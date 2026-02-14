from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from typing import Optional, List
import json
import os
import asyncio
import hashlib
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

router = APIRouter()
agent_router = APIRouter(prefix="/agent", tags=["Agent API"])

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "latest_report.json")
STATUS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "pipeline_status.json")
ANALYTICS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "analytics.jsonl")

from engine.narrative_store import (
    load_store, get_active_narratives, get_recently_faded, store_entry_to_api,
    get_all_narratives, get_narrative_timeline, get_narrative_signals_history,
    get_narrative_signals_count,
)

# Rate limiting: track events per hashed IP
_rate_limit: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 100
RATE_LIMIT_WINDOW = 3600  # 1 hour


@router.get("/narratives")
async def get_narratives(period: Optional[str] = "current", include_historical: bool = False):
    """Get detected narratives from the persistent store (ACTIVE + recently FADED, optionally all)"""
    try:
        # Try persistent store first
        store = load_store()
        if store.get("narratives"):
            if include_historical:
                all_entries = get_all_narratives(store, include_archived=True)
                total_runs = store.get("total_pipeline_runs", 0)
                api_narratives = []
                for entry in all_entries:
                    api_entry = store_entry_to_api(entry)
                    api_entry["total_pipeline_runs"] = total_runs
                    api_narratives.append(api_entry)
            else:
                active = get_active_narratives(store)
                faded = get_recently_faded(store, hours=24)
                total_runs = store.get("total_pipeline_runs", 0)
                api_narratives = []
                for entry in active + faded:
                    api_entry = store_entry_to_api(entry)
                    api_entry["total_pipeline_runs"] = total_runs
                    api_narratives.append(api_entry)

            # Load report for signal_summary and other metadata
            report = {}
            if os.path.exists(REPORT_PATH):
                with open(REPORT_PATH) as f:
                    report = json.load(f)

            return {
                "narratives": api_narratives,
                "signal_summary": report.get("signal_summary", {}),
                "generated_at": report.get("generated_at", store.get("last_updated", "")),
                "report_period": report.get("report_period", {}),
                "version": "0.2.0",
            }

        # Fall back to report file
        if os.path.exists(REPORT_PATH):
            with open(REPORT_PATH) as f:
                return json.load(f)

        status = _load_status()
        if status.get("status") == "running":
            return {"narratives": [], "message": "Generating first report... please wait."}
        return {"narratives": [], "message": "No report generated yet. Run the collector first."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/narratives/all")
async def get_all_narratives_endpoint():
    """Get ALL narratives ever detected, grouped by status."""
    try:
        all_entries = get_all_narratives(include_archived=True)
        total_runs = load_store().get("total_pipeline_runs", 0)

        grouped = {"active": [], "faded": [], "historical": []}
        for entry in all_entries:
            api_entry = store_entry_to_api(entry)
            api_entry["total_pipeline_runs"] = total_runs
            api_entry["id"] = entry.get("id", "")
            status = entry.get("status", "").upper()
            if status == "ACTIVE":
                grouped["active"].append(api_entry)
            elif status == "FADED":
                grouped["faded"].append(api_entry)
            else:
                grouped["historical"].append(api_entry)

        return {
            **grouped,
            "total_ever_detected": len(all_entries),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/narratives/{narrative_id}/timeline")
async def get_narrative_timeline_endpoint(narrative_id: str):
    """Get how a narrative evolved over time."""
    try:
        snapshots = get_narrative_timeline(narrative_id)
        if not snapshots:
            raise HTTPException(status_code=404, detail="No timeline data found")

        total_signals = get_narrative_signals_count(narrative_id)
        return {
            "narrative": {
                "name": snapshots[-1].get("name", "") if snapshots else "",
                "current_status": snapshots[-1].get("status", "") if snapshots else "",
            },
            "snapshots": [
                {
                    "date": s.get("snapshot_at", ""),
                    "status": s.get("status", ""),
                    "confidence": s.get("confidence", ""),
                    "direction": s.get("direction", ""),
                    "signal_count": s.get("signal_count", 0),
                    "pipeline_run": s.get("pipeline_run"),
                }
                for s in snapshots
            ],
            "total_signals_ever": total_signals,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/narratives/{narrative_id}/signals")
async def get_narrative_signals_endpoint(narrative_id: str, limit: int = 100):
    """Get full signal history for a narrative."""
    try:
        history = get_narrative_signals_history(narrative_id, limit=limit)
        # Get narrative name
        store = load_store()
        name = ""
        for nid, entry in store.get("narratives", {}).items():
            if nid == narrative_id:
                name = entry.get("name", "")
                break

        return {
            "narrative": name,
            "signals": [h["signal"] for h in history],
            "signals_with_meta": history,
            "total": get_narrative_signals_count(narrative_id),
        }
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


@router.get("/history")
async def get_history(days: int = 30):
    """Get signal counts per day for the last N days"""
    try:
        from engine.store import get_db
        conn = get_db()
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            rows = conn.execute("""
                SELECT date(collected_at) as day, COUNT(*) as signal_count,
                       COUNT(DISTINCT source) as source_count
                FROM signals
                WHERE collected_at > ?
                GROUP BY date(collected_at)
                ORDER BY day
            """, (cutoff,)).fetchall()

            narrative_rows = conn.execute("""
                SELECT date(generated_at) as day, COUNT(*) as narrative_count
                FROM narratives
                WHERE generated_at > ?
                GROUP BY date(generated_at)
                ORDER BY day
            """, (cutoff,)).fetchall()

            narrative_map = {str(r["day"]): r["narrative_count"] for r in narrative_rows}

            return {
                "days": days,
                "history": [
                    {
                        "date": str(r["day"]),
                        "signal_count": r["signal_count"],
                        "source_count": r["source_count"],
                        "narrative_count": narrative_map.get(str(r["day"]), 0),
                    }
                    for r in rows
                ],
            }
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
async def track_event_legacy(request: Request):
    """Legacy analytics endpoint — forwards to /analytics/event."""
    return await track_event(request)


@router.post("/analytics/event")
async def track_event(request: Request):
    """Store an analytics event in PostgreSQL."""
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

    app = body.get("app", "narrative-radar")[:50]
    properties = body.get("properties", {})
    session_id = body.get("session_id")
    user_agent = (request.headers.get("user-agent") or "")[:200]
    referrer = body.get("referrer") or request.headers.get("referer") or ""
    path = properties.get("path") or properties.get("page") or ""

    try:
        from engine.analytics_db import insert_event
        await insert_event(
            app=app, event=event[:100], properties=properties,
            session_id=session_id, ip_hash=ip_hash,
            user_agent=user_agent, referrer=referrer[:500], path=path[:500],
        )
    except Exception as e:
        # Fallback to file if DB fails
        record = {
            "app": app, "event": event[:100], "properties": properties,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ip_hash": ip_hash, "user_agent": user_agent,
        }
        os.makedirs(os.path.dirname(ANALYTICS_PATH), exist_ok=True)
        with open(ANALYTICS_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")

    return {"ok": True}


@router.get("/analytics/summary")
async def analytics_summary(app: Optional[str] = None, days: int = 30):
    """Return aggregated analytics stats from PostgreSQL."""
    try:
        from engine.analytics_db import get_summary
        return await get_summary(app=app, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/events")
async def analytics_events(app: str = "blog", event: str = "Page View", days: int = 7):
    """Event breakdown by day."""
    try:
        from engine.analytics_db import get_events_breakdown
        return await get_events_breakdown(app=app, event=event, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/funnel")
async def analytics_funnel(app: str = "roast-bot", days: int = 30):
    """Product funnel analysis."""
    try:
        from engine.analytics_db import get_funnel
        return await get_funnel(app=app, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/retention")
async def analytics_retention(app: str = "blog", days: int = 30):
    """Returning visitor analysis."""
    try:
        from engine.analytics_db import get_retention
        return await get_retention(app=app, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/realtime")
async def analytics_realtime(app: str = "all"):
    """Real-time analytics (last 30 minutes)."""
    try:
        from engine.analytics_db import get_realtime
        return await get_realtime(app=app)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Agent API helpers ──

CONFIDENCE_ORDER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
DIRECTION_ORDER = {"ACCELERATING": 3, "EMERGING": 2, "STABILIZING": 1}


def _load_report():
    """Load report, preferring persistent store for narratives."""
    store = load_store()
    if store.get("narratives"):
        active = get_active_narratives(store)
        faded = get_recently_faded(store, hours=24)
        total_runs = store.get("total_pipeline_runs", 0)
        api_narratives = []
        for entry in active + faded:
            api_entry = store_entry_to_api(entry)
            api_entry["total_pipeline_runs"] = total_runs
            api_narratives.append(api_entry)

        # Load base report for metadata
        report = {}
        if os.path.exists(REPORT_PATH):
            with open(REPORT_PATH) as f:
                report = json.load(f)
        report["narratives"] = api_narratives
        if not report.get("generated_at"):
            report["generated_at"] = store.get("last_updated", "")
        return report

    if not os.path.exists(REPORT_PATH):
        return None
    with open(REPORT_PATH) as f:
        return json.load(f)


def _idea_id(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()[:12]


def _freshness(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        delta = datetime.now(timezone.utc) - dt
        hours = int(delta.total_seconds() / 3600)
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)}m ago"
        if hours < 24:
            return f"{hours}h ago"
        return f"{delta.days}d ago"
    except Exception:
        return "unknown"


def _build_idea(idea: dict, narrative: dict, generated_at: str) -> dict:
    return {
        "id": _idea_id(idea["name"]),
        "name": idea["name"],
        "description": idea.get("description", ""),
        "narrative": narrative["name"],
        "narrative_confidence": narrative.get("confidence", "MEDIUM"),
        "narrative_direction": narrative.get("direction", "EMERGING"),
        "complexity": idea.get("complexity", "WEEKS"),
        "target_user": idea.get("target_user", ""),
        "solana_integrations": idea.get("solana_integrations", []),
        "market_analysis": idea.get("market_analysis", ""),
        "revenue_model": idea.get("revenue_model", ""),
        "key_metrics": idea.get("key_metrics", []),
        "reference_links": idea.get("reference_links", []),
        "supporting_evidence": narrative.get("supporting_signals", []),
        "freshness": _freshness(generated_at),
        "generated_at": generated_at,
    }


def _build_meta(report: dict) -> dict:
    sig = report.get("signal_summary", {})
    generated_at = report.get("generated_at", "")
    narratives = report.get("narratives", [])
    total_ideas = sum(len(n.get("ideas", [])) for n in narratives)
    total_signals = sig.get("total_collected", 0)

    sources = []
    for key in ["github", "twitter", "defillama", "onchain", "birdeye", "social"]:
        if sig.get(key, sig.get(f"{key}_signals", 0)):
            sources.append(key)
    if not sources:
        sources = list(sig.get("by_source", {}).keys()) if "by_source" in sig else ["github", "twitter", "defillama", "onchain"]

    try:
        gen_dt = datetime.fromisoformat(generated_at)
        next_update = (gen_dt + timedelta(hours=2)).isoformat()
    except Exception:
        next_update = ""

    return {
        "total_ideas": total_ideas,
        "total_narratives": len(narratives),
        "total_signals_analyzed": total_signals,
        "sources": sources,
        "last_updated": generated_at,
        "next_update": next_update,
        "update_frequency": "every 2 hours",
    }


@agent_router.get("/ideas", summary="List all build ideas", description="Returns all current Solana build ideas with full context, optimized for AI agent consumption. Filter by complexity, confidence, direction, or topic.")
async def agent_ideas(
    complexity: Optional[str] = Query(None, description="Filter by complexity: HOURS, DAYS, WEEKS, MONTHS"),
    min_confidence: Optional[str] = Query(None, description="Minimum narrative confidence: LOW, MEDIUM, HIGH"),
    direction: Optional[str] = Query(None, description="Filter by narrative direction: EMERGING, ACCELERATING, STABILIZING"),
    topic: Optional[str] = Query(None, description="Filter by topic keyword"),
):
    report = _load_report()
    if not report:
        raise HTTPException(status_code=503, detail="No report available yet. Pipeline may still be running.")

    generated_at = report.get("generated_at", "")
    ideas = []
    for narrative in report.get("narratives", []):
        conf = narrative.get("confidence", "MEDIUM")
        dirn = narrative.get("direction", "EMERGING")

        if min_confidence and CONFIDENCE_ORDER.get(conf, 0) < CONFIDENCE_ORDER.get(min_confidence.upper(), 0):
            continue
        if direction and dirn.upper() != direction.upper():
            continue
        if topic and topic.lower() not in [t.lower() for t in narrative.get("topics", [])]:
            continue

        for idea in narrative.get("ideas", []):
            if complexity and idea.get("complexity", "").upper() != complexity.upper():
                continue
            ideas.append(_build_idea(idea, narrative, generated_at))

    return {"ideas": ideas, "meta": _build_meta(report)}


@agent_router.get("/ideas/{idea_id}", summary="Get a single build idea", description="Returns full details for a specific build idea by its ID, including all supporting signals.")
async def agent_idea_detail(idea_id: str):
    report = _load_report()
    if not report:
        raise HTTPException(status_code=503, detail="No report available yet.")

    generated_at = report.get("generated_at", "")
    for narrative in report.get("narratives", []):
        for idea in narrative.get("ideas", []):
            if _idea_id(idea["name"]) == idea_id:
                return _build_idea(idea, narrative, generated_at)

    raise HTTPException(status_code=404, detail="Idea not found")


@agent_router.get("/narratives", summary="List all narratives", description="Returns all detected Solana narratives with clean structure, status, and signal counts per source.")
async def agent_narratives():
    report = _load_report()
    if not report:
        raise HTTPException(status_code=503, detail="No report available yet.")

    generated_at = report.get("generated_at", "")
    narratives = []
    for n in report.get("narratives", []):
        narratives.append({
            "name": n["name"],
            "confidence": n.get("confidence", "MEDIUM"),
            "direction": n.get("direction", "EMERGING"),
            "explanation": n.get("explanation", ""),
            "topics": n.get("topics", []),
            "signal_count": len(n.get("supporting_signals", [])),
            "idea_count": len(n.get("ideas", [])),
            "existing_projects": n.get("existing_projects", []),
            "supporting_signals": n.get("supporting_signals", []),
            "ideas": [{"id": _idea_id(i["name"]), "name": i["name"], "complexity": i.get("complexity", "WEEKS")} for i in n.get("ideas", [])],
        })

    return {
        "narratives": narratives,
        "meta": _build_meta(report),
    }


@agent_router.get("/discover", summary="Discover the best build idea", description="Returns the single best build idea right now based on narrative confidence, supporting evidence, and momentum. Includes a 'why_now' field explaining urgency.")
async def agent_discover():
    report = _load_report()
    if not report:
        raise HTTPException(status_code=503, detail="No report available yet.")

    generated_at = report.get("generated_at", "")
    best_idea = None
    best_score = -1
    best_narrative = None

    for narrative in report.get("narratives", []):
        conf_score = CONFIDENCE_ORDER.get(narrative.get("confidence", "MEDIUM"), 1)
        dir_score = DIRECTION_ORDER.get(narrative.get("direction", "EMERGING"), 1)
        evidence_score = len(narrative.get("supporting_signals", []))
        score = conf_score * 10 + dir_score * 5 + evidence_score

        for idea in narrative.get("ideas", []):
            if score > best_score:
                best_score = score
                best_idea = idea
                best_narrative = narrative

    if not best_idea:
        raise HTTPException(status_code=404, detail="No ideas available")

    result = _build_idea(best_idea, best_narrative, generated_at)
    conf = best_narrative.get("confidence", "MEDIUM")
    dirn = best_narrative.get("direction", "EMERGING")
    signals = len(best_narrative.get("supporting_signals", []))
    result["why_now"] = (
        f"The '{best_narrative['name']}' narrative has {conf} confidence and is {dirn}. "
        f"Backed by {signals} signals across multiple sources. "
        f"Building now captures first-mover advantage in this trend."
    )
    return result


@router.get("/digest", summary="Daily digest", description="Returns a markdown summary of top narratives for newsletters or AI agents.")
async def get_digest(format: Optional[str] = Query("markdown", description="Output format: markdown or text")):
    """Generate a plain-text/markdown digest of the top narratives."""
    report = _load_report()
    if not report:
        raise HTTPException(status_code=503, detail="No report available yet.")

    narratives = report.get("narratives", [])
    generated_at = report.get("generated_at", "")
    sig_summary = report.get("signal_summary", {})

    # Sort by confidence + direction score
    def _sort_key(n):
        return (
            CONFIDENCE_ORDER.get(n.get("confidence", "LOW"), 0) * 10
            + DIRECTION_ORDER.get(n.get("direction", "EMERGING"), 0) * 5
            + len(n.get("supporting_signals", []))
        )
    sorted_narratives = sorted(narratives, key=_sort_key, reverse=True)[:5]

    lines = []
    lines.append("# Solana Narrative Radar — Daily Digest")
    lines.append(f"*Generated: {generated_at}*")
    lines.append(f"*Signals analyzed: {sig_summary.get('total_collected', 0)} from {len([k for k in sig_summary if k.endswith('_signals') and sig_summary[k]])} sources*")
    lines.append("")

    for i, n in enumerate(sorted_narratives, 1):
        direction = n.get("direction", "EMERGING")
        confidence = n.get("confidence", "MEDIUM")
        name = n.get("name", "Unknown")
        explanation = n.get("explanation", "")
        market_opp = n.get("market_opportunity", "")
        signals = n.get("supporting_signals", [])
        status = n.get("status", "ACTIVE")

        # Risk level
        risk = _compute_risk(confidence, direction)

        lines.append(f"## {i}. [{direction}] {name} ({confidence} confidence)")
        if status == "FADED":
            lines.append("⚠️ *This narrative is fading*")
        lines.append("")
        lines.append(explanation)
        lines.append("")

        # Key signals
        if signals:
            lines.append("**Key signals:**")
            for s in signals[:5]:
                if isinstance(s, dict):
                    text = s.get("text", s.get("name", ""))
                    source = s.get("source", "")
                    url = s.get("url", "")
                    line = f"- [{source}] {text}"
                    if url:
                        line += f" ([link]({url}))"
                    lines.append(line)
                else:
                    lines.append(f"- {s}")
            lines.append("")

        # Build opportunity
        if market_opp:
            lines.append(f"**Build opportunity:** {market_opp}")
            lines.append("")

        lines.append(f"**Risk level:** {risk}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Footer
    lines.append("*Data sources: GitHub, Twitter/X, DeFiLlama, CoinGecko, Solana RPC, Reddit, Birdeye*")
    lines.append("*API: https://solana-narrative-radar-8vsib.ondigitalocean.app/api/agent/discover*")

    content = "\n".join(lines)
    return PlainTextResponse(content, media_type="text/markdown")


def _compute_risk(confidence: str, direction: str) -> str:
    """Compute risk level from confidence and direction."""
    c = CONFIDENCE_ORDER.get(confidence, 1)
    d = DIRECTION_ORDER.get(direction, 1)
    score = c + d
    if score >= 5:
        return "🟢 LOW RISK — Strong signals, established trend"
    elif score >= 3:
        return "🟡 MEDIUM RISK — Growing signals, monitor closely"
    else:
        return "🔴 HIGH RISK — Early signals, high upside potential"


router.include_router(agent_router)


# ── Telegram Bot Endpoints ──

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram bot webhook updates."""
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    from telegram_bot import handle_webhook_update
    await handle_webhook_update(update)
    return {"ok": True}


@router.post("/notify/telegram")
async def notify_telegram(request: Request):
    """Send a custom message to all Telegram subscribers (admin, protected by API key)."""
    admin_key = os.environ.get("TELEGRAM_ADMIN_KEY", os.environ.get("DIGEST_API_KEY", ""))
    if not admin_key:
        raise HTTPException(status_code=503, detail="Admin key not configured")

    auth = request.headers.get("Authorization", "").replace("Bearer ", "")
    body = {}
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    body_key = body.get("api_key", "")
    if auth != admin_key and body_key != admin_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Missing 'message' field")

    from telegram_bot import broadcast
    result = await broadcast(message)
    return result


# ── API Key & Usage Endpoints ──

@router.post("/keys/register")
async def register_api_key(request: Request):
    """Register for a free API key."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()

    if not name or not email:
        raise HTTPException(status_code=400, detail="Both 'name' and 'email' are required")
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    from rate_limiter import register_key
    result = await register_key(name, email)
    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.get("/keys/usage")
async def api_key_usage(key: str = Query(..., description="Your API key")):
    """Get usage statistics for an API key."""
    from rate_limiter import get_key_usage
    result = await get_key_usage(key)
    if not result:
        raise HTTPException(status_code=404, detail="API key not found")
    return result


@router.get("/usage/stats")
async def usage_stats():
    """Internal monitoring: usage dashboard stats."""
    from rate_limiter import get_usage_stats
    return await get_usage_stats()


# --- Email Digest Endpoints ---

import re

@router.post("/subscribe")
async def subscribe_endpoint(request: Request):
    """Subscribe to email digest."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    email = (body.get("email") or "").strip().lower()
    frequency = body.get("frequency", "weekly")

    if not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if frequency not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="Frequency must be 'daily' or 'weekly'")

    from digest import subscribe
    result = await subscribe(email, frequency)
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.get("/unsubscribe")
async def unsubscribe_endpoint(token: str = Query(...)):
    """Unsubscribe from email digest."""
    from digest import unsubscribe
    success = await unsubscribe(token)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{background:#0a0a0f;color:#e2e8f0;font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
    .card{{background:#12121a;border:1px solid #1e1e2e;border-radius:12px;padding:40px;text-align:center;max-width:400px}}
    a{{color:#9945ff;text-decoration:none}}</style></head><body><div class="card">
    <h2>{'✅ Unsubscribed' if success else '❌ Token Not Found'}</h2>
    <p>{'You have been unsubscribed from the Solana Narrative Radar digest.' if success else 'This unsubscribe link is invalid or already used.'}</p>
    <a href="{os.environ.get('BASE_URL', 'https://solana-narrative-radar-8vsib.ondigitalocean.app')}">← Back to Radar</a>
    </div></body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@router.post("/digest/trigger")
async def trigger_digest_endpoint(request: Request):
    """Trigger digest send (protected by API key)."""
    digest_key = os.environ.get("DIGEST_API_KEY", "")
    if not digest_key:
        raise HTTPException(status_code=503, detail="Digest not configured")

    auth = request.headers.get("Authorization", "").replace("Bearer ", "")
    body_key = ""
    try:
        b = await request.json()
        body_key = b.get("api_key", "")
    except Exception:
        pass

    if auth != digest_key and body_key != digest_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    from digest import trigger_digest
    try:
        b = await request.json()
        freq = b.get("frequency")
    except Exception:
        freq = None
    result = await trigger_digest(freq)
    return result
