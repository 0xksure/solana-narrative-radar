"""
API Rate Limiting & Usage Tracking middleware.

In-memory counters (reset hourly) + PostgreSQL persistent log.
"""
import asyncio
import hashlib
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Tuple

import asyncpg
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Tier limits (requests per hour)
TIER_LIMITS = {
    "anonymous": 30,
    "free": 100,
    "pro": 1000,
    "enterprise": None,  # unlimited
}

# In-memory rate counters: key -> list of timestamps
_rate_counters: dict[str, list[float]] = defaultdict(list)
_counter_lock = asyncio.Lock()

# Cache of key_hash -> (id, tier) to avoid DB lookups on every request
_key_cache: dict[str, Tuple[int, str]] = {}
_key_cache_ttl: dict[str, float] = {}
KEY_CACHE_TTL = 300  # 5 minutes

# DB pool
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> Optional[asyncpg.Pool]:
    global _pool
    if not DATABASE_URL:
        return None
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, ssl="require")
    return _pool


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"snr-rl-{ip}".encode()).hexdigest()[:16]


def generate_api_key() -> str:
    return f"snr_{secrets.token_urlsafe(32)}"


async def lookup_api_key(key_hash: str) -> Optional[Tuple[int, str]]:
    """Returns (id, tier) or None."""
    now = time.time()
    if key_hash in _key_cache and _key_cache_ttl.get(key_hash, 0) > now:
        return _key_cache[key_hash]

    try:
        pool = await get_pool()
        if pool is None:
            return None
        row = await pool.fetchrow(
            "SELECT id, tier FROM api_keys WHERE key_hash = $1", key_hash
        )
        if row:
            result = (row["id"], row["tier"])
            _key_cache[key_hash] = result
            _key_cache_ttl[key_hash] = now + KEY_CACHE_TTL
            # Update last_used_at (fire and forget)
            asyncio.create_task(_update_last_used(pool, row["id"]))
            return result
    except Exception as e:
        logger.warning(f"API key lookup failed: {e}")
    return None


async def _update_last_used(pool, key_id: int):
    try:
        await pool.execute(
            "UPDATE api_keys SET last_used_at = NOW(), requests_today = requests_today + 1, requests_total = requests_total + 1 WHERE id = $1",
            key_id,
        )
    except Exception:
        pass


async def log_usage(api_key_id: Optional[int], ip_hash: str, endpoint: str, method: str, response_time_ms: int, status_code: int):
    try:
        pool = await get_pool()
        if pool is None:
            return
        await pool.execute(
            """INSERT INTO api_usage_log (api_key_id, ip_hash, endpoint, method, timestamp, response_time_ms, status_code)
               VALUES ($1, $2, $3, $4, NOW(), $5, $6)""",
            api_key_id, ip_hash, endpoint, method, response_time_ms, status_code,
        )
    except Exception as e:
        logger.warning(f"Usage log failed: {e}")


def _prune_and_count(counter_key: str, window: float = 3600.0) -> int:
    """Prune old entries and return current count."""
    now = time.time()
    timestamps = _rate_counters[counter_key]
    _rate_counters[counter_key] = [t for t in timestamps if now - t < window]
    return len(_rate_counters[counter_key])


def _get_reset_time() -> int:
    """Seconds until the current hour window resets."""
    now = time.time()
    # Reset at the top of each hour
    return int(3600 - (now % 3600))


# Paths to skip rate limiting
SKIP_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # Skip static files and non-API paths
        if path in SKIP_PATHS or path.startswith("/assets") or path.startswith("/static"):
            return await call_next(request)

        start_time = time.time()
        client_ip = request.client.host if request.client else "0.0.0.0"
        ip_hash_val = hash_ip(client_ip)

        # Extract API key
        raw_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        api_key_id = None
        tier = "anonymous"
        counter_key = f"ip:{ip_hash_val}"

        if raw_key:
            key_hash_val = hash_key(raw_key)
            result = await lookup_api_key(key_hash_val)
            if result:
                api_key_id, tier = result
                counter_key = f"key:{api_key_id}"
            # If key provided but not found, treat as anonymous

        # Check rate limit
        limit = TIER_LIMITS.get(tier)
        remaining = None
        if limit is not None:
            async with _counter_lock:
                count = _prune_and_count(counter_key)
                if count >= limit:
                    reset = _get_reset_time()
                    # Log the 429
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    asyncio.create_task(log_usage(api_key_id, ip_hash_val, path, request.method, elapsed_ms, 429))
                    resp = JSONResponse(
                        {"detail": "Rate limit exceeded", "retry_after": reset},
                        status_code=429,
                    )
                    resp.headers["Retry-After"] = str(reset)
                    resp.headers["X-RateLimit-Limit"] = str(limit)
                    resp.headers["X-RateLimit-Remaining"] = "0"
                    resp.headers["X-RateLimit-Reset"] = str(reset)
                    return resp
                _rate_counters[counter_key].append(time.time())
                remaining = limit - count - 1

        # Process request
        response: Response = await call_next(request)

        # Add rate limit headers
        reset = _get_reset_time()
        if limit is not None:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, remaining or 0))
            response.headers["X-RateLimit-Reset"] = str(reset)
        else:
            response.headers["X-RateLimit-Limit"] = "unlimited"

        # Log usage async
        elapsed_ms = int((time.time() - start_time) * 1000)
        asyncio.create_task(log_usage(api_key_id, ip_hash_val, path, request.method, elapsed_ms, response.status_code))

        return response


