"""Collect signals from Solana ecosystem sources"""
import logging

logger = logging.getLogger(__name__)

import httpx
from datetime import datetime, timezone
from typing import List, Dict


async def collect_solana_ecosystem() -> List[Dict]:
    """Scrape Solana ecosystem data from public sources."""
    signals: List[Dict] = []

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # 1. Solana ecosystem JSON feed
        try:
            resp = await client.get(
                "https://raw.githubusercontent.com/solana-labs/ecosystem/main/src/data/ecosystem.json",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                projects = resp.json()
                if isinstance(projects, list):
                    # Sort by recency if possible, take newest
                    for p in projects[:30]:
                        name = p.get("name", "")
                        desc = p.get("description", "")
                        category = p.get("category", "")
                        url = p.get("url", p.get("website", ""))

                        if not name:
                            continue

                        signals.append({
                            "source": "solana_ecosystem",
                            "signal_type": "ecosystem_project",
                            "name": f"Solana Ecosystem: {name}",
                            "content": f"{name} — {desc[:200]}" if desc else name,
                            "url": url,
                            "score": 5,
                            "topics": _categorize(category, name, desc),
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                        })
        except Exception as e:
            logger.warning("Solana ecosystem JSON error: %s", e)

        # 2. Solana governance / DAO proposals via Realms API
        try:
            resp = await client.get(
                "https://api.realms.today/realms/v2",
                headers={"Accept": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                realms = resp.json()
                if isinstance(realms, list):
                    # Get top DAOs by member count or activity
                    for realm in realms[:20]:
                        name = realm.get("displayName", realm.get("name", ""))
                        if not name:
                            continue
                        members = realm.get("membersCount", 0) or 0
                        proposals = realm.get("proposalsCount", 0) or 0
                        if proposals > 0 or members > 100:
                            signals.append({
                                "source": "realms_dao",
                                "signal_type": "governance",
                                "name": f"Solana DAO: {name}",
                                "content": f"{name}: {members} members, {proposals} proposals",
                                "url": f"https://app.realms.today/dao/{realm.get('symbol', name)}",
                                "score": min(proposals + members // 10, 50),
                                "topics": ["governance", "defi"],
                                "collected_at": datetime.now(timezone.utc).isoformat(),
                            })
        except Exception as e:
            logger.warning("Realms DAO error: %s", e)

        # 3. Solana DeFi governance via Tally (GraphQL)
        try:
            query = """
            query {
              governances(chainIds: ["solana:mainnet"], pagination: { limit: 10 }) {
                nodes {
                  name
                  slug
                  proposalCount
                  tokenHoldersCount
                  organization {
                    name
                    slug
                  }
                }
              }
            }
            """
            resp = await client.post(
                "https://api.tally.xyz/query",
                json={"query": query},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                nodes = data.get("data", {}).get("governances", {}).get("nodes", [])
                for gov in nodes:
                    name = gov.get("name", "")
                    proposals = gov.get("proposalCount", 0) or 0
                    holders = gov.get("tokenHoldersCount", 0) or 0
                    slug = gov.get("slug", "")
                    org_name = gov.get("organization", {}).get("name", name)
                    if proposals > 0:
                        signals.append({
                            "source": "tally_governance",
                            "signal_type": "governance",
                            "name": f"Governance: {org_name or name}",
                            "content": f"{org_name}: {proposals} proposals, {holders} token holders",
                            "url": f"https://www.tally.xyz/gov/{slug}" if slug else "",
                            "score": min(proposals * 3, 40),
                            "topics": ["governance", "defi"],
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                        })
        except Exception as e:
            logger.warning("Tally governance error: %s", e)

    logger.info("Solana Ecosystem: %s signals", len(signals))
    return signals


def _categorize(category: str, name: str, desc: str) -> List[str]:
    text = f"{category} {name} {desc}".lower()
    topics = ["solana_ecosystem"]

    mapping = {
        "defi": ["defi", "lending", "borrow", "swap", "dex", "amm", "yield", "vault"],
        "nft": ["nft", "collectible", "art", "metaplex"],
        "gaming": ["game", "gaming", "play", "metaverse"],
        "infrastructure": ["infra", "rpc", "validator", "bridge", "oracle", "sdk"],
        "payments": ["payment", "pay", "wallet", "transfer"],
        "ai_agents": ["ai", "agent", "machine learning", "llm"],
        "social": ["social", "messaging", "community"],
        "governance": ["dao", "governance", "voting"],
    }
    for topic, keywords in mapping.items():
        if any(kw in text for kw in keywords):
            topics.append(topic)
    return topics
