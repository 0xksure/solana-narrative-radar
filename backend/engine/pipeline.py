"""Main pipeline: collect → score → cluster → generate ideas → persist"""
import json
import os
import uuid
from datetime import datetime
from typing import Dict

from collectors.github_collector import collect_new_solana_repos, collect_trending_solana_repos
from collectors.defillama_collector import collect_solana_tvl
from collectors.social_collector import collect_kol_tweets
from collectors.onchain_collector import collect_onchain_signals
from collectors.birdeye_collector import collect_birdeye_trending
from collectors.coingecko_collector import collect_coingecko_trending
from collectors.solana_ecosystem_collector import collect_solana_ecosystem
from engine.scorer import score_signals
from engine.narrative_engine import cluster_narratives, generate_ideas
from engine.store import save_run, get_signal_velocity, get_stats
from engine.narrative_tracker import update_narrative_states
from engine.narrative_store import (
    load_store, save_store, merge_narratives,
    get_active_narratives, get_recently_faded,
    get_active_narrative_hints, store_entry_to_api,
)


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
    
    print("  [4/7] Collecting on-chain signals...")
    onchain_signals = await collect_onchain_signals()
    
    print("  [5/9] Collecting Birdeye trending tokens...")
    birdeye_signals = await collect_birdeye_trending()
    
    print("  [6/9] Collecting CoinGecko trending...")
    coingecko_signals = await collect_coingecko_trending()
    
    print("  [7/9] Collecting Solana ecosystem & governance...")
    ecosystem_signals = await collect_solana_ecosystem()
    
    all_signals = github_new + github_trending + defi_signals + social_signals + onchain_signals + birdeye_signals + coingecko_signals + ecosystem_signals
    print(f"  → Collected {len(all_signals)} raw signals")
    
    # Phase 2: Score signals
    print("  [6/7] Scoring signals...")
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
    print("  [7/7] Detecting narratives...")
    
    # Load persistent store and pass hints to LLM
    narrative_store = load_store()
    prev_hints = get_active_narrative_hints(narrative_store)
    
    narrative_result = cluster_narratives(scored, previous_narrative_hints=prev_hints)
    
    # Phase 4: Generate ideas for each narrative
    narratives = narrative_result.get("narratives", [])
    if narratives:
        print(f"  → Found {len(narratives)} narratives, generating ideas...")
        narratives_with_ideas = generate_ideas(narratives)
    else:
        narratives_with_ideas = []
    
    # Phase 5: Merge into persistent narrative store
    print("  [+] Updating narrative store...")
    narrative_store = merge_narratives(narratives_with_ideas, narrative_store)
    save_store(narrative_store)
    
    # Build report from the store (ACTIVE + recently FADED)
    active = get_active_narratives(narrative_store)
    faded = get_recently_faded(narrative_store, hours=24)
    total_runs = narrative_store.get("total_pipeline_runs", 0)
    
    store_narratives = []
    for entry in active + faded:
        api_entry = store_entry_to_api(entry)
        api_entry["total_pipeline_runs"] = total_runs
        store_narratives.append(api_entry)
    
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
            "birdeye_signals": len(birdeye_signals),
            "coingecko_signals": len(coingecko_signals),
            "ecosystem_signals": len(ecosystem_signals),
            "high_score_signals": len([s for s in scored if s.get("score", 0) > 60])
        },
        "narratives": store_narratives,
        "generated_at": datetime.utcnow().isoformat(),
        "version": "0.2.0"
    }
    
    # Enrich narratives with velocity data from history
    for n in store_narratives:
        name_lower = n.get("name", "").lower()
        velocity = get_signal_velocity(name_lower)
        if velocity.get("data_points", 0) >= 2:
            n["velocity"] = velocity
    
    report["narratives"] = store_narratives
    
    # Save report
    with open(os.path.join(data_dir, "latest_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    
    # Also save historical
    hist_file = os.path.join(data_dir, f"report_{datetime.utcnow().strftime('%Y-%m-%d')}.json")
    with open(hist_file, "w") as f:
        json.dump(report, f, indent=2)
    
    # Persist to SQLite
    run_id = str(uuid.uuid4())
    try:
        save_run(run_id, scored, store_narratives, report.get("signal_summary", {}))
        db_stats = get_stats()
        print(f"  💾 Persisted to DB (total: {db_stats['total_signals_collected']} signals, {db_stats['total_runs']} runs)")
    except Exception as e:
        print(f"  ⚠️ DB persist error: {e}")
    
    active_count = len([n for n in store_narratives if n.get("status") == "ACTIVE"])
    faded_count = len([n for n in store_narratives if n.get("status") == "FADED"])
    print(f"✅ Pipeline complete! {active_count} active narratives, {faded_count} recently faded")
    return report
