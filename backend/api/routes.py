from fastapi import APIRouter, HTTPException
from typing import Optional
import json
import os
import asyncio

router = APIRouter()

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "latest_report.json")
STATUS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "pipeline_status.json")


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
