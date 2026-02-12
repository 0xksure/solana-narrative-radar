"""Collect social signals from X/Twitter"""
import subprocess
import json
from datetime import datetime
from typing import List, Dict

# KOLs to monitor (per bounty spec)
SOLANA_KOLS = [
    "0xMert_",       # Mert (Helius)
    "aeyakovenko",   # Anatoly Yakovenko (Toly)
    "rajgokal",      # Raj (Solana co-founder)
    "armaboronnikov", # Akshay
    "VitalikButerin", # For cross-ecosystem context
    "shaboronnikov",  # Shaw (Eliza/ai16z)
]

async def collect_kol_tweets() -> List[Dict]:
    """Collect recent tweets from Solana KOLs using xbird"""
    signals = []
    
    try:
        # Use xbird to get home timeline (includes followed accounts)
        result = subprocess.run(
            ["xbird", "home", "--count", "50"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            # Parse tweets and extract Solana-related ones
            for line in result.stdout.strip().split("\n"):
                if any(kw in line.lower() for kw in [
                    "solana", "sol", "defi", "nft", "anchor", "helius",
                    "jupiter", "drift", "agent", "ai agent", "onchain"
                ]):
                    signals.append({
                        "source": "twitter",
                        "signal_type": "kol_tweet",
                        "content": line[:500],
                        "collected_at": datetime.utcnow().isoformat()
                    })
    except Exception as e:
        print(f"Social collection error: {e}")
    
    # Also search for trending Solana topics
    try:
        for query in ["solana narrative", "building on solana", "solana ecosystem"]:
            result = subprocess.run(
                ["xbird", "search", query, "--count", "20"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        signals.append({
                            "source": "twitter",
                            "signal_type": "trending_topic",
                            "query": query,
                            "content": line[:500],
                            "collected_at": datetime.utcnow().isoformat()
                        })
    except Exception as e:
        print(f"Twitter search error: {e}")
    
    return signals
