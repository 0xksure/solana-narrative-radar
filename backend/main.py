from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from contextlib import asynccontextmanager
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Solana Narrative Radar starting...")
    yield
    # Shutdown
    print("👋 Shutting down...")

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

@app.get("/health")
async def health():
    return {"status": "ok", "service": "solana-narrative-radar"}
