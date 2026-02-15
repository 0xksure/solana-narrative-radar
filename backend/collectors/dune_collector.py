"""Collect Solana on-chain analytics from Dune Analytics and Flipside Crypto"""
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Popular public Dune query IDs for Solana metrics
DUNE_QUERIES = {
    "dex_volume": 3296006,        # Solana DEX daily volume
    "active_wallets": 2781859,    # Solana daily active wallets
    "program_usage": 3521862,     # Top Solana programs by tx count
    "stablecoin_flows": 3303060,  # USDC/USDT volume on Solana
    "new_tokens": 3466513,        # New SPL token launches
}

# Flipside SQL queries as fallback
FLIPSIDE_QUERIES = {
    "dex_volume": """
        SELECT DATE_TRUNC('day', block_timestamp) as dt,
               SUM(swap_to_amount_usd) as volume_usd
        FROM solana.defi.fact_swaps
        WHERE block_timestamp >= CURRENT_DATE - 14
        GROUP BY 1 ORDER BY 1
    """,
    "active_wallets": """
        SELECT DATE_TRUNC('day', block_timestamp) as dt,
               COUNT(DISTINCT signers[0]) as wallets
        FROM solana.core.fact_transactions
        WHERE block_timestamp >= CURRENT_DATE - 14 AND succeeded = TRUE
        GROUP BY 1 ORDER BY 1
    """,
    "stablecoin_flows": """
        SELECT DATE_TRUNC('day', block_timestamp) as dt,
               SUM(swap_to_amount_usd) as volume_usd
        FROM solana.defi.fact_swaps
        WHERE block_timestamp >= CURRENT_DATE - 14
          AND (LOWER(swap_to_mint) IN (
            'epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v', -- USDC
            'es9vmfrzacermjfrf4h2fyd4kconky11mcce8benwnyb'  -- USDT
          ) OR LOWER(swap_from_mint) IN (
            'epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v',
            'es9vmfrzacermjfrf4h2fyd4kconky11mcce8benwnyb'
          ))
        GROUP BY 1 ORDER BY 1
    """,
}


