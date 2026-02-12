"""Main pipeline: collect → score → cluster → generate ideas"""
import json
import os
from datetime import datetime
from typing import Dict

from collectors.github_collector import collect_new_solana_repos, collect_trending_solana_repos
from collectors.defillama_collector import collect_solana_tvl
from collectors.social_collector import collect_kol_tweets
from collectors.onchain_collector import collect_onchain_signals
from engine.scorer import score_signals
from engine.narrative_engine import cluster_narratives, generate_ideas


async def run_pipeline() -> Dict:
    """Run the full narrative detection pipeline"""
    print("📡 Starting Solana Narrative Radar pipeline...")
    
    # Phase 1: Collect signals from all sources
    print("  [1/5] Collecting GitHub signals...")
    github_new = await collect_new_solana_repos(days_back=14)
    github_trending = await collect_trending_solana_repos()
    
    print("  [2/5] Collecting DeFiLlama signals...")
    defi_signals = await collect_solana_tvl()
    
    print("  [3/6] Collecting social signals...")
    social_signals = await collect_kol_tweets()
    
    print("  [4/6] Collecting on-chain signals...")
    onchain_signals = await collect_onchain_signals()
    
    all_signals = github_new + github_trending + defi_signals + social_signals + onchain_signals
    print(f"  → Collected {len(all_signals)} raw signals")
    
    # Phase 2: Score signals
    print("  [5/6] Scoring signals...")
    scored = score_signals(all_signals)
    
    # Save raw signals
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    
    with open(os.path.join(data_dir, "signals.json"), "w") as f:
        json.dump({
            "signals": scored[:100],  # Keep top 100
            "total_collected": len(all_signals),
            "generated_at": datetime.utcnow().isoformat()
        }, f, indent=2)
    
    # Phase 3: Cluster into narratives
    print("  [6/6] Detecting narratives...")
    narrative_result = cluster_narratives(scored)
    
    # Phase 4: Generate ideas for each narrative
    narratives = narrative_result.get("narratives", [])
    if narratives:
        print(f"  → Found {len(narratives)} narratives, generating ideas...")
        narratives_with_ideas = generate_ideas(narratives)
    else:
        narratives_with_ideas = []
    
    # Build final report
    report = {
        "report_period": {
            "start": datetime.utcnow().strftime("%Y-%m-%d"),
            "end": datetime.utcnow().strftime("%Y-%m-%d"),
            "type": "fortnightly"
        },
        "signal_summary": {
            "total_collected": len(all_signals),
            "github_signals": len(github_new) + len(github_trending),
            "defi_signals": len(defi_signals),
            "social_signals": len(social_signals),
            "onchain_signals": len(onchain_signals),
            "high_score_signals": len([s for s in scored if s.get("score", 0) > 60])
        },
        "narratives": narratives_with_ideas,
        "generated_at": datetime.utcnow().isoformat(),
        "version": "0.1.0"
    }
    
    # Save report
    with open(os.path.join(data_dir, "latest_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    
    # Also save historical
    hist_file = os.path.join(data_dir, f"report_{datetime.utcnow().strftime('%Y-%m-%d')}.json")
    with open(hist_file, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"✅ Pipeline complete! Found {len(narratives_with_ideas)} narratives")
    return report
