from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse
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
)

# Rate limiting: track events per hashed IP
_rate_limit: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 100
RATE_LIMIT_WINDOW = 3600  # 1 hour


@router.get("/narratives")
async def get_narratives(period: Optional[str] = "current"):
    """Get detected narratives from the persistent store (ACTIVE + recently FADED)"""
    try:
        # Try persistent store first
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


router.include_router(agent_router)
