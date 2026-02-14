"""PostgreSQL-backed analytics event store."""

import os
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def insert_event(
    app: str, event: str, properties: dict,
    session_id: str = None, ip_hash: str = None,
    user_agent: str = None, referrer: str = None, path: str = None,
):
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO analytics_events (app, event, properties, session_id, ip_hash, user_agent, referrer, path)
           VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8)""",
        app, event, __import__('json').dumps(properties),
        session_id, ip_hash, user_agent, referrer, path,
    )


async def get_summary(app: str = None, days: int = 30) -> dict:
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    app_filter = "AND app = $2" if app else ""
    args = [cutoff, app] if app else [cutoff]

    total = await pool.fetchval(
        f"SELECT COUNT(*) FROM analytics_events WHERE created_at > $1 {app_filter}", *args
    )
    unique_sessions = await pool.fetchval(
        f"SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at > $1 AND session_id IS NOT NULL {app_filter}", *args
    )
    top_events = await pool.fetch(
        f"SELECT event, COUNT(*) as cnt FROM analytics_events WHERE created_at > $1 {app_filter} GROUP BY event ORDER BY cnt DESC LIMIT 10", *args
    )
    top_pages = await pool.fetch(
        f"SELECT path, COUNT(*) as cnt FROM analytics_events WHERE created_at > $1 AND path IS NOT NULL {app_filter} GROUP BY path ORDER BY cnt DESC LIMIT 10", *args
    )
    top_referrers = await pool.fetch(
        f"SELECT referrer, COUNT(*) as cnt FROM analytics_events WHERE created_at > $1 AND referrer IS NOT NULL AND referrer != '' {app_filter} GROUP BY referrer ORDER BY cnt DESC LIMIT 10", *args
    )
    daily = await pool.fetch(
        f"SELECT date(created_at) as day, COUNT(*) as cnt FROM analytics_events WHERE created_at > $1 {app_filter} GROUP BY day ORDER BY day", *args
    )

    return {
        "total_events": total,
        "unique_sessions": unique_sessions,
        "top_events": [{"event": r["event"], "count": r["cnt"]} for r in top_events],
        "top_pages": [{"path": r["path"], "count": r["cnt"]} for r in top_pages],
        "top_referrers": [{"referrer": r["referrer"], "count": r["cnt"]} for r in top_referrers],
        "daily": [{"date": str(r["day"]), "count": r["cnt"]} for r in daily],
        "days": days,
        "app": app,
    }


async def get_events_breakdown(app: str, event: str, days: int = 7) -> dict:
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    daily = await pool.fetch(
        "SELECT date(created_at) as day, COUNT(*) as cnt, COUNT(DISTINCT session_id) as sessions FROM analytics_events WHERE created_at > $1 AND app = $2 AND event = $3 GROUP BY day ORDER BY day",
        cutoff, app, event,
    )
    top_props = await pool.fetch(
        "SELECT properties, COUNT(*) as cnt FROM analytics_events WHERE created_at > $1 AND app = $2 AND event = $3 GROUP BY properties ORDER BY cnt DESC LIMIT 20",
        cutoff, app, event,
    )

    return {
        "event": event, "app": app, "days": days,
        "daily": [{"date": str(r["day"]), "count": r["cnt"], "unique_sessions": r["sessions"]} for r in daily],
        "top_properties": [{"properties": __import__('json').loads(r["properties"]), "count": r["cnt"]} for r in top_props],
    }


async def get_funnel(app: str, days: int = 30) -> dict:
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if app == "roast-bot":
        steps = ["Page View", "Wallet Submitted", "Roast Generated", "Roast Shared"]
    elif app == "blog":
        steps = ["Page View", "Article Viewed", "Scroll Depth", "Article Read Time"]
    else:
        steps = ["page_view"]

    results = []
    for step_name in steps:
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM analytics_events WHERE created_at > $1 AND app = $2 AND event = $3",
            cutoff, app, step_name,
        )
        sessions = await pool.fetchval(
            "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at > $1 AND app = $2 AND event = $3 AND session_id IS NOT NULL",
            cutoff, app, step_name,
        )
        results.append({"step": step_name, "count": count, "unique_sessions": sessions})

    return {"app": app, "days": days, "funnel": results}


async def get_retention(app: str, days: int = 30) -> dict:
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    returning = await pool.fetchval(
        """SELECT COUNT(DISTINCT session_id) FROM analytics_events
           WHERE created_at > $1 AND app = $2 AND session_id IS NOT NULL
           AND session_id IN (
               SELECT session_id FROM analytics_events
               WHERE created_at > $1 AND app = $2 AND session_id IS NOT NULL
               GROUP BY session_id HAVING COUNT(DISTINCT date(created_at)) > 1
           )""",
        cutoff, app,
    )
    total = await pool.fetchval(
        "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at > $1 AND app = $2 AND session_id IS NOT NULL",
        cutoff, app,
    )

    return {
        "app": app, "days": days,
        "total_sessions": total,
        "returning_sessions": returning,
        "retention_rate": round(returning / total * 100, 1) if total > 0 else 0,
    }


async def get_realtime(app: str = None) -> dict:
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    app_filter = "AND app = $2" if app and app != "all" else ""
    args = [cutoff, app] if app and app != "all" else [cutoff]

    count = await pool.fetchval(
        f"SELECT COUNT(*) FROM analytics_events WHERE created_at > $1 {app_filter}", *args
    )
    sessions = await pool.fetchval(
        f"SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at > $1 AND session_id IS NOT NULL {app_filter}", *args
    )
    pages = await pool.fetch(
        f"SELECT path, COUNT(*) as cnt FROM analytics_events WHERE created_at > $1 AND path IS NOT NULL {app_filter} GROUP BY path ORDER BY cnt DESC LIMIT 10", *args
    )

    return {
        "period": "last_30_minutes",
        "events": count,
        "active_sessions": sessions,
        "current_pages": [{"path": r["path"], "count": r["cnt"]} for r in pages],
    }


async def run_daily_rollup():
    """Aggregate yesterday's events into daily rollup."""
    pool = await get_pool()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    await pool.execute(
        """INSERT INTO analytics_daily_rollup (app, event, date, count, unique_sessions)
           SELECT app, event, date(created_at), COUNT(*), COUNT(DISTINCT session_id)
           FROM analytics_events
           WHERE date(created_at) = $1
           GROUP BY app, event, date(created_at)
           ON CONFLICT (app, event, date) DO UPDATE SET
               count = EXCLUDED.count,
               unique_sessions = EXCLUDED.unique_sessions""",
        yesterday,
    )


async def cleanup_old_events(days: int = 90):
    """Delete raw events older than N days (rollups are kept forever)."""
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    await pool.execute("DELETE FROM analytics_events WHERE created_at < $1", cutoff)
