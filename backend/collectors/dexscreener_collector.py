"""Collect trending tokens and new pairs from DexScreener API (free, no auth)."""
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

import httpx

logger = logging.getLogger(__name__)

BOOSTED_URL = "https://api.dexscreener.com/token-boosts/top/v1"
TOKEN_PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
PAIRS_URL = "https://api.dexscreener.com/latest/dex/pairs/solana"
TOKENS_URL = "https://api.dexscreener.com/latest/dex/tokens"

CATEGORY_KEYWORDS = {
    "ai": ["ai", "gpt", "agent", "neural", "llm", "cognitive", "brain", "sentient"],
    "memecoins": ["pepe", "doge", "bonk", "wif", "meme", "shib", "cat", "dog", "moon", "frog", "chad", "wojak"],
    "defi": ["swap", "lend", "yield", "vault", "farm", "stake", "liquid", "fi", "dex"],
    "gaming": ["game", "play", "nft", "meta", "quest", "arena", "world"],
    "rwa": ["rwa", "real", "asset", "treasury", "bond"],
    "social": ["social", "friend", "chat", "community"],
    "infra": ["bridge", "oracle", "rpc", "validator", "layer", "chain", "sol"],
}


def _categorize(name: str, symbol: str) -> str:
    text = f"{name} {symbol}".lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat
    return "other"


def _infer_topics(name: str, symbol: str) -> List[str]:
    topics = ["defi", "trading"]
    cat = _categorize(name, symbol)
    if cat != "other":
        topics.append(cat)
    return topics


async def _fetch_json(client: httpx.AsyncClient, url: str) -> any:
    try:
        resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code == 200:
            return resp.json()
        logger.warning("DexScreener %s returned %s", url, resp.status_code)
    except httpx.TimeoutException:
        logger.warning("DexScreener timeout: %s", url)
    except Exception as e:
        logger.warning("DexScreener error for %s: %s", url, e)
    return None


async def _get_solana_boosted_tokens(client: httpx.AsyncClient) -> List[Dict]:
    """Get top boosted tokens, filter to Solana."""
    data = await _fetch_json(client, BOOSTED_URL)
    if not data or not isinstance(data, list):
        return []
    return [t for t in data if t.get("chainId") == "solana"]


async def _get_pair_details(client: httpx.AsyncClient, addresses: List[str]) -> List[Dict]:
    """Fetch detailed pair data for token addresses."""
    if not addresses:
        return []
    # Batch up to 30 addresses
    addr_str = ",".join(addresses[:30])
    data = await _fetch_json(client, f"{TOKENS_URL}/{addr_str}")
    if not data:
        return []
    pairs = data.get("pairs") or []
    # Filter Solana and deduplicate by base token (keep highest volume pair)
    solana_pairs = [p for p in pairs if p.get("chainId") == "solana"]
    best_by_token: Dict[str, Dict] = {}
    for p in solana_pairs:
        base = p.get("baseToken", {}).get("address", "")
        vol = p.get("volume", {}).get("h24", 0) or 0
        if base not in best_by_token or vol > (best_by_token[base].get("volume", {}).get("h24", 0) or 0):
            best_by_token[base] = p
    return list(best_by_token.values())


def _pair_to_signal(pair: Dict, rank: int, total: int) -> Dict:
    """Convert a DexScreener pair to a signal dict."""
    base = pair.get("baseToken", {})
    name = base.get("name", "Unknown")
    symbol = base.get("symbol", "")
    address = pair.get("pairAddress", "")
    price_change = pair.get("priceChange", {})
    volume_24h = pair.get("volume", {}).get("h24", 0) or 0
    liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
    market_cap = pair.get("marketCap") or pair.get("fdv") or 0
    txns = pair.get("txns", {}).get("h24", {})
    buys = txns.get("buys", 0) or 0
    sells = txns.get("sells", 0) or 0
    pair_created = pair.get("pairCreatedAt")

    pct_24h = price_change.get("h24", 0) or 0
    pct_1h = price_change.get("h1", 0) or 0
    pct_5m = price_change.get("m5", 0) or 0
    pct_6h = price_change.get("h6", 0) or 0

    # Engagement score: inverse rank normalized to 0-100
    engagement = max(0, 100 - int(rank * 100 / max(total, 1)))

    content_parts = [f"24h vol: ${volume_24h:,.0f}"]
    if pct_24h:
        content_parts.append(f"price 24h: {pct_24h:+.1f}%")
    if pct_1h:
        content_parts.append(f"1h: {pct_1h:+.1f}%")
    if liquidity:
        content_parts.append(f"liq: ${liquidity:,.0f}")
    if buys + sells > 0:
        content_parts.append(f"txns: {buys+sells}")

    return {
        "source": "defi",
        "signal_type": "dexscreener_trending",
        "name": f"{name} ({symbol}) trending on DexScreener",
        "content": ", ".join(content_parts),
        "topics": _infer_topics(name, symbol),
        "engagement": engagement,
        "volume": volume_24h,
        "price_change": pct_24h,
        "url": f"https://dexscreener.com/solana/{address}" if address else "",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "volume_24h": volume_24h,
            "price_change_5m": pct_5m,
            "price_change_1h": pct_1h,
            "price_change_6h": pct_6h,
            "price_change_24h": pct_24h,
            "liquidity": liquidity,
            "market_cap": market_cap,
            "buys_24h": buys,
            "sells_24h": sells,
            "pair_created_at": pair_created,
            "token_address": base.get("address", ""),
            "category": _categorize(name, symbol),
        },
    }


