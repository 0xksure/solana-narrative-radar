"""Collect signals from Solana governance: SIMDs, forum, releases, DAOs"""
import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict

import httpx

logger = logging.getLogger(__name__)

GITHUB_HEADERS = {"Accept": "application/vnd.github.v3+json", "User-Agent": "SolanaNarrativeRadar/1.0"}
REQUEST_DELAY = 1.5

TOPIC_KEYWORDS = {
    "defi": ["defi", "swap", "amm", "lending", "liquidity", "yield"],
    "privacy": ["privacy", "confidential", "zero knowledge", "zk"],
    "token_extensions": ["token extension", "token-2022", "transfer hook", "mint close"],
    "staking": ["stake", "staking", "validator", "delegation", "slashing"],
    "fees": ["fee", "priority fee", "base fee", "fee market"],
    "compression": ["compress", "merkle", "state compression"],
    "performance": ["performance", "tps", "throughput", "latency", "turbine", "quic"],
    "security": ["security", "audit", "vulnerability", "exploit"],
    "governance": ["governance", "vote", "proposal", "dao"],
    "infrastructure": ["rpc", "validator", "node", "infrastructure", "runtime"],
    "mobile": ["mobile", "saga", "sms", "dapp store"],
    "ai_agents": ["ai", "agent", "llm", "machine learning"],
    "payments": ["payment", "pay", "transfer", "remittance"],
    "nft": ["nft", "metaplex", "collection", "compressed nft"],
}


def _detect_topics(text: str) -> List[str]:
    text_lower = text.lower()
    topics = []
    for topic, kws in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in kws):
            topics.append(topic)
    return topics


