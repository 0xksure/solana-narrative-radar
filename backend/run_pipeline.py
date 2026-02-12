"""CLI runner for the narrative detection pipeline"""
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
    print("🚀 Solana Narrative Radar - Running Pipeline")
    print("=" * 50)
    report = await run_pipeline()
    print("\n" + "=" * 50)
    print(f"📊 Report Summary:")
    print(f"   Signals collected: {report['signal_summary']['total_collected']}")
    print(f"   Narratives found: {len(report['narratives'])}")
    for n in report['narratives']:
        print(f"   • {n['name']} [{n['confidence']}] - {len(n.get('ideas', []))} build ideas")
    print(f"\n💾 Report saved to backend/data/latest_report.json")

if __name__ == "__main__":
    asyncio.run(main())
