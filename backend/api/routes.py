from fastapi import APIRouter, HTTPException, Request
from typing import Optional
import json
import os
import asyncio
import hashlib
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

router = APIRouter()

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "latest_report.json")
STATUS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "pipeline_status.json")
ANALYTICS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "analytics.jsonl")

# Rate limiting: track events per hashed IP
_rate_limit: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 100
RATE_LIMIT_WINDOW = 3600  # 1 hour


@router.get("/narratives")
async def get_narratives(period: Optional[str] = "current"):
    """Get detected narratives for the current or historical period"""
    try:
        if os.path.exists(REPORT_PATH):
            with open(REPORT_PATH) as f:
                return json.load(f)

        # Check if pipeline is currently running
        status = _load_status()
        if status.get("status") == "running":
            return {"narratives": [], "message": "Generating first report... please wait."}
        return {"narratives": [], "message": "No report generated yet. Run the collector first."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals")
async def get_signals():
    """Get raw signals collected from all sources"""
    signals_path = os.path.join(os.path.dirname(__file__), "..", "data", "signals.json")
    if os.path.exists(signals_path):
        with open(signals_path) as f:
            return json.load(f)
    return {"signals": []}


@router.post("/generate")
async def generate_report():
    """Trigger a new narrative detection run (non-blocking)"""
    from main import _pipeline_lock, run_pipeline_task

    if _pipeline_lock.locked():
        return {"status": "already_running", "eta_seconds": 15}

    asyncio.create_task(run_pipeline_task())
    return {"status": "generating", "eta_seconds": 20}


@router.get("/status")
async def get_status():
    """Get pipeline status and metadata"""
    status = _load_status()
    if not status:
        return {
            "last_run": None,
            "next_run": None,
            "status": "idle",
            "duration_seconds": None,
            "signal_count": 0,
            "narrative_count": 0,
        }
    return {
        "last_run": status.get("last_run"),
        "next_run": status.get("next_run"),
        "status": status.get("status", "idle"),
        "duration_seconds": status.get("duration_seconds"),
        "signal_count": status.get("signal_count", 0),
        "narrative_count": status.get("narrative_count", 0),
    }


@router.get("/stats")
async def get_stats():
    """Get agent tracking statistics"""
    try:
        from engine.store import get_stats as db_stats
        stats = db_stats()
        return {"agent": "autonomous", "loop_hours": 2, **stats}
    except Exception as e:
        return {"error": str(e)}


@router.get("/velocity/{topic}")
async def get_velocity(topic: str, days: int = 7):
    """Get signal velocity for a specific topic"""
    try:
        from engine.store import get_signal_velocity
        return get_signal_velocity(topic, days)
    except Exception as e:
        return {"error": str(e)}


def _load_status():
    try:
        with open(STATUS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


@router.get("/config")
async def get_config():
    """Return public frontend config (e.g. Sentry DSN)."""
    return {
        "sentry_dsn": os.getenv("SENTRY_DSN", ""),
    }


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(f"snr-salt-{ip}".encode()).hexdigest()[:16]


def _check_rate_limit(ip_hash: str) -> bool:
    now = time.time()
    timestamps = _rate_limit[ip_hash]
    # Prune old entries
    _rate_limit[ip_hash] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    return len(_rate_limit[ip_hash]) < RATE_LIMIT_MAX


@router.post("/analytics")
async def track_event(request: Request):
    """Store an analytics event."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = body.get("event")
    if not event or not isinstance(event, str):
        raise HTTPException(status_code=400, detail="Missing 'event' field")

    client_ip = request.client.host if request.client else "unknown"
    ip_hash = _hash_ip(client_ip)

    if not _check_rate_limit(ip_hash):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    _rate_limit[ip_hash].append(time.time())

    record = {
        "event": event[:100],
        "properties": body.get("properties", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip_hash": ip_hash,
        "user_agent": (request.headers.get("user-agent") or "")[:200],
    }

    os.makedirs(os.path.dirname(ANALYTICS_PATH), exist_ok=True)
    with open(ANALYTICS_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

    return {"ok": True}


@router.get("/analytics/summary")
async def analytics_summary():
    """Return aggregated analytics stats."""
    if not os.path.exists(ANALYTICS_PATH):
        return {"total_events": 0, "periods": {}, "top_events": [], "unique_visitors": 0, "top_referrers": []}

    now = datetime.now(timezone.utc)
    events = []
    try:
        with open(ANALYTICS_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except Exception:
        pass

    # Aggregate
    event_counts = defaultdict(int)
    visitors = set()
    referrers = defaultdict(int)
    periods = {"today": 0, "7d": 0, "30d": 0}

    for e in events:
        event_counts[e.get("event", "unknown")] += 1
        visitors.add(e.get("ip_hash", ""))
        ref = (e.get("properties") or {}).get("referrer", "")
        if ref:
            referrers[ref] += 1

        try:
            ts = datetime.fromisoformat(e["timestamp"])
            age = now - ts
            if age < timedelta(days=1):
                periods["today"] += 1
            if age < timedelta(days=7):
                periods["7d"] += 1
            if age < timedelta(days=30):
                periods["30d"] += 1
        except Exception:
            pass

    top_events = sorted(event_counts.items(), key=lambda x: -x[1])[:10]
    top_referrers = sorted(referrers.items(), key=lambda x: -x[1])[:10]

    return {
        "total_events": len(events),
        "unique_visitors": len(visitors),
        "periods": periods,
        "top_events": [{"event": k, "count": v} for k, v in top_events],
        "top_referrers": [{"referrer": k, "count": v} for k, v in top_referrers],
    }
