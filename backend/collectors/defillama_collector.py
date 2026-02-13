"""Collect DeFi TVL and protocol data from DeFiLlama"""
import httpx
from datetime import datetime
from typing import List, Dict

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
        
        # Sort by TVL change
        for p in solana_protocols:
            tvl = p.get("tvl", 0) or 0
            change_1d = p.get("change_1d", 0) or 0
            change_7d = p.get("change_7d", 0) or 0
            
            if tvl > 1_000_000:  # Only track protocols with >$1M TVL
                slug = p.get("slug", p.get("name", "").lower().replace(" ", "-"))
                signals.append({
                    "source": "defillama",
                    "signal_type": "tvl_data",
                    "name": p.get("name", ""),
                    "category": p.get("category", ""),
                    "tvl": tvl,
                    "change_1d": change_1d,
                    "change_7d": change_7d,
                    "chains": p.get("chains", []),
                    "url": f"https://defillama.com/protocol/{slug}",
                    "collected_at": datetime.utcnow().isoformat()
                })
        
        # Also get category-level TVL
        resp2 = await client.get("https://api.llama.fi/v2/chains", timeout=30)
        if resp2.status_code == 200:
            chains = resp2.json()
            solana_chain = next((c for c in chains if c.get("name") == "Solana"), None)
            if solana_chain:
                signals.append({
                    "source": "defillama",
                    "signal_type": "chain_tvl",
                    "name": "Solana",
                    "tvl": solana_chain.get("tvl", 0),
                    "collected_at": datetime.utcnow().isoformat()
                })
    
    return sorted(signals, key=lambda x: abs(x.get("change_7d", 0)), reverse=True)
