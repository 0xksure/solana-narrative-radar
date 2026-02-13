#!/usr/bin/env python3
"""Pre-collect social signals using xbird CLI.

Run locally before deploying to populate data/social_cache.json.
Usage: python precollect_social.py
"""
import asyncio
import json
import re
import os
import sys
from datetime import datetime

SEARCH_QUERIES = [
    # Engagement-filtered general queries
    '"solana" min_faves:50',
    '"building on solana" min_faves:20',
    '"$SOL" min_faves:100',
    # Protocol-specific trending
    '"jupiter solana" OR "jup airdrop" OR "@JupiterExchange" min_faves:20',
    '"jito solana" OR "jito tips" min_faves:20',
    '"pump.fun" OR "pumpfun" min_faves:30',
    '"solana ai agent" OR "eliza solana" OR "ai16z" min_faves:20',
    '"solana depin" OR "helium solana" min_faves:20',
    '"solana rwa" OR "tokenized assets solana" min_faves:10',
    '"solana staking" OR "liquid staking solana" min_faves:20',
    # Emerging narrative detection
    '"solana" "just launched" min_faves:10',
    '"solana" "alpha" min_faves:30',
    '"solana" "narrative" min_faves:20',
    '"solana" "bullish" min_faves:50',
    # KOL-specific
    "from:0xMert_ solana",
    "from:aeyakovenko",
    "from:rajgokal",
]

SOLANA_KEYWORDS = [
    "solana", "sol", "defi", "nft", "anchor", "helius",
    "jupiter", "drift", "agent", "ai agent", "onchain",
    "jito", "marinade", "raydium", "orca", "phantom",
    "backpack", "tensor", "pump.fun", "bonk", "wif",
]

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def parse_xbird_output(output: str) -> list:
    """Parse xbird CLI output into structured tweets."""
    tweets = []
    current_tweet = {}
    
    for line in output.strip().split("\n"):
        line = line.strip()
        
        if line.startswith("─"):
            if current_tweet and current_tweet.get("text"):
                tweets.append(current_tweet)
                current_tweet = {}
            continue
        
        if not line:
            continue
        
        url_match = re.match(r'🔗\s*(https?://\S+)', line)
        if url_match:
            current_tweet["url"] = url_match.group(1)
            continue
        
        if line.startswith("📅") or line.startswith("🎬"):
            continue
        
        author_match = re.match(r'^@(\w+)\s*\(', line)
        if author_match:
            if current_tweet and current_tweet.get("text"):
                tweets.append(current_tweet)
            current_tweet = {"author": author_match.group(1), "text": ""}
            continue
        
        current_tweet["text"] = (current_tweet.get("text", "") + " " + line).strip()
    
    if current_tweet and current_tweet.get("text"):
        tweets.append(current_tweet)
    
    return tweets


def is_solana_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in SOLANA_KEYWORDS)


def extract_topics(text: str) -> list:
    text_lower = text.lower()
    topics = []
    topic_keywords = {
        "defi": ["defi", "lending", "borrowing", "yield", "liquidity", "amm", "dex", "swap", "tvl"],
        "ai_agents": ["ai agent", "agent", "autonomous", "llm", "gpt", "claude", "eliza"],
        "trading": ["trading", "trade", "perp", "futures", "leverage"],
        "infrastructure": ["rpc", "validator", "node", "infrastructure", "sdk"],
        "memecoins": ["memecoin", "meme", "bonk", "wif", "pump", "degen"],
        "staking": ["staking", "stake", "validator", "delegation", "msol", "jitosol"],
        "nft": ["nft", "collection", "mint", "tensor", "magiceden"],
        "gaming": ["gaming", "game", "play", "metaverse"],
        "rwa": ["rwa", "real world", "tokenized", "treasury"],
        "payments": ["payment", "pay", "transfer", "remittance"],
    }
    for topic, keywords in topic_keywords.items():
        if any(kw in text_lower for kw in keywords):
            topics.append(topic)
    return topics if topics else ["other"]


async def collect_home_timeline(count=50):
    """Collect from home timeline via direct Twitter API, filter Solana-related."""
    from collectors.twitter_api import get_home_timeline
    signals = []
    try:
        tweets = await get_home_timeline(count)
        for t in tweets:
            if is_solana_related(t.get("text", "")):
                signals.append({
                    "source": "twitter",
                    "signal_type": "kol_tweet",
                    "name": f"@{t.get('author', 'unknown')}: {t.get('text', '')[:80]}",
                    "content": t.get("text", "")[:500],
                    "author": t.get("author", ""),
                    "url": t.get("url", ""),
                    "topics": extract_topics(t.get("text", "")),
                    "collected_at": datetime.utcnow().isoformat(),
                })
    except Exception as e:
        print(f"⚠️ Home timeline error: {e}")
    return signals


async def collect_search(query, count=20):
    """Search for a query via direct Twitter API."""
    from collectors.twitter_api import search_tweets
    signals = []
    try:
        tweets = await search_tweets(query, count)
        for t in tweets:
            signals.append({
                "source": "twitter",
                "signal_type": "trending_topic",
                "name": f"Search '{query}': {t.get('text', '')[:60]}",
                "query": query,
                "content": t.get("text", "")[:500],
                "author": t.get("author", ""),
                "url": t.get("url", ""),
                "topics": extract_topics(t.get("text", "")),
                "collected_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        print(f"⚠️ Search '{query}' error: {e}")
    return signals


async def async_main():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    all_signals = []
    
    # Home timeline
    print("Collecting home timeline...")
    home = await collect_home_timeline(100)
    print(f"  → {len(home)} Solana-related tweets from home")
    all_signals.extend(home)
    
    # Search queries
    for q in SEARCH_QUERIES:
        print(f"Searching: {q}")
        results = await collect_search(q, 20)
        print(f"  → {len(results)} results")
        all_signals.extend(results)
    
    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for s in all_signals:
        url = s.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique.append(s)
    
    cache = {
        "collected_at": datetime.utcnow().isoformat(),
        "signal_count": len(unique),
        "signals": unique,
    }
    
    cache_path = os.path.join(DATA_DIR, "social_cache.json")
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)
    
    print(f"\n✅ Saved {len(unique)} signals to {cache_path}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
