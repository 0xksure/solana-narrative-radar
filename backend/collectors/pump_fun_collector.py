"""Collect trending memecoin data from Pump.fun"""
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import List, Dict

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://frontend-api-v2.pump.fun"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

THEME_KEYWORDS: Dict[str, List[str]] = {
    "ai": ["ai", "gpt", "agent", "neural", "llm", "cognitive", "brain", "intelligence", "openai", "claude"],
    "animal": ["dog", "cat", "pepe", "frog", "bear", "bull", "ape", "monkey", "shib", "doge", "bonk", "wif"],
    "political": ["trump", "biden", "maga", "president", "election", "vote", "freedom", "patriot", "politics"],
    "celebrity": ["elon", "musk", "drake", "kanye", "taylor", "swift"],
    "food": ["pizza", "burger", "taco", "sushi", "coffee", "beer", "wine"],
    "crypto_meta": ["sol", "solana", "eth", "bitcoin", "btc", "defi", "nft", "web3"],
}


def _detect_theme(name: str, symbol: str, description: str = "") -> str:
    text = f"{name} {symbol} {description}".lower()
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return theme
    return "other"


def _infer_topics(name: str, symbol: str, theme: str) -> List[str]:
    topics = ["memecoin", "pump.fun"]
    if theme != "other":
        topics.append(theme)
    text = f"{name} {symbol}".lower()
    if any(kw in text for kw in ["ai", "gpt", "agent", "neural", "llm"]):
        topics.append("ai_agents")
    return list(set(topics))


async def _fetch_json(client: httpx.AsyncClient, url: str) -> list | dict | None:
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            logger.warning("Pump.fun %s returned %s", url, resp.status_code)
            return None
        return resp.json()
    except Exception as e:
        logger.warning("Pump.fun fetch error for %s: %s", url, e)
        return None


