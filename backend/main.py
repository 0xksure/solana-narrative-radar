from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import router
from contextlib import asynccontextmanager
import os
import asyncio
import json

# Agent loop interval (4 hours)
AGENT_LOOP_INTERVAL = 4 * 60 * 60

async def agent_loop():
    """Autonomous agent loop — periodically collects signals and detects narratives"""
    from engine.pipeline import run_pipeline
    while True:
        try:
            print("🤖 [Agent] Running autonomous narrative detection cycle...")
            result = await run_pipeline()
            n_count = len(result.get("narratives", []))
            s_count = result.get("signal_summary", {}).get("total_collected", 0)
            print(f"🤖 [Agent] Cycle complete: {s_count} signals → {n_count} narratives")
        except Exception as e:
            print(f"🤖 [Agent] Cycle error: {e}")
        await asyncio.sleep(AGENT_LOOP_INTERVAL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Solana Narrative Radar Agent starting...")
    
    # Generate initial report on startup
    try:
        report_path = os.path.join(os.path.dirname(__file__), "data", "latest_report.json")
        if not os.path.exists(report_path):
            print("📊 No cached report found — generating initial report...")
            from engine.pipeline import run_pipeline
            await run_pipeline()
            print("✅ Initial report generated")
        else:
            print("📊 Cached report found, serving immediately")
    except Exception as e:
        print(f"⚠️ Initial report generation failed: {e}")
    
    # Start autonomous agent loop
    task = asyncio.create_task(agent_loop())
    print("🤖 Agent loop started (runs every 4 hours)")
    
    yield
    
    task.cancel()
    print("👋 Agent shutting down...")

app = FastAPI(
    title="Solana Narrative Radar",
    description="AI-powered narrative detection for the Solana ecosystem",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# Serve static frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/health")
async def health():
    report_path = os.path.join(os.path.dirname(__file__), "data", "latest_report.json")
    has_report = os.path.exists(report_path)
    last_run = None
    if has_report:
        try:
            with open(report_path) as f:
                data = json.load(f)
                last_run = data.get("generated_at")
        except Exception:
            pass
    return {
        "status": "ok",
        "service": "solana-narrative-radar",
        "agent": "autonomous",
        "loop_interval_hours": AGENT_LOOP_INTERVAL // 3600,
        "has_report": has_report,
        "last_run": last_run
    }
