from fastapi import APIRouter, HTTPException
from typing import Optional
import json
import os

router = APIRouter()

@router.get("/narratives")
async def get_narratives(period: Optional[str] = "current"):
    """Get detected narratives for the current or historical period"""
    try:
        # Load latest narrative report
        report_path = os.path.join(os.path.dirname(__file__), "..", "data", "latest_report.json")
        if os.path.exists(report_path):
            with open(report_path) as f:
                return json.load(f)
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
    """Trigger a new narrative detection run"""
    from engine.pipeline import run_pipeline
    result = await run_pipeline()
    return result
