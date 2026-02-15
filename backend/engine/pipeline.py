"""Main pipeline: collect → score → cluster → generate ideas → persist"""
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

from collectors.github_collector import collect_new_solana_repos, collect_trending_solana_repos
from collectors.defillama_collector import collect_solana_tvl
from collectors.social_collector import collect_kol_tweets
from collectors.onchain_collector import collect_onchain_signals
from collectors.birdeye_collector import collect_birdeye_trending
from collectors.coingecko_collector import collect_coingecko_trending
from collectors.solana_ecosystem_collector import collect_solana_ecosystem
from collectors.dexscreener_collector import collect_dexscreener
from collectors.reddit_collector import collect as collect_reddit
from collectors.governance_collector import collect as collect_governance
from collectors.news_collector import collect as collect_news
from collectors.pump_fun_collector import collect as collect_pump_fun
from collectors.jupiter_collector import collect as collect_jupiter
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
    logger.info("Starting narrative radar pipeline")
    
    # Phase 1: Collect signals from all sources
    logger.info("[1/8] Collecting GitHub signals")
    github_new = await collect_new_solana_repos(days_back=14)
    github_trending = await collect_trending_solana_repos()
    
    logger.info("[2/8] Collecting DeFiLlama signals")
    defi_signals = await collect_solana_tvl()
    
    logger.info("[3/8] Collecting social signals")
    social_signals = await collect_kol_tweets()
    
    logger.info("[4/8] Collecting on-chain signals")
    onchain_signals = await collect_onchain_signals()
    
    logger.info("[5/9] Collecting Birdeye trending")
    birdeye_signals = await collect_birdeye_trending()
    
    logger.info("[6/9] Collecting CoinGecko trending")
    coingecko_signals = await collect_coingecko_trending()
    
    logger.info("[7/9] Collecting Solana ecosystem")
    ecosystem_signals = await collect_solana_ecosystem()
    
    logger.info("[8/9] Collecting Reddit signals")
    reddit_signals = await collect_reddit()
    
    logger.info("[9/11] Collecting DexScreener trending")
    dexscreener_signals = await collect_dexscreener()
    
    logger.info("[10/11] Collecting Pump.fun signals")
    pump_fun_signals = await collect_pump_fun()
    
    logger.info("[11/11] Collecting Jupiter signals")
    jupiter_signals = await collect_jupiter()
    
    all_signals = github_new + github_trending + defi_signals + social_signals + onchain_signals + birdeye_signals + coingecko_signals + ecosystem_signals + reddit_signals + dexscreener_signals + pump_fun_signals + jupiter_signals
    logger.info("Collected %d raw signals", len(all_signals))
    
    # Phase 2: Score signals
    logger.info("Scoring signals")
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
    logger.info("Detecting narratives")
    
    # Load persistent store and pass hints to LLM
    narrative_store = load_store()
    prev_hints = get_active_narrative_hints(narrative_store)
    
    narrative_result = cluster_narratives(scored, previous_narrative_hints=prev_hints)
    
    # Phase 4: Generate ideas for each narrative
    narratives = narrative_result.get("narratives", [])
    if narratives:
        logger.info("Found %d narratives, generating ideas", len(narratives))
        narratives_with_ideas = generate_ideas(narratives)
    else:
        narratives_with_ideas = []
    
    # Phase 5: Merge into persistent narrative store
    logger.info("Updating narrative store")
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
            "reddit_signals": len(reddit_signals),
            "dexscreener_signals": len(dexscreener_signals),
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
        logger.info("Persisted to DB (total: %d signals, %d runs)", db_stats['total_signals_collected'], db_stats['total_runs'])
    except Exception as e:
        logger.error("DB persist error: %s", e)
    
    active_count = len([n for n in store_narratives if n.get("status") == "ACTIVE"])
    faded_count = len([n for n in store_narratives if n.get("status") == "FADED"])
    logger.info("Pipeline complete: %d active narratives, %d recently faded", active_count, faded_count)
    return report