def _generate_narrative_signals(individual_signals: List[Dict]) -> List[Dict]:
    """Group individual token signals into narrative-level signals."""
    narrative_signals = []

    # Group by category
    by_category: Dict[str, List[Dict]] = defaultdict(list)
    for s in individual_signals:
        cat = s.get("metadata", {}).get("category", "other")
        by_category[cat].append(s)

    category_labels = {
        "ai": "AI tokens",
        "memecoins": "Memecoins",
        "defi": "DeFi protocols",
        "gaming": "Gaming tokens",
        "rwa": "RWA tokens",
        "social": "SocialFi tokens",
        "infra": "Infrastructure tokens",
    }

    for cat, signals in by_category.items():
        if cat == "other" or len(signals) < 2:
            continue
        label = category_labels.get(cat, f"{cat} tokens")
        total_vol = sum(s.get("volume", 0) for s in signals)
        avg_change = sum(s.get("price_change", 0) for s in signals) / len(signals)
        names = [s["name"].split(" (")[0] for s in signals[:5]]

        direction = "gaining momentum" if avg_change > 0 else "seeing activity"
        narrative_signals.append({
            "source": "defi",
            "signal_type": "narrative_cluster",
            "name": f"{label} {direction} on DexScreener ({len(signals)} tokens)",
            "content": (
                f"{len(signals)} {label.lower()} trending. "
                f"Combined 24h vol: ${total_vol:,.0f}, avg price change: {avg_change:+.1f}%. "
                f"Includes: {', '.join(names)}"
            ),
            "topics": ["defi", "trading", cat],
            "engagement": min(100, len(signals) * 20 + int(total_vol / 100_000)),
            "volume": total_vol,
            "price_change": avg_change,
            "url": "https://dexscreener.com/?rankBy=trendingScoreH6&order=desc&chainIds=solana",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "cluster_size": len(signals),
                "category": cat,
                "total_volume": total_vol,
                "avg_price_change": avg_change,
                "token_names": names,
            },
        })

    # Detect new launches (pairs created in last 6 hours)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    six_hours_ms = 6 * 3600 * 1000
    new_launches = [
        s for s in individual_signals
        if s.get("metadata", {}).get("pair_created_at")
        and (now_ms - s["metadata"]["pair_created_at"]) < six_hours_ms
    ]
    if len(new_launches) >= 2:
        names = [s["name"].split(" (")[0] for s in new_launches[:5]]
        total_vol = sum(s.get("volume", 0) for s in new_launches)
        narrative_signals.append({
            "source": "defi",
            "signal_type": "new_launch_wave",
            "name": f"New token launch wave on Solana ({len(new_launches)} tokens in 6h)",
            "content": (
                f"{len(new_launches)} new tokens launched and trending. "
                f"Combined vol: ${total_vol:,.0f}. "
                f"Includes: {', '.join(names)}"
            ),
            "topics": ["defi", "trading", "new_launches"],
            "engagement": min(100, len(new_launches) * 25),
            "volume": total_vol,
            "url": "https://dexscreener.com/new-pairs/solana",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "new_launch_count": len(new_launches),
                "total_volume": total_vol,
                "token_names": names,
            },
        })

    # Volume spike detection
    high_vol = [s for s in individual_signals if s.get("volume", 0) > 1_000_000]
    if len(high_vol) >= 3:
        total_vol = sum(s.get("volume", 0) for s in high_vol)
        names = [s["name"].split(" (")[0] for s in sorted(high_vol, key=lambda x: x.get("volume", 0), reverse=True)[:5]]
        narrative_signals.append({
            "source": "defi",
            "signal_type": "volume_concentration",
            "name": f"High volume concentration on DexScreener ({len(high_vol)} tokens >$1M vol)",
            "content": (
                f"{len(high_vol)} tokens with >$1M 24h volume trending. "
                f"Total vol: ${total_vol:,.0f}. Top: {', '.join(names)}"
            ),
            "topics": ["defi", "trading", "volume"],
            "engagement": min(100, 50 + len(high_vol) * 10),
            "volume": total_vol,
            "url": "https://dexscreener.com/?rankBy=volume&order=desc&chainIds=solana",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "high_vol_count": len(high_vol),
                "total_volume": total_vol,
                "token_names": names,
            },
        })

    return narrative_signals


async def collect_dexscreener() -> List[Dict]:
    """Collect trending DexScreener signals for Solana.

    Returns 10-30 signals: individual trending tokens + narrative groupings.
    """
    signals: List[Dict] = []

    async with httpx.AsyncClient(timeout=20) as client:
        # Get boosted/trending tokens on Solana
        boosted = await _get_solana_boosted_tokens(client)
        logger.info("DexScreener: %d boosted Solana tokens", len(boosted))

        if not boosted:
            return signals

        # Extract token addresses for detail lookup
        addresses = list({t.get("tokenAddress") for t in boosted if t.get("tokenAddress")})

        # Fetch pair details
        pair_details = await _get_pair_details(client, addresses)
        logger.info("DexScreener: %d pair details fetched", len(pair_details))

        # Convert to signals
        individual = []
        for i, pair in enumerate(pair_details):
            vol = pair.get("volume", {}).get("h24", 0) or 0
            if vol < 500:  # Skip dust
                continue
            sig = _pair_to_signal(pair, i, len(pair_details))
            individual.append(sig)

        # Sort by volume, keep top 20
        individual.sort(key=lambda x: x.get("volume", 0), reverse=True)
        individual = individual[:20]

        # Generate narrative grouping signals
        narratives = _generate_narrative_signals(individual)

        # Combine: narratives first, then top individual signals
        signals = narratives + individual

        # Cap at 30
        signals = signals[:30]

    logger.info("DexScreener: %d total signals (%d narrative clusters)",
                len(signals), len([s for s in signals if s.get("signal_type") == "narrative_cluster"]))
    return signals


# Public API
async def collect() -> List[Dict]:
    """Public collect interface."""
    return await collect_dexscreener()