async def collect() -> List[Dict]:
    """Collect signals from Pump.fun — themes, new launches, graduation candidates."""
    signals: List[Dict] = []
    all_tokens: List[Dict] = []

    async with httpx.AsyncClient(timeout=20) as client:
        # Fetch multiple endpoints concurrently-ish
        recently_traded = await _fetch_json(
            client, f"{BASE_URL}/coins?sort=last_trade_timestamp&order=DESC&limit=50"
        )
        top_mcap = await _fetch_json(
            client, f"{BASE_URL}/coins?sort=market_cap&order=DESC&limit=50"
        )
        featured = await _fetch_json(client, f"{BASE_URL}/coins/featured")
        king = await _fetch_json(client, f"{BASE_URL}/coins/king-of-the-hill")

    # Deduplicate by mint address
    seen_mints = set()
    for source_tokens in [recently_traded, top_mcap, featured]:
        if not isinstance(source_tokens, list):
            continue
        for t in source_tokens:
            mint = t.get("mint")
            if mint and mint not in seen_mints:
                seen_mints.add(mint)
                all_tokens.append(t)

    # King of the hill as a standalone signal
    if isinstance(king, dict) and king.get("mint"):
        mint = king["mint"]
        if mint not in seen_mints:
            seen_mints.add(mint)
            all_tokens.append(king)
        name = king.get("name", "Unknown")
        symbol = king.get("symbol", "")
        mcap = king.get("market_cap") or king.get("usd_market_cap") or 0
        signals.append({
            "source": "defi",
            "signal_type": "pump_fun_king",
            "name": f"Pump.fun King of the Hill: {name} ({symbol})",
            "content": f"{name} ({symbol}) is the current King of the Hill on Pump.fun with market cap ${mcap:,.0f}",
            "topics": _infer_topics(name, symbol, _detect_theme(name, symbol)),
            "engagement": min(mcap / 1000, 100),
            "url": f"https://pump.fun/{mint}",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"platform": "pump.fun", "mint": mint, "market_cap": mcap},
        })

    if not all_tokens:
        logger.warning("Pump.fun: no tokens collected")
        return signals

    # Detect new launches (< 1 hour old)
    now = datetime.now(timezone.utc)
    new_launches = []
    for t in all_tokens:
        created = t.get("created_timestamp")
        if created:
            try:
                # Could be ms or seconds
                ts = created / 1000 if created > 1e12 else created
                created_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if now - created_dt < timedelta(hours=1):
                    new_launches.append(t)
            except Exception:
                pass

    if new_launches:
        names = ", ".join(t.get("symbol", "?") for t in new_launches[:10])
        signals.append({
            "source": "defi",
            "signal_type": "pump_fun_new_launches",
            "name": f"New Pump.fun launches: {len(new_launches)} tokens",
            "content": f"{len(new_launches)} new tokens launched on Pump.fun in the last hour: {names}",
            "topics": ["memecoin", "pump.fun", "new_launches"],
            "engagement": min(len(new_launches) * 5, 100),
            "collected_at": now.isoformat(),
            "metadata": {"platform": "pump.fun", "token_count": len(new_launches)},
        })

    # Theme clustering — group tokens by detected theme
    theme_buckets: Dict[str, List[Dict]] = defaultdict(list)
    for t in all_tokens:
        name = t.get("name", "")
        symbol = t.get("symbol", "")
        desc = t.get("description", "")
        theme = _detect_theme(name, symbol, desc)
        theme_buckets[theme].append(t)

    for theme, tokens in theme_buckets.items():
        if theme == "other" or len(tokens) < 2:
            continue

        names = ", ".join(t.get("symbol", "?") for t in tokens[:8])
        total_mcap = sum((t.get("market_cap") or t.get("usd_market_cap") or 0) for t in tokens)
        engagement = min(len(tokens) * 10 + total_mcap / 10000, 100)

        signals.append({
            "source": "defi",
            "signal_type": "pump_fun_theme",
            "name": f"{theme.replace('_', ' ').title()}-themed memecoins trending on Pump.fun",
            "content": (
                f"Multiple {theme}-themed tokens ({names}) gaining traction on Pump.fun. "
                f"{len(tokens)} tokens, combined market cap: ${total_mcap:,.0f}"
            ),
            "topics": _infer_topics("", "", theme),
            "engagement": engagement,
            "collected_at": now.isoformat(),
            "metadata": {
                "platform": "pump.fun",
                "token_count": len(tokens),
                "theme": theme,
                "top_tokens": [{"name": t.get("name"), "symbol": t.get("symbol"),
                                "market_cap": t.get("market_cap") or t.get("usd_market_cap") or 0}
                               for t in sorted(tokens, key=lambda x: x.get("market_cap") or x.get("usd_market_cap") or 0, reverse=True)[:5]],
            },
        })

    # Individual top tokens by market cap
    sorted_by_mcap = sorted(all_tokens, key=lambda x: x.get("market_cap") or x.get("usd_market_cap") or 0, reverse=True)
    for t in sorted_by_mcap[:10]:
        name = t.get("name", "Unknown")
        symbol = t.get("symbol", "")
        mint = t.get("mint", "")
        mcap = t.get("market_cap") or t.get("usd_market_cap") or 0
        if mcap < 5000:
            continue
        theme = _detect_theme(name, symbol, t.get("description", ""))
        signals.append({
            "source": "defi",
            "signal_type": "pump_fun_top_token",
            "name": f"Pump.fun Top Token: {name} ({symbol})",
            "content": f"{name} ({symbol}) on Pump.fun — market cap ${mcap:,.0f}",
            "topics": _infer_topics(name, symbol, theme),
            "engagement": min(mcap / 5000, 80),
            "url": f"https://pump.fun/{mint}" if mint else "",
            "collected_at": now.isoformat(),
            "metadata": {"platform": "pump.fun", "mint": mint, "market_cap": mcap, "theme": theme},
        })

    logger.info("Pump.fun: %d signals collected", len(signals))
    return signals
