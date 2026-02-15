"""Collect developer tooling trends from npm and crates.io registries."""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List

import httpx

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CACHE_FILE = os.path.join(DATA_DIR, "devtools_cache.json")

CRATES_UA = "SolanaNarrativeRadar/1.0 (contact@example.com)"

# --- Packages to monitor ---

NPM_PACKAGES = {
    "core": [
        ("@solana/web3.js", "Core SDK"),
        ("@solana/spl-token", "Token program"),
        ("@coral-xyz/anchor", "Anchor framework"),
        ("@solana/wallet-adapter-react", "Wallet integration"),
    ],
    "nft": [
        ("@metaplex-foundation/mpl-token-metadata", "NFT/metadata"),
        ("@tensor-oss/tensorswap-sdk", "Tensor NFTs"),
    ],
    "defi": [
        ("@drift-labs/sdk", "Drift protocol"),
        ("@jup-ag/core", "Jupiter"),
    ],
    "emerging": [
        ("@lightprotocol/compressed-token", "Compressed tokens"),
        ("@solana/actions", "Solana Actions/Blinks"),
        ("@helium/spl-utils", "Helium/DePIN"),
    ],
}

CRATES_PACKAGES = {
    "core": [
        ("solana-sdk", "Core Rust SDK"),
        ("solana-program", "On-chain program dev"),
        ("solana-client", "RPC client"),
        ("anchor-lang", "Anchor framework"),
    ],
    "token": [
        ("spl-token", "SPL token"),
        ("mpl-token-metadata", "Metaplex"),
    ],
    "emerging": [
        ("clockwork-sdk", "Automation"),
        ("pyth-sdk-solana", "Pyth oracle"),
    ],
}

ALL_NPM = [(pkg, desc, cat) for cat, pkgs in NPM_PACKAGES.items() for pkg, desc in pkgs]
ALL_CRATES = [(pkg, desc, cat) for cat, pkgs in CRATES_PACKAGES.items() for pkg, desc in pkgs]


def _load_cache() -> Dict:
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: Dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


