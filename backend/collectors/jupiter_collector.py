"""Collect trading volume and trend data from Jupiter aggregator"""
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Dict

import httpx

logger = logging.getLogger(__name__)

TICKERS_URL = "https://stats.jup.ag/coingecko/tickers"
TOKEN_LIST_URL = "https://token.jup.ag/strict"
PRICE_URL = "https://price.jup.ag/v6/price"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "meme": ["pepe", "doge", "bonk", "wif", "meme", "shib", "cat", "dog", "moon", "popcat", "myro"],
    "defi": ["swap", "lend", "yield", "vault", "farm", "stake", "liquid", "jup", "raydium", "orca", "marinade"],
    "ai": ["ai", "gpt", "agent", "neural", "llm", "render", "nosana"],
    "gaming": ["game", "play", "nft", "meta", "quest", "star atlas", "aurory"],
    "infrastructure": ["bridge", "oracle", "rpc", "validator", "pyth", "wormhole", "jito"],
    "lsd": ["msol", "bsol", "jitosol", "lst", "liquid staking"],
}


def _categorize(base: str, target: str) -> str:
    text = f"{base} {target}".lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat
    return "other"


def _infer_topics(base: str, target: str, category: str) -> List[str]:
    topics = ["trading", "jupiter", "dex"]
    if category != "other":
        topics.append(category)
    return topics


async def collect() -> List[Dict]:
    """Collect signals from Jupiter — top pairs, volume trends, category analysis."""
    signals: List[Dict] = []
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=20) as client:
        # Fetch tickers
        tickers = []
        try:
            resp = await client.get(TICKERS_URL, headers=HEADERS)
            if resp.status_code == 200:
                tickers = resp.json() if isinstance(resp.json(), list) else resp.json().get("tickers", [])
            else:
                logger.warning("Jupiter tickers API returned %s", resp.status_code)
        except Exception as e:
            logger.warning("Jupiter tickers error: %s", e)

        # Fetch token list for context
        token_map: Dict[str, Dict] = {}
        try:
            resp = await client.get(TOKEN_LIST_URL, headers=HEADERS)
            if resp.status_code == 200:
                for t in resp.json():
                    addr = t.get("address", "")
                    if addr:
                        token_map[addr] = t
        except Exception as e:
            logger.debug("Jupiter token list error: %s", e)

    if not tickers:
        logger.warning("Jupiter: no tickers data")
        return signals

    # Sort by volume
    for t in tickers:
        try:
            t["_vol"] = float(t.get("target_volume", 0) or 0)
        except (ValueError, TypeError):
            t["_vol"] = 0

    tickers.sort(key=lambda x: x["_vol"], reverse=True)

    # Top pairs by volume
    for t in tickers[:15]:
        base = t.get("base_currency_name", t.get("ticker_id", "").split("_")[0] if "_" in t.get("ticker_id", "") else "Unknown")
        target = t.get("target_currency_name", "USDC")
        vol = t["_vol"]
        last_price = t.get("last_price", 0)
        bid = t.get("bid", 0)
        ask = t.get("ask", 0)
        pool_id = t.get("pool_id", "")
        ticker_id = t.get("ticker_id", "")

        if vol < 100:
            continue

        category = _categorize(base, target)

        signals.append({
            "source": "defi",
            "signal_type": "jupiter_top_pair",
            "name": f"Jupiter Top Pair: {base}/{target}",
            "content": (
                f"{base}/{target} on Jupiter — "
                f"volume: ${vol:,.0f}, last price: {last_price}"
            ),
            "topics": _infer_topics(base, target, category),
            "engagement": min(vol / 10000, 100),
            "url": f"https://jup.ag/swap/{ticker_id.replace('_', '-')}" if ticker_id else "https://jup.ag",
            "collected_at": now.isoformat(),
            "metadata": {
                "platform": "jupiter",
                "base": base,
                "target": target,
                "volume": vol,
                "last_price": last_price,
                "category": category,
            },
        })

    # Category volume analysis
    cat_volumes: Dict[str, float] = defaultdict(float)
    cat_pairs: Dict[str, List[str]] = defaultdict(list)
    for t in tickers:
        base = t.get("base_currency_name", "")
        target = t.get("target_currency_name", "")
        cat = _categorize(base, target)
        vol = t["_vol"]
        cat_volumes[cat] += vol
        if len(cat_pairs[cat]) < 5:
            cat_pairs[cat].append(f"{base}/{target}")

    for cat, total_vol in sorted(cat_volumes.items(), key=lambda x: x[1], reverse=True):
        if cat == "other" or total_vol < 1000:
            continue
        pairs_str = ", ".join(cat_pairs[cat])
        signals.append({
            "source": "defi",
            "signal_type": "jupiter_category_volume",
            "name": f"Jupiter {cat.upper()} volume: ${total_vol:,.0f}",
            "content": (
                f"{cat.title()} category on Jupiter seeing ${total_vol:,.0f} in swap volume. "
                f"Top pairs: {pairs_str}"
            ),
            "topics": ["trading", "jupiter", cat],
            "engagement": min(total_vol / 50000, 100),
            "collected_at": now.isoformat(),
            "metadata": {
                "platform": "jupiter",
                "category": cat,
                "total_volume": total_vol,
                "pair_count": len(cat_pairs[cat]),
                "top_pairs": cat_pairs[cat],
            },
        })

    # Overall Jupiter volume signal
    total_volume = sum(t["_vol"] for t in tickers)
    if total_volume > 0:
        top_3 = [t.get("base_currency_name", "?") for t in tickers[:3]]
        signals.append({
            "source": "defi",
            "signal_type": "jupiter_volume_overview",
            "name": f"Jupiter total swap volume: ${total_volume:,.0f}",
            "content": (
                f"Jupiter aggregator processing ${total_volume:,.0f} across {len(tickers)} pairs. "
                f"Top traded: {', '.join(top_3)}"
            ),
            "topics": ["trading", "jupiter", "dex", "solana"],
            "engagement": min(total_volume / 100000, 100),
            "collected_at": now.isoformat(),
            "metadata": {"platform": "jupiter", "total_volume": total_volume, "pair_count": len(tickers)},
        })

    logger.info("Jupiter: %d signals collected", len(signals))
    return signals