# ── API Key Management ──

async def register_key(name: str, email: str) -> dict:
    raw_key = generate_api_key()
    key_hash_val = hash_key(raw_key)
    key_prefix = raw_key[:8]

    pool = await get_pool()
    # Check if email already has a key
    existing = await pool.fetchrow("SELECT key_prefix FROM api_keys WHERE email = $1", email)
    if existing:
        return {"error": "Email already registered. Contact support to recover your key."}

    await pool.execute(
        """INSERT INTO api_keys (key_hash, key_prefix, name, email, tier)
           VALUES ($1, $2, $3, $4, 'free')""",
        key_hash_val, key_prefix, name, email,
    )
    return {
        "api_key": raw_key,
        "prefix": key_prefix,
        "tier": "free",
        "rate_limit": TIER_LIMITS["free"],
        "message": "Save this key — it cannot be retrieved later.",
    }


async def get_key_usage(raw_key: str) -> Optional[dict]:
    key_hash_val = hash_key(raw_key)
    pool = await get_pool()
    if pool is None:
        return {"error": "Database not configured"}
    row = await pool.fetchrow(
        "SELECT id, key_prefix, name, email, tier, created_at, last_used_at, requests_today, requests_total FROM api_keys WHERE key_hash = $1",
        key_hash_val,
    )
    if not row:
        return None

    # Recent usage breakdown
    recent = await pool.fetch(
        """SELECT endpoint, COUNT(*) as count, AVG(response_time_ms) as avg_ms
           FROM api_usage_log WHERE api_key_id = $1 AND timestamp > NOW() - INTERVAL '24 hours'
           GROUP BY endpoint ORDER BY count DESC LIMIT 10""",
        row["id"],
    )

    return {
        "prefix": row["key_prefix"],
        "name": row["name"],
        "tier": row["tier"],
        "rate_limit": TIER_LIMITS.get(row["tier"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None,
        "requests_today": row["requests_today"],
        "requests_total": row["requests_total"],
        "recent_endpoints": [
            {"endpoint": r["endpoint"], "count": r["count"], "avg_response_ms": round(float(r["avg_ms"] or 0), 1)}
            for r in recent
        ],
    }


async def get_usage_stats() -> dict:
    """Internal monitoring stats."""
    pool = await get_pool()

    today = await pool.fetchrow(
        "SELECT COUNT(*) as total, COUNT(DISTINCT ip_hash) as unique_ips, AVG(response_time_ms) as avg_ms FROM api_usage_log WHERE timestamp > NOW() - INTERVAL '24 hours'"
    )
    top_endpoints = await pool.fetch(
        "SELECT endpoint, COUNT(*) as count FROM api_usage_log WHERE timestamp > NOW() - INTERVAL '24 hours' GROUP BY endpoint ORDER BY count DESC LIMIT 10"
    )
    total_keys = await pool.fetchval("SELECT COUNT(*) FROM api_keys")
    by_tier = await pool.fetch("SELECT tier, COUNT(*) as count FROM api_keys GROUP BY tier")

    return {
        "today": {
            "total_requests": today["total"] if today else 0,
            "unique_ips": today["unique_ips"] if today else 0,
            "avg_response_ms": round(float(today["avg_ms"] or 0), 1) if today else 0,
        },
        "top_endpoints": [{"endpoint": r["endpoint"], "count": r["count"]} for r in top_endpoints],
        "api_keys": {
            "total": total_keys,
            "by_tier": {r["tier"]: r["count"] for r in by_tier},
        },
    }
