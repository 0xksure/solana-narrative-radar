"""Collect DeFi TVL and protocol data from DeFiLlama"""
import httpx
from datetime import datetime, timedelta
from typing import List, Dict

async def _fetch_protocol_history(client: httpx.AsyncClient, slug: str) -> Dict:
    """Fetch historical TVL for a protocol (last 30 days)"""
    try:
        resp = await client.get(f"https://api.llama.fi/protocol/{slug}", timeout=30)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        
        # Extract chain-specific TVL history for Solana, or total
        tvl_data = data.get("chainTvls", {}).get("Solana", {}).get("tvl", [])
        if not tvl_data:
            tvl_data = data.get("tvl", [])
        
        if not tvl_data:
            return {}
        
        # Last 30 days
        cutoff = datetime.utcnow() - timedelta(days=30)
        cutoff_ts = int(cutoff.timestamp())
        
        recent = [p for p in tvl_data if p.get("date", 0) >= cutoff_ts]
        if not recent:
            return {}
        
        tvl_history = [{"date": p["date"], "tvl": p.get("totalLiquidityUSD", p.get("tvl", 0))} for p in recent]
        tvl_now = tvl_history[-1]["tvl"] if tvl_history else 0
        
        # Find TVL at various points
        now_ts = int(datetime.utcnow().timestamp())
        ts_7d = now_ts - 7 * 86400
        ts_30d = now_ts - 30 * 86400
        ts_1d = now_ts - 86400
        
        def _tvl_at(target_ts):
            closest = min(tvl_history, key=lambda p: abs(p["date"] - target_ts))
            return closest["tvl"]
        
        tvl_7d_ago = _tvl_at(ts_7d)
        tvl_30d_ago = _tvl_at(ts_30d)
        tvl_1d_ago = _tvl_at(ts_1d)
        
        def _pct(old, new):
            if old and old > 0:
                return round((new - old) / old * 100, 2)
            return 0
        
        return {
            "tvl_now": tvl_now,
            "tvl_7d_ago": tvl_7d_ago,
            "tvl_30d_ago": tvl_30d_ago,
            "change_7d_pct": _pct(tvl_7d_ago, tvl_now),
            "change_30d_pct": _pct(tvl_30d_ago, tvl_now),
            "change_1d_pct": _pct(tvl_1d_ago, tvl_now),
            "tvl_history": tvl_history,
            "description": data.get("description", ""),
            "logo": data.get("logo", ""),
        }
    except Exception as e:
        print(f"Failed to fetch history for {slug}: {e}")
        return {}


async def _fetch_chain_tvl_history(client: httpx.AsyncClient) -> Dict:
    """Fetch Solana total chain TVL history (last 30 days)"""
    try:
        resp = await client.get("https://api.llama.fi/v2/historicalChainTvl/Solana", timeout=30)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        
        cutoff = datetime.utcnow() - timedelta(days=30)
        cutoff_ts = int(cutoff.timestamp())
        recent = [p for p in data if p.get("date", 0) >= cutoff_ts]
        
        if not recent:
            return {}
        
        tvl_history = [{"date": p["date"], "tvl": p.get("tvl", 0)} for p in recent]
        tvl_now = tvl_history[-1]["tvl"] if tvl_history else 0
        
        now_ts = int(datetime.utcnow().timestamp())
        
        def _tvl_at(target_ts):
            closest = min(tvl_history, key=lambda p: abs(p["date"] - target_ts))
            return closest["tvl"]
        
        def _pct(old, new):
            if old and old > 0:
                return round((new - old) / old * 100, 2)
            return 0
        
        tvl_7d_ago = _tvl_at(now_ts - 7 * 86400)
        tvl_30d_ago = _tvl_at(now_ts - 30 * 86400)
        
        return {
            "tvl_history": tvl_history,
            "tvl_now": tvl_now,
            "change_7d_pct": _pct(tvl_7d_ago, tvl_now),
            "change_30d_pct": _pct(tvl_30d_ago, tvl_now),
        }
    except Exception as e:
        print(f"Failed to fetch chain TVL history: {e}")
        return {}


async def collect_solana_tvl() -> List[Dict]:
    """Get TVL data for Solana protocols"""
    signals = []
    
    async with httpx.AsyncClient() as client:
        # Get all protocols on Solana
        resp = await client.get("https://api.llama.fi/protocols", timeout=30)
        if resp.status_code != 200:
            return []
        
        protocols = resp.json()
        solana_protocols = [
            p for p in protocols 
            if "Solana" in (p.get("chains") or [])
        ]
        
        # Build base signals for protocols with >$1M TVL
        base_signals = []
        for p in solana_protocols:
            tvl = p.get("tvl", 0) or 0
            change_1d = p.get("change_1d", 0) or 0
            change_7d = p.get("change_7d", 0) or 0
            
            if tvl > 1_000_000:
                slug = p.get("slug", p.get("name", "").lower().replace(" ", "-"))
                base_signals.append({
                    "source": "defillama",
                    "signal_type": "tvl_data",
                    "name": p.get("name", ""),
                    "slug": slug,
                    "category": p.get("category", ""),
                    "tvl": tvl,
                    "change_1d": change_1d,
                    "change_7d": change_7d,
                    "chains": p.get("chains", []),
                    "url": f"https://defillama.com/protocol/{slug}",
                    "collected_at": datetime.utcnow().isoformat()
                })
        
        # Sort by absolute 7d change, take top 20 for historical enrichment
        sorted_by_change = sorted(base_signals, key=lambda x: abs(x.get("change_7d", 0)), reverse=True)
        top_20_slugs = {s["slug"] for s in sorted_by_change[:20]}
        
        # Fetch historical data for top 20
        for sig in base_signals:
            if sig["slug"] in top_20_slugs:
                history = await _fetch_protocol_history(client, sig["slug"])
                if history:
                    sig["tvl_now"] = history.get("tvl_now", sig["tvl"])
                    sig["tvl_7d_ago"] = history.get("tvl_7d_ago", 0)
                    sig["tvl_30d_ago"] = history.get("tvl_30d_ago", 0)
                    sig["change_7d_pct"] = history.get("change_7d_pct", 0)
                    sig["change_30d_pct"] = history.get("change_30d_pct", 0)
                    sig["change_1d_pct"] = history.get("change_1d_pct", 0)
                    sig["tvl_history"] = history.get("tvl_history", [])
                    sig["description"] = history.get("description", "")
                    sig["logo"] = history.get("logo", "")
            signals.append(sig)
        
        # Fetch chain-level TVL
        resp2 = await client.get("https://api.llama.fi/v2/chains", timeout=30)
        if resp2.status_code == 200:
            chains = resp2.json()
            solana_chain = next((c for c in chains if c.get("name") == "Solana"), None)
            if solana_chain:
                chain_signal = {
                    "source": "defillama",
                    "signal_type": "chain_tvl",
                    "name": "Solana",
                    "tvl": solana_chain.get("tvl", 0),
                    "collected_at": datetime.utcnow().isoformat()
                }
                # Enrich with historical chain TVL
                chain_history = await _fetch_chain_tvl_history(client)
                if chain_history:
                    chain_signal["tvl_history"] = chain_history.get("tvl_history", [])
                    chain_signal["change_7d_pct"] = chain_history.get("change_7d_pct", 0)
                    chain_signal["change_30d_pct"] = chain_history.get("change_30d_pct", 0)
                signals.append(chain_signal)
    
    return sorted(signals, key=lambda x: abs(x.get("change_7d", 0)), reverse=True)
