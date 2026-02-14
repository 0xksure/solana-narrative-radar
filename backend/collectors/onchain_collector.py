"""Collect on-chain signals from Solana public APIs (no API key needed)"""
import logging

logger = logging.getLogger(__name__)

import httpx
import json
from datetime import datetime
from typing import List, Dict


# Notable Solana programs to track activity
TRACKED_PROGRAMS = {
    "JUP6LkMUJnQhGd1VKjTnSemxYlHmPKSidRjMaoc8hEq": "Jupiter v6",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY": "Phoenix",
    "opnb2LAfJYbRMAHHvqjCwQxanZn7ReEHp1k81EQMiaE": "OpenBook v2",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "Pump.fun",
    "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA": "Marinade Finance",
    "JitoSOL": "Jito",
}


async def collect_onchain_signals() -> List[Dict]:
    """Collect on-chain activity signals from public Solana APIs"""
    signals = []
    
    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Solana network stats from public RPC
        try:
            rpc_resp = await client.post(
                "https://api.mainnet-beta.solana.com",
                json={"jsonrpc": "2.0", "id": 1, "method": "getRecentPerformanceSamples", "params": [5]}
            )
            if rpc_resp.status_code == 200:
                samples = rpc_resp.json().get("result", [])
                if samples:
                    avg_tps = sum(s.get("numTransactions", 0) / max(s.get("samplePeriodSecs", 1), 1) for s in samples) / len(samples)
                    signals.append({
                        "source": "solana_rpc",
                        "signal_type": "network_activity",
                        "name": f"Solana Network TPS: {avg_tps:.0f}",
                        "content": f"Average TPS across last {len(samples)} samples: {avg_tps:.0f} transactions/sec",
                        "topics": ["infrastructure"],
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception as e:
            logger.warning("Solana RPC error: %s", e)
        
        # 2. Epoch info (staking activity indicator)
        try:
            epoch_resp = await client.post(
                "https://api.mainnet-beta.solana.com",
                json={"jsonrpc": "2.0", "id": 1, "method": "getEpochInfo"}
            )
            if epoch_resp.status_code == 200:
                epoch = epoch_resp.json().get("result", {})
                if epoch:
                    progress = (epoch.get("slotIndex", 0) / max(epoch.get("slotsInEpoch", 1), 1)) * 100
                    signals.append({
                        "source": "solana_rpc",
                        "signal_type": "epoch_info",
                        "name": f"Epoch {epoch.get('epoch', '?')} — {progress:.1f}% complete",
                        "content": json.dumps({"epoch": epoch.get("epoch"), "progress_pct": round(progress, 1)}),
                        "topics": ["staking", "infrastructure"],
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
        
        # 3. Token trending from Birdeye public endpoint
        try:
            resp = await client.get(
                "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hChangePercent&sort_type=desc&offset=0&limit=10",
                headers={"x-chain": "solana"}
            )
            if resp.status_code == 200:
                tokens = resp.json().get("data", {}).get("tokens", [])
                for token in tokens[:5]:
                    name = token.get("name", "Unknown")
                    symbol = token.get("symbol", "?")
                    change = token.get("v24hChangePercent", 0)
                    if change and abs(change) > 10:  # Significant movers only
                        signals.append({
                            "source": "birdeye",
                            "signal_type": "token_trending",
                            "name": f"🔥 {symbol} ({name}) {change:+.1f}% 24h",
                            "content": f"{name} ({symbol}) moved {change:+.1f}% in 24h. Liquidity: ${token.get('liquidity', 0):,.0f}",
                            "topics": ["trading", "memecoins"] if change > 50 else ["trading"],
                            "collected_at": datetime.utcnow().isoformat()
                        })
        except Exception:
            pass
        
        # 4. Solscan token stats
        try:
            resp = await client.get("https://api.solscan.io/token/list?sortBy=market_cap&direction=desc&limit=10&offset=0")
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for token in data[:5]:
                    if token.get("priceChange24h") and abs(token["priceChange24h"]) > 5:
                        signals.append({
                            "source": "solscan",
                            "signal_type": "top_token_movement",
                            "name": f"{token.get('tokenSymbol', '?')} market cap movement: {token.get('priceChange24h', 0):+.1f}%",
                            "content": json.dumps({
                                "symbol": token.get("tokenSymbol"),
                                "name": token.get("tokenName"),
                                "market_cap": token.get("marketCap"),
                                "price_change_24h": token.get("priceChange24h")
                            }),
                            "topics": ["trading"],
                            "collected_at": datetime.utcnow().isoformat()
                        })
        except Exception:
            pass
        
        # 5. Jupiter trending tokens (public, no API key)
        try:
            resp = await client.get("https://api.jup.ag/tokens/v1/trending")
            if resp.status_code == 200:
                tokens = resp.json() if isinstance(resp.json(), list) else []
                for token in tokens[:5]:
                    name = token.get("name", "Unknown")
                    symbol = token.get("symbol", "?")
                    vol = token.get("daily_volume", 0)
                    if vol and vol > 1_000_000:
                        signals.append({
                            "source": "jupiter",
                            "signal_type": "trending_token",
                            "name": f"Jupiter top volume: {symbol} (${vol:,.0f})",
                            "content": f"{name} ({symbol}) with ${vol:,.0f} daily volume on Jupiter",
                            "url": f"https://jup.ag/swap/SOL-{token.get('address', '')}",
                            "topics": ["trading", "defi"],
                            "collected_at": datetime.utcnow().isoformat()
                        })
        except Exception as e:
            logger.warning("Jupiter API error: %s", e)

        # 6. Recent program activity via getSignaturesForAddress for key programs
        for program_id, program_name in list(TRACKED_PROGRAMS.items())[:3]:
            try:
                sig_resp = await client.post(
                    "https://api.mainnet-beta.solana.com",
                    json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                          "params": [program_id, {"limit": 10}]}
                )
                if sig_resp.status_code == 200:
                    sigs = sig_resp.json().get("result", [])
                    if sigs:
                        signals.append({
                            "source": "solana_rpc",
                            "signal_type": "program_activity",
                            "name": f"{program_name}: {len(sigs)} recent txs",
                            "content": f"{program_name} ({program_id[:8]}...) had {len(sigs)} transactions in recent slots",
                            "topics": ["defi", "infrastructure"],
                            "collected_at": datetime.utcnow().isoformat()
                        })
            except Exception:
                pass

        # 8. Supply info (total SOL supply/staked as macro signal)
        try:
            supply_resp = await client.post(
                "https://api.mainnet-beta.solana.com",
                json={"jsonrpc": "2.0", "id": 1, "method": "getSupply"}
            )
            if supply_resp.status_code == 200:
                supply = supply_resp.json().get("result", {}).get("value", {})
                if supply:
                    total = supply.get("total", 0) / 1e9
                    circulating = supply.get("circulating", 0) / 1e9
                    signals.append({
                        "source": "solana_rpc",
                        "signal_type": "supply_stats",
                        "name": f"SOL Supply: {circulating:,.0f}M circulating / {total:,.0f}M total",
                        "content": json.dumps({"total_sol": round(total, 0), "circulating_sol": round(circulating, 0)}),
                        "topics": ["infrastructure", "staking"],
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
    
    logger.info("On-chain: %s signals", len(signals))
    return signals
