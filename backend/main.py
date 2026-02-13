from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import router
from contextlib import asynccontextmanager
import os
import sentry_sdk

# Initialize Sentry if DSN is configured
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,
        environment=os.getenv("ENVIRONMENT", "production"),
    )
import asyncio
import json
import time
from datetime import datetime, timezone, timedelta

# Agent loop interval (2 hours)
AGENT_LOOP_INTERVAL = 2 * 60 * 60
STALE_THRESHOLD = 4 * 60 * 60  # 4 hours

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REPORT_PATH = os.path.join(DATA_DIR, "latest_report.json")
STATUS_PATH = os.path.join(DATA_DIR, "pipeline_status.json")

# Global lock to prevent concurrent pipeline runs
_pipeline_lock = asyncio.Lock()
_pipeline_running = False


def _load_status():
    try:
        with open(STATUS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_status(status: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATUS_PATH, "w") as f:
        json.dump(status, f, indent=2)


def _report_is_stale() -> bool:
    """Check if latest_report.json is missing or older than STALE_THRESHOLD."""
    if not os.path.exists(REPORT_PATH):
        return True
    try:
        age = time.time() - os.path.getmtime(REPORT_PATH)
        return age > STALE_THRESHOLD
    except Exception:
        return True


async def run_pipeline_task():
    """Run the pipeline with status tracking. Prevents concurrent runs."""
    global _pipeline_running
    if _pipeline_lock.locked():
        print("🤖 [Agent] Pipeline already running, skipping")
        return

    async with _pipeline_lock:
        _pipeline_running = True
        now = datetime.now(timezone.utc)
        next_run = (now + timedelta(seconds=AGENT_LOOP_INTERVAL)).isoformat()
        _save_status({
            **_load_status(),
            "status": "running",
            "next_run": next_run,
            "started_at": now.isoformat(),
        })

        start = time.time()
        try:
            from engine.pipeline import run_pipeline
            print(f"🤖 [Agent] Running pipeline at {now.isoformat()}...")
            result = await run_pipeline()
            duration = round(time.time() - start, 1)
            n_count = len(result.get("narratives", []))
            s_count = result.get("signal_summary", {}).get("total_collected", 0)
            print(f"🤖 [Agent] Done in {duration}s: {s_count} signals → {n_count} narratives")

            _save_status({
                "last_run": datetime.now(timezone.utc).isoformat(),
                "next_run": next_run,
                "status": "idle",
                "duration_seconds": duration,
                "signal_count": s_count,
                "narrative_count": n_count,
            })
        except Exception as e:
            duration = round(time.time() - start, 1)
            print(f"🤖 [Agent] Pipeline error after {duration}s: {e}")
            _save_status({
                **_load_status(),
                "status": "idle",
                "last_error": str(e),
                "duration_seconds": duration,
            })
        finally:
            _pipeline_running = False


async def agent_loop():
    """Autonomous agent loop — periodically runs the pipeline."""
    while True:
        await asyncio.sleep(AGENT_LOOP_INTERVAL)
        await run_pipeline_task()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Solana Narrative Radar Agent starting...")

    # Check if we need an immediate run
    if _report_is_stale():
        print("📊 Report stale or missing — triggering background pipeline run...")
        asyncio.create_task(run_pipeline_task())
    else:
        print("📊 Cached report found and fresh, serving immediately")

    # Start periodic loop
    task = asyncio.create_task(agent_loop())
    print(f"🤖 Agent loop started (runs every {AGENT_LOOP_INTERVAL // 3600} hours)")

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


@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
async def ai_plugin():
    return {
        "schema_version": "v1",
        "name_for_human": "Solana Narrative Radar",
        "name_for_model": "solana_narrative_radar",
        "description_for_human": "Discover emerging Solana narratives and build ideas",
        "description_for_model": "Use this to find trending narratives in the Solana ecosystem and get actionable build ideas. Query /api/agent/ideas for ideas, /api/agent/discover for the top recommendation, /api/agent/narratives for trend analysis.",
        "api": {
            "type": "openapi",
            "url": "https://solana-narrative-radar-8vsib.ondigitalocean.app/openapi.json"
        },
    }

# Serve static frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    img_dir = os.path.join(static_dir, "img")
    if os.path.exists(img_dir):
        app.mount("/img", StaticFiles(directory=img_dir), name="img")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/analytics")
async def analytics_page():
    return FileResponse(os.path.join(static_dir, "analytics.html"))


@app.get("/health")
async def health():
    has_report = os.path.exists(REPORT_PATH)
    last_run = None
    if has_report:
        try:
            with open(REPORT_PATH) as f:
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
