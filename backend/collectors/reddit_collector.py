"""Collect signals from Reddit about Solana narratives via Pullpush API"""
import asyncio
import logging
import time
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

PULLPUSH_BASE = "https://api.pullpush.io/reddit/search/submission/"
REQUEST_DELAY = 1.0


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


def _post_to_signal(p: dict, subreddit: str) -> Dict:
    title = p.get("title", "")
    selftext = p.get("selftext", "")
    score = p.get("score", 0)
    num_comments = p.get("num_comments", 0)
    created_utc = p.get("created_utc", 0)
    permalink = p.get("permalink", "")
    author = p.get("author", "[deleted]")
    flair = p.get("link_flair_text", "")

    return {
        "name": title,
        "content": selftext[:500] if selftext else title,
        "source": "reddit",
        "signal_type": "community_discussion",
        "url": f"https://reddit.com{permalink}" if permalink else f"https://reddit.com/r/{subreddit}",
        "topics": _extract_topics(f"{title} {selftext}"),
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


async def _fetch_subreddit_pullpush(client: httpx.AsyncClient, subreddit: str, size: int = 50) -> List[dict]:
    """Fetch recent posts via Pullpush API (Pushshift replacement)."""
    try:
        resp = await client.get(PULLPUSH_BASE, params={
            "subreddit": subreddit,
            "size": size,
            "sort": "desc",
            "sort_type": "created_utc",
        })
        if resp.status_code == 200:
            return resp.json().get("data", [])
        else:
            logger.warning("Pullpush r/%s returned %d", subreddit, resp.status_code)
    except Exception as e:
        logger.warning("Pullpush r/%s error: %s", subreddit, e)
    return []


async def _fetch_subreddit_reddit(client: httpx.AsyncClient, subreddit: str, sort: str = "hot", limit: int = 50) -> List[dict]:
    """Fallback: try Reddit JSON API directly."""
    try:
        resp = await client.get(
            f"https://www.reddit.com/r/{subreddit}/{sort}.json",
            params={"limit": limit, "raw_json": 1},
            headers={"User-Agent": "SolanaNarrativeRadar/1.0"},
        )
        if resp.status_code == 200:
            return [c["data"] for c in resp.json().get("data", {}).get("children", []) if c.get("data")]
    except Exception:
        pass
    return []


async def collect() -> List[Dict]:
    """Collect Reddit signals about Solana narratives."""
    signals = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Collect from Solana-native subreddits (all posts relevant)
        for sub in SOLANA_SUBREDDITS:
            posts = await _fetch_subreddit_pullpush(client, sub, size=50)
            if not posts:
                posts = await _fetch_subreddit_reddit(client, sub)
            for p in posts:
                pid = p.get("id", "")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                signals.append(_post_to_signal(p, sub))
            await asyncio.sleep(REQUEST_DELAY)

        # Collect from filtered subreddits (only Solana-related posts)
        for sub in FILTERED_SUBREDDITS:
            # Try keyword search via Pullpush
            try:
                resp = await client.get(PULLPUSH_BASE, params={
                    "subreddit": sub,
                    "q": "solana OR sol OR $SOL",
                    "size": 50,
                    "sort": "desc",
                    "sort_type": "created_utc",
                })
                posts = resp.json().get("data", []) if resp.status_code == 200 else []
            except Exception:
                posts = []

            if not posts:
                posts = await _fetch_subreddit_reddit(client, sub)
                posts = [p for p in posts if _is_solana_related(f"{p.get('title', '')} {p.get('selftext', '')}")]

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


if __name__ == "__main__":
    import json as _json
    logging.basicConfig(level=logging.INFO)

    async def _main():
        results = await collect()
        print(f"\n=== Reddit Collector: {len(results)} signals ===\n")
        for s in results[:10]:
            print(f"[{s['metadata']['subreddit']}] (↑{s['metadata']['score']} 💬{s['metadata']['comments']}) {s['name'][:80]}")
        print(f"\n... and {max(0, len(results)-10)} more")
        if results:
            print("\nSample signal:")
            print(_json.dumps(results[0], indent=2, default=str))

    asyncio.run(_main())