async def _fetch_dune_cached(client: httpx.AsyncClient, query_id: int) -> Optional[Dict]:
    """Fetch cached results from a public Dune query (no API key needed)."""
    try:
        resp = await client.get(
            f"https://api.dune.com/api/v1/query/{query_id}/results",
            headers={"X-Dune-API-Key": os.environ.get("DUNE_API_KEY", "")},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.debug(f"Dune API query {query_id} failed: {e}")

    # Try public cache endpoint (no key needed)
    try:
        resp = await client.get(
            f"https://dune.com/api/cache/v1/query/{query_id}/results",
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.debug(f"Dune cache query {query_id} failed: {e}")

    return None


async def _fetch_flipside(client: httpx.AsyncClient, sql: str) -> Optional[List[Dict]]:
    """Run a query on Flipside Crypto (free tier, no key needed)."""
    try:
        # Create query run
        resp = await client.post(
            "https://api-v2.flipsidecrypto.xyz/json-rpc",
            json={
                "jsonrpc": "2.0",
                "method": "createQueryRun",
                "params": [{"sql": sql, "ttlMinutes": 60, "resultFormat": "csv"}],
                "id": 1,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        run_id = data.get("result", {}).get("queryRun", {}).get("id")
        if not run_id:
            return None

        # Poll for results (up to 60s)
        import asyncio
        for _ in range(12):
            await asyncio.sleep(5)
            resp = await client.post(
                "https://api-v2.flipsidecrypto.xyz/json-rpc",
                json={
                    "jsonrpc": "2.0",
                    "method": "getQueryRunResults",
                    "params": [{"queryRunId": run_id, "format": "json", "page": {"number": 1, "size": 100}}],
                    "id": 1,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                continue
            result = resp.json().get("result", {})
            status = result.get("queryRun", {}).get("state")
            if status == "QUERY_STATE_SUCCESS":
                return result.get("rows", [])
            if status and "FAILED" in status:
                logger.warning(f"Flipside query failed: {status}")
                return None
        logger.warning("Flipside query timed out")
        return None
    except Exception as e:
        logger.debug(f"Flipside query failed: {e}")
        return None


def _pct_change(values: List[float], period: int = 7) -> Optional[float]:
    """Calculate percentage change over a period."""
    if len(values) < period + 1:
        return None
    recent = sum(values[-period:]) / period
    previous = sum(values[-2 * period:-period]) / period if len(values) >= 2 * period else values[0]
    if previous == 0:
        return None
    return ((recent - previous) / previous) * 100


def _make_signal(name: str, content: str, topics: List[str], engagement: float,
                 metric: str, value: float, change_pct: float, source_name: str = "dune") -> Dict:
    return {
        "name": name,
        "content": content,
        "source": "defi",
        "topics": topics,
        "engagement": min(max(engagement, 0), 100),
        "metadata": {
            "source": source_name,
            "metric": metric,
            "value": value,
            "change_pct": round(change_pct, 1),
            "collected_at": datetime.utcnow().isoformat(),
        },
    }


def _volume_to_engagement(change_pct: float) -> float:
    """Map percentage change to engagement score (0-100)."""
    if change_pct > 100:
        return 95
    if change_pct > 50:
        return 80
    if change_pct > 20:
        return 65
    if change_pct > 0:
        return 40
    return 20


async def _collect_from_dune(client: httpx.AsyncClient) -> List[Dict]:
    """Try collecting from Dune Analytics."""
    signals = []

    for metric_name, query_id in DUNE_QUERIES.items():
        data = await _fetch_dune_cached(client, query_id)
        if not data:
            continue

        rows = (data.get("result", {}).get("rows", [])
                or data.get("data", {}).get("rows", []))
        if not rows:
            continue

        logger.info(f"Dune {metric_name}: got {len(rows)} rows")

        # Extract time-series values
        value_key = None
        for key in ["volume_usd", "volume", "wallets", "count", "tx_count", "total_volume", "amount"]:
            if key in rows[0]:
                value_key = key
                break
        if not value_key:
            # Use first numeric column
            for k, v in rows[0].items():
                if isinstance(v, (int, float)) and k not in ("dt", "date", "day"):
                    value_key = k
                    break
        if not value_key:
            continue

        values = [float(r.get(value_key, 0)) for r in rows if r.get(value_key) is not None]
        if not values:
            continue

        latest = values[-1]
        change = _pct_change(values)
        if change is None:
            continue

        engagement = _volume_to_engagement(abs(change))

        if metric_name == "dex_volume" and abs(change) > 15:
            direction = "surges" if change > 0 else "drops"
            signals.append(_make_signal(
                f"Solana DEX volume {direction} {abs(change):.0f}% week-over-week",
                f"Daily DEX volume at ${latest:,.0f}. Week-over-week change of {change:+.1f}%.",
                ["defi", "dex", "volume"], engagement, "dex_volume", latest, change,
            ))
        elif metric_name == "active_wallets" and abs(change) > 10:
            direction = "accelerating" if change > 0 else "declining"
            signals.append(_make_signal(
                f"Solana user onboarding {direction}: wallets {change:+.0f}%",
                f"Daily active wallets at {latest:,.0f}. Week-over-week change of {change:+.1f}%.",
                ["adoption", "wallets", "users"], engagement, "active_wallets", latest, change,
            ))
        elif metric_name == "stablecoin_flows" and abs(change) > 15:
            direction = "inflows surge" if change > 0 else "outflows detected"
            signals.append(_make_signal(
                f"Solana stablecoin {direction}: {change:+.0f}% WoW",
                f"Stablecoin volume at ${latest:,.0f}. Week-over-week change of {change:+.1f}%.",
                ["defi", "stablecoins", "liquidity"], engagement, "stablecoin_flows", latest, change,
            ))
        elif metric_name == "new_tokens" and abs(change) > 20:
            direction = "spike" if change > 0 else "cooldown"
            signals.append(_make_signal(
                f"New SPL token launches {direction}: {change:+.0f}% WoW",
                f"Daily new token launches at {latest:,.0f}. Change of {change:+.1f}% week-over-week.",
                ["tokens", "launches", "ecosystem"], engagement, "new_tokens", latest, change,
            ))
        elif metric_name == "program_usage":
            # For program usage, look at top programs
            if isinstance(rows[0], dict) and any(k in rows[0] for k in ["program", "program_id", "program_name"]):
                prog_key = next((k for k in ["program_name", "program", "program_id"] if k in rows[0]), None)
                if prog_key and len(rows) >= 1:
                    top = rows[0]
                    signals.append(_make_signal(
                        f"Top Solana program: {top.get(prog_key, 'Unknown')} leads in transactions",
                        f"Most active program: {top.get(prog_key, 'Unknown')} with {top.get(value_key, 0):,.0f} transactions.",
                        ["infrastructure", "programs", "activity"],
                        50, "program_usage", float(top.get(value_key, 0)), 0, 
                    ))

    return signals


async def _collect_from_flipside(client: httpx.AsyncClient) -> List[Dict]:
    """Fallback: collect from Flipside Crypto."""
    signals = []

    for metric_name, sql in FLIPSIDE_QUERIES.items():
        rows = await _fetch_flipside(client, sql)
        if not rows:
            continue

        logger.info(f"Flipside {metric_name}: got {len(rows)} rows")

        value_key = None
        for key in ["volume_usd", "wallets"]:
            if key in rows[0]:
                value_key = key
                break
        if not value_key:
            continue

        values = [float(r.get(value_key, 0)) for r in rows if r.get(value_key) is not None]
        if not values:
            continue

        latest = values[-1]
        change = _pct_change(values)
        if change is None:
            continue

        engagement = _volume_to_engagement(abs(change))

        if metric_name == "dex_volume" and abs(change) > 15:
            direction = "surges" if change > 0 else "drops"
            signals.append(_make_signal(
                f"Solana DEX volume {direction} {abs(change):.0f}% WoW",
                f"Daily DEX volume at ${latest:,.0f}. Week-over-week change of {change:+.1f}%.",
                ["defi", "dex", "volume"], engagement, "dex_volume", latest, change, "flipside",
            ))
        elif metric_name == "active_wallets" and abs(change) > 10:
            direction = "accelerating" if change > 0 else "declining"
            signals.append(_make_signal(
                f"Solana wallet activity {direction}: {change:+.0f}% WoW",
                f"Daily active wallets at {latest:,.0f}. Change of {change:+.1f}%.",
                ["adoption", "wallets", "users"], engagement, "active_wallets", latest, change, "flipside",
            ))
        elif metric_name == "stablecoin_flows" and abs(change) > 15:
            direction = "inflows surge" if change > 0 else "outflows detected"
            signals.append(_make_signal(
                f"Solana stablecoin {direction}: {change:+.0f}% WoW",
                f"Stablecoin volume at ${latest:,.0f}. Change of {change:+.1f}%.",
                ["defi", "stablecoins", "liquidity"], engagement, "stablecoin_flows", latest, change, "flipside",
            ))

    return signals


async def collect() -> List[Dict]:
    """Collect on-chain analytics signals from Dune Analytics or Flipside Crypto."""
    signals = []
    async with httpx.AsyncClient() as client:
        # Try Dune first
        dune_key = os.environ.get("DUNE_API_KEY")
        if dune_key:
            logger.info("Collecting from Dune Analytics (API key set)")
            signals = await _collect_from_dune(client)
        else:
            logger.info("No DUNE_API_KEY set, trying public cache endpoints")
            signals = await _collect_from_dune(client)

        # If Dune yielded nothing, try Flipside
        if not signals:
            logger.info("Dune returned no signals, trying Flipside Crypto")
            signals = await _collect_from_flipside(client)

        if not signals:
            logger.warning("Neither Dune nor Flipside returned usable signals")

    logger.info(f"Dune/Flipside collector: {len(signals)} signals")
    return signals
