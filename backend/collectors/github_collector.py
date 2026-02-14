"""Collect developer activity signals from GitHub"""
import logging

logger = logging.getLogger(__name__)

import httpx
import os
from datetime import datetime, timedelta
from typing import List, Dict

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# Blocklist: exclude self-promotional / OpenClaw-related repos and orgs
BLOCKED_OWNERS = {"openclaw", "clawver", "clawd", "clawdbot", "0xksure"}
BLOCKED_REPO_KEYWORDS = {"openclaw", "clawver", "clawd", "clawdbot"}


def _is_blocked_repo(item: dict) -> bool:
    """Return True if this repo should be excluded."""
    owner = (item.get("owner", {}).get("login", "") or "").lower()
    full_name = (item.get("full_name", "") or "").lower()
    if owner in BLOCKED_OWNERS:
        return True
    return any(kw in full_name for kw in BLOCKED_REPO_KEYWORDS)

async def collect_new_solana_repos(days_back: int = 14) -> List[Dict]:
    """Find new Solana-related repos created in the last N days"""
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    query = f"solana created:>{since} sort:stars"
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "stars", "per_page": 50},
            headers=HEADERS,
            timeout=30
        )
        if resp.status_code != 200:
            logger.warning("GitHub API error: %s", resp.status_code)
            return []
        
        data = resp.json()
        repos = []
        for item in data.get("items", []):
            if _is_blocked_repo(item):
                continue
            repos.append({
                "source": "github",
                "signal_type": "new_repo",
                "name": item["full_name"],
                "description": item.get("description", ""),
                "stars": item["stargazers_count"],
                "forks": item["forks_count"],
                "language": item.get("language", ""),
                "created_at": item["created_at"],
                "pushed_at": item.get("pushed_at", ""),
                "owner_name": item.get("owner", {}).get("login", ""),
                "open_issues": item.get("open_issues_count", 0),
                "watchers": item.get("watchers_count", 0),
                "url": item["html_url"],
                "topics": item.get("topics", []),
                "collected_at": datetime.utcnow().isoformat()
            })
        return repos

async def collect_trending_solana_repos() -> List[Dict]:
    """Find Solana repos with accelerating star velocity"""
    queries = [
        "solana agent", "solana defi", "solana nft", "solana token",
        "anchor solana", "solana sdk", "solana ai", "solana payments"
    ]
    all_repos = []
    
    async with httpx.AsyncClient() as client:
        for query in queries:
            resp = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "updated", "per_page": 20},
                headers=HEADERS,
                timeout=30
            )
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    if _is_blocked_repo(item):
                        continue
                    all_repos.append({
                        "source": "github",
                        "signal_type": "trending_repo",
                        "name": item["full_name"],
                        "description": item.get("description", ""),
                        "stars": item["stargazers_count"],
                        "forks": item["forks_count"],
                        "language": item.get("language", ""),
                        "created_at": item.get("created_at", ""),
                        "pushed_at": item.get("pushed_at", ""),
                        "updated_at": item["updated_at"],
                        "owner_name": item.get("owner", {}).get("login", ""),
                        "open_issues": item.get("open_issues_count", 0),
                        "watchers": item.get("watchers_count", 0),
                        "url": item["html_url"],
                        "topics": item.get("topics", []),
                        "query_matched": query,
                        "collected_at": datetime.utcnow().isoformat()
                    })
    
    # Deduplicate by repo name
    seen = set()
    unique = []
    for r in all_repos:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    
    return sorted(unique, key=lambda x: x["stars"], reverse=True)
