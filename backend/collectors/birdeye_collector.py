"""Collect trending token data from Birdeye public API"""
import logging

logger = logging.getLogger(__name__)

import httpx
from datetime import datetime, timezone
from typing import List, Dict


BIRDEYE_TRENDING_URL = (
    "https://public-api.birdeye.so/defi/token_trending"
    "?sort_by=volume24hChangePercent&sort_type=desc&offset=0&limit=20"
)


async def collect_birdeye_trending() -> List[Dict]:
    """Collect trending Solana tokens from Birdeye's public API.
    
    Returns signals for tokens with notable volume changes,
    which can indicate emerging narratives or momentum shifts.
    """
    signals: List[Dict] = []

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                BIRDEYE_TRENDING_URL,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("Birdeye API returned %s", resp.status_code)
                return signals

            data = resp.json()
            tokens = data.get("data", {}).get("tokens", data.get("data", []))

            if not isinstance(tokens, list):
                tokens = []

            for token in tokens[:20]:
                name = token.get("name") or token.get("symbol") or "Unknown"
                symbol = token.get("symbol") or ""
                address = token.get("address") or ""
                volume_24h = token.get("volume24h", 0) or 0
                volume_change = token.get("volume24hChangePercent", 0) or 0
                price_change = token.get("priceChange24h", 0) or 0
                liquidity = token.get("liquidity", 0) or 0

                # Only include tokens with meaningful activity
                if volume_24h < 1000:
                    continue

                signal_type = "volume_anomaly"
                if abs(volume_change) > 500:
                    signal_type = "volume_spike"
                elif abs(price_change) > 50:
                    signal_type = "price_surge"

                content = (
                    f"{name} ({symbol}): "
                    f"24h vol ${volume_24h:,.0f} "
                    f"({volume_change:+.1f}% change), "
                    f"price {price_change:+.1f}%, "
                    f"liq ${liquidity:,.0f}"
                )

                signals.append({
                    "source": "birdeye",
                    "signal_type": signal_type,
                    "name": f"Birdeye Trending: {name} ({symbol})",
                    "content": content,
                    "topics": _infer_topics(name, symbol),
                    "volume": volume_24h,
                    "price_change": price_change,
                    "volume_change": volume_change,
                    "url": f"https://birdeye.so/token/{address}?chain=solana" if address else "",
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                })

        except httpx.TimeoutException:
            logger.warning("Birdeye API timeout")
        except Exception as e:
            logger.warning("Birdeye collector error: %s", e)

    logger.info("Birdeye: %s trending token signals", len(signals))
    return signals


def _infer_topics(name: str, symbol: str) -> List[str]:
    """Infer topic tags from token name/symbol."""
    text = f"{name} {symbol}".lower()
    topics = ["trading"]

    keyword_map = {
        "memecoins": ["pepe", "doge", "bonk", "wif", "meme", "shib", "cat", "dog", "moon"],
        "defi": ["swap", "lend", "yield", "vault", "farm", "stake", "liquid"],
        "ai_agents": ["ai", "gpt", "agent", "neural", "llm", "cognitive"],
        "gaming": ["game", "play", "nft", "meta", "quest"],
        "infrastructure": ["bridge", "oracle", "rpc", "validator", "layer"],
    }

    for topic, keywords in keyword_map.items():
        if any(kw in text for kw in keywords):
            topics.append(topic)

    return topics
