"""CLI runner for the narrative detection pipeline"""
import logging

logger = logging.getLogger(__name__)

import asyncio
import json
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from engine.pipeline import run_pipeline

async def main():
    logger.info("Solana Narrative Radar - Running Pipeline")
    logger.info("=" * 50)
    report = await run_pipeline()
    logger.info("=" * 50)
    logger.info("Report Summary:")
    logger.info("Signals collected: %s", report['signal_summary']['total_collected'])
    logger.info("Narratives found: %s", len(report['narratives']))
    for n in report['narratives']:
        logger.info("%s [%s] - %s build ideas", n['name'], n['confidence'], len(n.get('ideas', [])))
    logger.info("\nReport saved to backend/data/latest_report.json")

if __name__ == "__main__":
    asyncio.run(main())
