"""Structured logging configuration for Solana Narrative Radar."""

import logging
import os
import sys


def setup_logging(app_name: str = "narrative-radar", level: str = None):
    """Configure structured logging for the application."""
    level = level or os.environ.get("LOG_LEVEL", "INFO")
    log_format = f"%(asctime)s | %(levelname)-8s | {app_name} | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