async def _collect_simds(client: httpx.AsyncClient) -> List[Dict]:
    """Collect open SIMDs from GitHub."""
    signals = []
    try:
        resp = await client.get(
            "https://api.github.com/repos/solana-foundation/solana-improvement-documents/issues",
            params={"state": "open", "sort": "updated", "per_page": 50},
            headers=GITHUB_HEADERS,
        )
        if resp.status_code != 200:
            logger.warning("SIMD fetch returned %d", resp.status_code)
            return []

        for issue in resp.json():
            title = issue.get("title", "")
            number = issue.get("number", 0)
            body = issue.get("body", "") or ""
            reactions = issue.get("reactions", {})
            reaction_count = sum(reactions.get(k, 0) for k in ["+1", "-1", "laugh", "hooray", "heart", "rocket", "eyes"]) if isinstance(reactions, dict) else 0
            comments = issue.get("comments", 0)
            labels = [l.get("name", "") for l in issue.get("labels", [])]

            combined = f"{title} {body}"
            detected = _detect_topics(combined)
            topics = ["governance", "infrastructure"] + detected

            signals.append({
                "name": f"SIMD-{number}: {title}",
                "content": body[:500],
                "source": "github",
                "signal_type": "governance_proposal",
                "url": issue.get("html_url", ""),
                "topics": list(set(topics)),
                "engagement": reaction_count + comments,
                "timestamp": issue.get("updated_at", ""),
                "metadata": {
                    "type": "simd",
                    "state": issue.get("state", "open"),
                    "labels": labels,
                    "reactions": reaction_count,
                    "comments": comments,
                    "author": issue.get("user", {}).get("login", ""),
                },
                "collected_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        logger.error("SIMD collection error: %s", e)
    return signals


async def _collect_solana_releases(client: httpx.AsyncClient) -> List[Dict]:
    """Collect recent Solana releases from GitHub."""
    signals = []
    try:
        resp = await client.get(
            "https://api.github.com/repos/anza-xyz/agave/releases",
            params={"per_page": 10},
            headers=GITHUB_HEADERS,
        )
        if resp.status_code != 200:
            # Fallback to solana-labs/solana
            resp = await client.get(
                "https://api.github.com/repos/solana-labs/solana/releases",
                params={"per_page": 10},
                headers=GITHUB_HEADERS,
            )
        if resp.status_code != 200:
            logger.warning("Solana releases fetch returned %d", resp.status_code)
            return []

        cutoff = datetime.utcnow() - timedelta(days=30)
        for rel in resp.json():
            published = rel.get("published_at", "")
            if published:
                try:
                    pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00")).replace(tzinfo=None)
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    pass

            body = rel.get("body", "") or ""
            tag = rel.get("tag_name", "")
            name = rel.get("name", "") or tag
            combined = f"{name} {body}"
            detected = _detect_topics(combined)
            topics = ["infrastructure", "release"] + detected

            signals.append({
                "name": f"Solana Release: {name}",
                "content": body[:500],
                "source": "github",
                "signal_type": "release",
                "url": rel.get("html_url", ""),
                "topics": list(set(topics)),
                "engagement": 0,
                "timestamp": published,
                "metadata": {
                    "type": "release",
                    "tag": tag,
                    "prerelease": rel.get("prerelease", False),
                    "author": rel.get("author", {}).get("login", ""),
                },
                "collected_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        logger.error("Solana releases error: %s", e)
    return signals


async def _collect_forum(client: httpx.AsyncClient) -> List[Dict]:
    """Collect latest topics from Solana forum (Discourse API)."""
    signals = []
    try:
        resp = await client.get(
            "https://forum.solana.com/latest.json",
            headers={"User-Agent": "SolanaNarrativeRadar/1.0"},
        )
        if resp.status_code != 200:
            logger.warning("Solana forum returned %d", resp.status_code)
            return []

        data = resp.json()
        topics = data.get("topic_list", {}).get("topics", [])

        for t in topics[:40]:
            title = t.get("title", "")
            topic_id = t.get("id", 0)
            views = t.get("views", 0)
            reply_count = t.get("reply_count", 0) + t.get("posts_count", 0)
            like_count = t.get("like_count", 0)
            slug = t.get("slug", "")

            combined = f"{title} {t.get('excerpt', '')}"
            detected = _detect_topics(combined)
            topic_tags = ["governance", "community"] + detected

            signals.append({
                "name": title,
                "content": t.get("excerpt", title)[:500],
                "source": "governance",
                "signal_type": "forum_discussion",
                "url": f"https://forum.solana.com/t/{slug}/{topic_id}",
                "topics": list(set(topic_tags)),
                "engagement": views + reply_count * 10 + like_count * 5,
                "timestamp": t.get("last_posted_at", ""),
                "metadata": {
                    "type": "forum",
                    "views": views,
                    "replies": reply_count,
                    "likes": like_count,
                    "category_id": t.get("category_id"),
                    "pinned": t.get("pinned", False),
                },
                "collected_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        logger.error("Forum collection error: %s", e)
    return signals


async def collect() -> List[Dict]:
    """Collect all governance signals."""
    signals = []

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        logger.info("Collecting SIMDs...")
        simds = await _collect_simds(client)
        signals.extend(simds)
        await asyncio.sleep(REQUEST_DELAY)

        logger.info("Collecting Solana releases...")
        releases = await _collect_solana_releases(client)
        signals.extend(releases)
        await asyncio.sleep(REQUEST_DELAY)

        logger.info("Collecting forum topics...")
        forum = await _collect_forum(client)
        signals.extend(forum)

    signals.sort(key=lambda s: s.get("engagement", 0), reverse=True)
    logger.info("Governance collector: %d signals (SIMDs=%d, releases=%d, forum=%d)",
                len(signals), len(simds), len(releases), len(forum))
    return signals


if __name__ == "__main__":
    import json as _json
    logging.basicConfig(level=logging.INFO)

    async def _main():
        results = await collect()
        print(f"\n=== Governance Collector: {len(results)} signals ===\n")
        for s in results[:10]:
            print(f"[{s['metadata']['type']}] (eng:{s['engagement']}) {s['name'][:80]}")
        if results:
            print(f"\nSample:\n{_json.dumps(results[0], indent=2, default=str)}")

    asyncio.run(_main())
