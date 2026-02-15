"""Collect signals from Reddit about Solana narratives"""
import asyncio
import logging
import re
from datetime import datetime
from typing import List, Dict

import httpx

logger = logging.getLogger(__name__)

# Subreddits where all posts are relevant
SOLANA_SUBREDDITS = ["solana", "solanadev", "SolanaMemeCoins"]

# Subreddits that need keyword filtering
FILTERED_SUBREDDITS = ["cryptocurrency", "defi"]

SOLANA_KEYWORDS = [
    "solana", "sol", "$sol", "phantom", "jupiter", "jup", "raydium",
    "orca", "marinade", "jito", "tensor", "helius", "drift", "bonk",
    "wif", "pump.fun", "pumpfun", "backpack", "magiceden", "metaplex",
    "anchor", "seahorse", "squads", "realms", "mango", "pyth",
]

TOPIC_MAP = {
    "defi": ["defi", "lending", "borrowing", "yield", "liquidity", "amm", "dex", "swap", "tvl"],
    "ai_agents": ["ai agent", "agent", "autonomous", "llm", "eliza", "ai16z"],
    "trading": ["trading", "trade", "perp", "futures", "leverage"],
    "infrastructure": ["rpc", "validator", "node", "infrastructure", "sdk"],
    "memecoins": ["memecoin", "meme", "bonk", "wif", "pump", "degen"],
    "staking": ["staking", "stake", "delegation", "msol", "jitosol"],
    "nft": ["nft", "collection", "mint", "tensor", "magiceden"],
    "gaming": ["gaming", "game", "play", "metaverse"],
    "rwa": ["rwa", "real world", "tokenized"],
    "payments": ["payment", "pay", "transfer"],
    "development": ["rust", "anchor", "program", "smart contract", "deploy", "sdk", "developer"],
}

USER_AGENT = "SolanaNarrativeRadar/1.0"
REQUEST_DELAY = 2.0  # seconds between requests


def _is_solana_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in SOLANA_KEYWORDS)


def _extract_topics(text: str) -> List[str]:
    text_lower = text.lower()
    topics = []
    for topic, keywords in TOPIC_MAP.items():
        if any(kw in text_lower for kw in keywords):
            topics.append(topic)
    return topics if topics else ["other"]


def _post_to_signal(post_data: dict, subreddit: str) -> Dict:
    p = post_data
    title = p.get("title", "")
    selftext = p.get("selftext", "")
    score = p.get("score", 0)
    num_comments = p.get("num_comments", 0)
    created_utc = p.get("created_utc", 0)
    permalink = p.get("permalink", "")
    author = p.get("author", "[deleted]")
    flair = p.get("link_flair_text", "")

    combined_text = f"{title} {selftext}"

    return {
        "name": title,
        "content": selftext[:500] if selftext else title,
        "source": "reddit",
        "signal_type": "community_discussion",
        "url": f"https://reddit.com{permalink}" if permalink else "",
        "topics": _extract_topics(combined_text),
        "engagement": score + num_comments,
        "timestamp": created_utc,
        "metadata": {
            "subreddit": subreddit,
            "score": score,
            "comments": num_comments,
            "author": author,
            "flair": flair,
        },
        "collected_at": datetime.utcnow().isoformat(),
    }


async def _fetch_subreddit(client: httpx.AsyncClient, subreddit: str, sort: str = "hot", limit: int = 50) -> List[dict]:
    """Fetch posts from a subreddit. Returns raw post data dicts."""
    try:
        resp = await client.get(
            f"https://old.reddit.com/r/{subreddit}/{sort}.json",
            params={"limit": limit, "raw_json": 1},
        )
        if resp.status_code == 200:
            return [child["data"] for child in resp.json().get("data", {}).get("children", []) if child.get("data")]
        else:
            logger.warning("Reddit r/%s/%s returned %d", subreddit, sort, resp.status_code)
    except Exception as e:
        logger.warning("Reddit r/%s/%s error: %s", subreddit, sort, e)
    return []


async def collect() -> List[Dict]:
    """Collect Reddit signals about Solana narratives."""
    signals = []
    seen_ids = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
        # Collect from Solana-native subreddits (all posts relevant)
        for sub in SOLANA_SUBREDDITS:
            for sort in ("hot", "new"):
                posts = await _fetch_subreddit(client, sub, sort, limit=50)
                for p in posts:
                    pid = p.get("id", "")
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    score = p.get("score", 0)
                    if score >= 2 or sort == "new":
                        signals.append(_post_to_signal(p, sub))
                await asyncio.sleep(REQUEST_DELAY)

        # Collect from filtered subreddits (only Solana-related posts)
        for sub in FILTERED_SUBREDDITS:
            for sort in ("hot", "new"):
                posts = await _fetch_subreddit(client, sub, sort, limit=50)
                for p in posts:
                    pid = p.get("id", "")
                    if pid in seen_ids:
                        continue
                    combined = f"{p.get('title', '')} {p.get('selftext', '')}"
                    if _is_solana_related(combined):
                        seen_ids.add(pid)
                        signals.append(_post_to_signal(p, sub))
                await asyncio.sleep(REQUEST_DELAY)

    # Sort by engagement
    signals.sort(key=lambda s: s.get("engagement", 0), reverse=True)

    logger.info("Reddit collector: %d signals from %d subreddits", len(signals), len(SOLANA_SUBREDDITS) + len(FILTERED_SUBREDDITS))
    return signals


# Standalone test
if __name__ == "__main__":
    import json as _json

    logging.basicConfig(level=logging.INFO)

    async def _main():
        results = await collect()
        print(f"\n=== Reddit Collector: {len(results)} signals ===\n")
        for s in results[:10]:
            print(f"[{s['metadata']['subreddit']}] (↑{s['metadata']['score']} 💬{s['metadata']['comments']}) {s['name'][:80]}")
        print(f"\n... and {max(0, len(results)-10)} more")
        # Dump full first signal for inspection
        if results:
            print("\nSample signal:")
            print(_json.dumps(results[0], indent=2, default=str))

    asyncio.run(_main())