async def _fetch_npm_downloads(client: httpx.AsyncClient, package: str) -> int:
    """Get last-week download count for an npm package."""
    try:
        resp = await client.get(
            f"https://api.npmjs.org/downloads/point/last-week/{package}",
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("downloads", 0)
    except Exception as e:
        logger.debug("npm downloads error for %s: %s", package, e)
    return 0


async def _fetch_crate_downloads(client: httpx.AsyncClient, crate: str) -> int:
    """Get recent download count for a crate (last 7 days from daily data)."""
    try:
        resp = await client.get(
            f"https://crates.io/api/v1/crates/{crate}/downloads",
            headers={"User-Agent": CRATES_UA},
            timeout=15,
        )
        if resp.status_code == 200:
            entries = resp.json().get("version_downloads", [])
            cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
            return sum(e.get("downloads", 0) for e in entries if e.get("date", "") >= cutoff)
    except Exception as e:
        logger.debug("crates.io downloads error for %s: %s", crate, e)
    await asyncio.sleep(1)  # rate limit
    return 0


async def _search_new_npm_packages(client: httpx.AsyncClient) -> List[Dict]:
    """Search for new Solana packages on npm."""
    signals = []
    try:
        resp = await client.get(
            "https://registry.npmjs.org/-/v1/search",
            params={"text": "solana", "size": 20, "quality": 0.5, "popularity": 0.98},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        for obj in resp.json().get("objects", []):
            pkg = obj.get("package", {})
            pub_date = pkg.get("date", "")
            if pub_date >= cutoff:
                name = pkg.get("name", "")
                desc = pkg.get("description", "")
                # Fetch downloads
                dl = await _fetch_npm_downloads(client, name)
                if dl >= 100:
                    signals.append(_make_signal(
                        f"New npm package '{name}' gaining traction ({dl} downloads in first week)",
                        f"{name}: {desc}. Published recently with {dl} weekly downloads.",
                        ["developer", "tooling", "new-package"],
                        min(dl / 10, 100),
                        {"registry": "npm", "package": name, "weekly_downloads": dl, "new": True},
                    ))
    except Exception as e:
        logger.debug("npm search error: %s", e)
    return signals


async def _search_new_crates(client: httpx.AsyncClient) -> List[Dict]:
    """Search for new Solana crates."""
    signals = []
    try:
        resp = await client.get(
            "https://crates.io/api/v1/crates",
            params={"q": "solana", "per_page": 20, "sort": "new"},
            headers={"User-Agent": CRATES_UA},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        for crate in resp.json().get("crates", []):
            created = crate.get("created_at", "")[:10]
            if created >= cutoff:
                name = crate.get("name", "")
                dl = crate.get("recent_downloads", 0)
                desc = crate.get("description", "")
                if dl >= 50:
                    signals.append(_make_signal(
                        f"New crate '{name}' published ({dl} recent downloads)",
                        f"{name}: {desc}. Recently published with {dl} downloads.",
                        ["developer", "tooling", "rust", "new-package"],
                        min(dl / 5, 100),
                        {"registry": "crates.io", "package": name, "weekly_downloads": dl, "new": True},
                    ))
        await asyncio.sleep(1)
    except Exception as e:
        logger.debug("crates.io search error: %s", e)
    return signals


def _make_signal(name: str, content: str, topics: List[str], engagement: float, metadata: Dict) -> Dict:
    return {
        "name": name,
        "content": content,
        "source": "github",  # developer activity category
        "topics": topics,
        "engagement": engagement,
        "signal_type": "devtools_trend",
        "collected_at": datetime.utcnow().isoformat(),
        "metadata": metadata,
    }


def _growth_pct(current: int, previous: int) -> float:
    if previous <= 0:
        return 0
    return round((current - previous) / previous * 100, 1)


def _category_label(cat: str) -> str:
    return {"core": "Core SDK", "nft": "NFT", "defi": "DeFi", "token": "Token", "emerging": "Emerging"}.get(cat, cat)


async def collect() -> List[Dict]:
    """Main entry point — collect developer tooling signals."""
    cache = _load_cache()
    prev_npm = cache.get("npm", {})
    prev_crates = cache.get("crates", {})
    signals: List[Dict] = []
    new_npm: Dict[str, int] = {}
    new_crates: Dict[str, int] = {}

    async with httpx.AsyncClient() as client:
        # --- npm downloads ---
        for pkg, desc, cat in ALL_NPM:
            dl = await _fetch_npm_downloads(client, pkg)
            new_npm[pkg] = dl
            if dl == 0:
                continue
            prev = prev_npm.get(pkg, 0)
            growth = _growth_pct(dl, prev)
            if prev > 0 and growth > 30:
                signals.append(_make_signal(
                    f"{pkg} downloads surge {growth}% week-over-week",
                    f"{pkg} ({desc}) saw {dl:,} downloads this week (up from {prev:,}). {_category_label(cat)} developer activity increasing.",
                    ["developer", "tooling", cat],
                    min(growth, 100),
                    {"registry": "npm", "package": pkg, "weekly_downloads": dl, "prev_downloads": prev, "growth_pct": growth, "category": cat},
                ))

        # --- crates.io downloads ---
        for crate, desc, cat in ALL_CRATES:
            dl = await _fetch_crate_downloads(client, crate)
            new_crates[crate] = dl
            if dl == 0:
                continue
            prev = prev_crates.get(crate, 0)
            growth = _growth_pct(dl, prev)
            if prev > 0 and growth > 30:
                signals.append(_make_signal(
                    f"{crate} crate downloads up {growth}% week-over-week",
                    f"{crate} ({desc}) saw {dl:,} downloads this week (up from {prev:,}). Rust {_category_label(cat)} dev activity rising.",
                    ["developer", "tooling", "rust", cat],
                    min(growth, 100),
                    {"registry": "crates.io", "package": crate, "weekly_downloads": dl, "prev_downloads": prev, "growth_pct": growth, "category": cat},
                ))

        # --- Category trends ---
        for cat_name, cat_packages in NPM_PACKAGES.items():
            cat_growths = []
            for pkg, _ in cat_packages:
                prev = prev_npm.get(pkg, 0)
                cur = new_npm.get(pkg, 0)
                if prev > 0 and cur > 0:
                    cat_growths.append(_growth_pct(cur, prev))
            if cat_growths and (avg := sum(cat_growths) / len(cat_growths)) > 20:
                signals.append(_make_signal(
                    f"{_category_label(cat_name)} developer activity increasing ({avg:.0f}% avg growth)",
                    f"Solana {_category_label(cat_name)} packages averaging {avg:.0f}% download growth across {len(cat_growths)} tracked packages.",
                    ["developer", "tooling", cat_name, "category-trend"],
                    min(avg, 100),
                    {"category": cat_name, "avg_growth_pct": round(avg, 1), "packages_tracked": len(cat_growths)},
                ))

        # --- Ecosystem health ---
        web3_dl = new_npm.get("@solana/web3.js", 0)
        sdk_dl = new_crates.get("solana-sdk", 0)
        if web3_dl > 0 or sdk_dl > 0:
            prev_web3 = prev_npm.get("@solana/web3.js", 0)
            prev_sdk = prev_crates.get("solana-sdk", 0)
            total = web3_dl + sdk_dl
            prev_total = prev_web3 + prev_sdk
            health_growth = _growth_pct(total, prev_total) if prev_total > 0 else 0
            signals.append(_make_signal(
                f"Solana ecosystem health: {total:,} core SDK downloads (npm+crates)",
                f"@solana/web3.js: {web3_dl:,} | solana-sdk: {sdk_dl:,}. Combined {'up' if health_growth > 0 else 'down'} {abs(health_growth):.0f}% WoW.",
                ["developer", "ecosystem-health"],
                max(min(health_growth, 100), 10),
                {"web3js_downloads": web3_dl, "solana_sdk_downloads": sdk_dl, "total": total, "growth_pct": health_growth},
            ))

        # --- New packages ---
        npm_new = await _search_new_npm_packages(client)
        signals.extend(npm_new)

        crates_new = await _search_new_crates(client)
        signals.extend(crates_new)

    # Save cache for next run
    _save_cache({
        "npm": new_npm,
        "crates": new_crates,
        "updated_at": datetime.utcnow().isoformat(),
    })

    logger.info("Devtools collector: %d signals", len(signals))
    return signals
