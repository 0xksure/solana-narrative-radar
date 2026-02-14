"""Collect trending coins from CoinGecko (no API key needed)"""
import logging

logger = logging.getLogger(__name__)

import httpx
from datetime import datetime, timezone
from typing import List, Dict


async def collect_coingecko_trending() -> List[Dict]:
    """Fetch trending coins from CoinGecko, filter for Solana ecosystem."""
    signals: List[Dict] = []

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/search/trending",
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("CoinGecko API returned %s", resp.status_code)
                return signals

            data = resp.json()
            coins = data.get("coins", [])

            for entry in coins:
                coin = entry.get("item", {})
                name = coin.get("name", "Unknown")
                symbol = coin.get("symbol", "")
                coin_id = coin.get("id", "")
                market_cap_rank = coin.get("market_cap_rank")
                price_btc = coin.get("price_btc", 0)
                score = coin.get("score", 0)
                slug = coin.get("slug", coin_id)
                platforms = coin.get("platforms", {})

                # Check if on Solana (platform key or name match)
                is_solana = False
                sol_address = ""
                if isinstance(platforms, dict):
                    for pkey, addr in platforms.items():
                        if "solana" in pkey.lower():
                            is_solana = True
                            sol_address = addr
                            break

                # Also check name/symbol for Solana-related tokens
                text_lower = f"{name} {symbol}".lower()
                solana_keywords = [
                    "solana", "sol", "jupiter", "jito", "raydium", "orca",
                    "marinade", "bonk", "wif", "pyth", "drift", "tensor",
                    "phantom", "backpack", "helium", "render",
                ]
                if any(kw in text_lower for kw in solana_keywords):
                    is_solana = True

                # Include all trending coins but mark Solana ones specially
                content = (
                    f"CoinGecko Trending #{score + 1}: {name} ({symbol})"
                    f"{f' — MCap rank #{market_cap_rank}' if market_cap_rank else ''}"
                    f"{' [Solana]' if is_solana else ''}"
                )

                signal = {
                    "source": "coingecko",
                    "signal_type": "trending_coin",
                    "name": f"CoinGecko Trending: {name} ({symbol})",
                    "content": content,
                    "url": f"https://www.coingecko.com/en/coins/{coin_id}",
                    "score": max(10 - score, 1) * 5,  # Higher rank = higher score
                    "topics": _infer_topics(name, symbol, is_solana),
                    "is_solana": is_solana,
                    "market_cap_rank": market_cap_rank,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }
                if sol_address:
                    signal["sol_address"] = sol_address

                signals.append(signal)

            # Also fetch Solana ecosystem category
            try:
                cat_resp = await client.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "category": "solana-ecosystem",
                        "order": "volume_desc",
                        "per_page": 15,
                        "page": 1,
                        "sparkline": False,
                        "price_change_percentage": "24h,7d",
                    },
                )
                if cat_resp.status_code == 200:
                    tokens = cat_resp.json()
                    for token in tokens:
                        change_24h = token.get("price_change_percentage_24h", 0) or 0
                        change_7d = token.get("price_change_percentage_7d_in_currency", 0) or 0
                        vol = token.get("total_volume", 0) or 0

                        if abs(change_24h) > 5 or vol > 10_000_000:
                            signals.append({
                                "source": "coingecko",
                                "signal_type": "sol_ecosystem_mover",
                                "name": f"Solana Ecosystem: {token.get('name', '')} ({token.get('symbol', '').upper()})",
                                "content": (
                                    f"{token.get('name', '')} ({token.get('symbol', '').upper()}): "
                                    f"24h {change_24h:+.1f}%, 7d {change_7d:+.1f}%, "
                                    f"Vol ${vol:,.0f}, MCap ${token.get('market_cap', 0):,.0f}"
                                ),
                                "url": f"https://www.coingecko.com/en/coins/{token.get('id', '')}",
                                "score": min(abs(change_24h) + abs(change_7d), 50),
                                "topics": ["trading", "defi"],
                                "is_solana": True,
                                "collected_at": datetime.now(timezone.utc).isoformat(),
                            })
            except Exception as e:
                logger.warning("CoinGecko category error: %s", e)

        except httpx.TimeoutException:
            logger.warning("CoinGecko API timeout")
        except Exception as e:
            logger.warning("CoinGecko collector error: %s", e)

    logger.info("CoinGecko: %s signals", len(signals))
    return signals


def _infer_topics(name: str, symbol: str, is_solana: bool) -> List[str]:
    text = f"{name} {symbol}".lower()
    topics = ["trading"]
    if is_solana:
        topics.append("solana_ecosystem")

    keyword_map = {
        "memecoins": ["pepe", "doge", "bonk", "wif", "meme", "shib", "cat", "dog"],
        "defi": ["swap", "lend", "yield", "vault", "farm", "stake", "liquid", "jupiter", "raydium", "orca"],
        "ai_agents": ["ai", "gpt", "agent", "neural", "llm"],
        "gaming": ["game", "play", "nft", "meta"],
        "infrastructure": ["bridge", "oracle", "rpc", "validator", "pyth", "helium", "render"],
    }
    for topic, keywords in keyword_map.items():
        if any(kw in text for kw in keywords):
            topics.append(topic)
    return topics
