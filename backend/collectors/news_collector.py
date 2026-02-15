"""Collect Solana-related news from crypto RSS feeds"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

RSS_FEEDS = {
    "cointelegraph": "https://cointelegraph.com/rss",
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "theblock": "https://www.theblock.co/rss.xml",
    "decrypt": "https://decrypt.co/feed",
    "dlnews": "https://www.dlnews.com/arc/outboundfeeds/rss/",
}

SOLANA_KEYWORDS = [
    "solana", " sol ", "$sol", "phantom wallet", "jupiter exchange", "jupiter dex",
    "raydium", "orca ", "marinade", "jito", "tensor", "helius",
    "drift protocol", "bonk", "wif", "pump.fun", "pumpfun",
    "backpack exchange", "magic eden", "magiceden", "metaplex",
    "pyth network", "wormhole", "helium solana", "render solana",
    "solana mobile", "saga phone", "firedancer", "frankendancer",
    "solana defi", "solana nft", "solana ecosystem", "solana blockchain",
]

TOPIC_MAP = {
    "defi": ["defi", "lending", "borrowing", "yield", "liquidity", "amm", "dex", "swap", "tvl"],
    "nft": ["nft", "collection", "mint", "tensor", "magic eden", "metaplex"],
    "gaming": ["gaming", "game", "play", "metaverse", "gamefi"],
    "infrastructure": ["firedancer", "validator", "rpc", "upgrade", "release", "tps"],
    "regulation": ["regulation", "sec", "regulat", "compliance", "legal", "lawsuit", "etf"],
    "memecoins": ["memecoin", "meme coin", "bonk", "wif", "pump.fun", "degen"],
    "ai_agents": ["ai agent", "ai ", "artificial intelligence", "machine learning", "llm"],
    "payments": ["payment", "pay", "visa", "mastercard", "shopify"],
    "mobile": ["mobile", "saga", "dapp store", "sms"],
    "staking": ["staking", "stake", "liquid staking", "msol", "jitosol"],
    "rwa": ["rwa", "real world asset", "tokeniz"],
    "trading": ["trading", "perp", "futures", "leverage", "exchange"],
}

USER_AGENT = "SolanaNarrativeRadar/1.0"
REQUEST_DELAY = 1.0


def _is_solana_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in SOLANA_KEYWORDS)


def _detect_topics(text: str) -> List[str]:
    text_lower = text.lower()
    topics = []
    for topic, kws in TOPIC_MAP.items():
        if any(kw in text_lower for kw in kws):
            topics.append(topic)
    return topics if topics else ["general"]


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Try ISO format
    for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_rss(xml_text: str, outlet: str) -> List[Dict]:
    """Parse RSS XML into article dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("RSS parse error for %s: %s", outlet, e)
        return []

    # Handle both RSS 2.0 and Atom
    ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/",
          "content": "http://purl.org/rss/1.0/modules/content/"}

    # RSS 2.0: channel/item
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = _strip_html(item.findtext("description") or item.findtext("content:encoded", namespaces=ns) or "")
        pub_date = item.findtext("pubDate") or item.findtext("dc:date", namespaces=ns) or ""
        items.append({"title": title, "link": link, "description": desc, "published": pub_date, "outlet": outlet})

    # Atom: entry
    if not items:
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href", "") if link_el is not None else ""
            desc = _strip_html(entry.findtext("{http://www.w3.org/2005/Atom}summary") or
                               entry.findtext("{http://www.w3.org/2005/Atom}content") or "")
            pub_date = entry.findtext("{http://www.w3.org/2005/Atom}published") or \
                       entry.findtext("{http://www.w3.org/2005/Atom}updated") or ""
            items.append({"title": title, "link": link, "description": desc, "published": pub_date, "outlet": outlet})

    return items


async def _fetch_feed(client: httpx.AsyncClient, outlet: str, url: str) -> List[Dict]:
    """Fetch and parse a single RSS feed."""
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            logger.warning("RSS %s returned %d", outlet, resp.status_code)
            return []
        return _parse_rss(resp.text, outlet)
    except Exception as e:
        logger.warning("RSS %s error: %s", outlet, e)
        return []


async def collect() -> List[Dict]:
    """Collect Solana-related news from crypto RSS feeds."""
    signals = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)  # 48h window for reliability

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for outlet, url in RSS_FEEDS.items():
            articles = await _fetch_feed(client, outlet, url)
            logger.info("RSS %s: %d articles fetched", outlet, len(articles))

            for art in articles:
                combined = f"{art['title']} {art['description']}"
                if not _is_solana_related(combined):
                    continue

                # Filter by date
                pub_dt = _parse_date(art["published"])
                if pub_dt and pub_dt < cutoff:
                    continue

                detected = _detect_topics(combined)

                signals.append({
                    "name": art["title"],
                    "content": art["description"][:500],
                    "source": "news",
                    "signal_type": "news_article",
                    "url": art["link"],
                    "topics": detected,
                    "engagement": 0,
                    "timestamp": art["published"],
                    "metadata": {
                        "type": "news",
                        "outlet": outlet,
                        "published": art["published"],
                    },
                    "collected_at": datetime.utcnow().isoformat(),
                })

            await asyncio.sleep(REQUEST_DELAY)

    logger.info("News collector: %d Solana-related articles from %d feeds", len(signals), len(RSS_FEEDS))
    return signals


if __name__ == "__main__":
    import json as _json
    logging.basicConfig(level=logging.INFO)

    async def _main():
        results = await collect()
        print(f"\n=== News Collector: {len(results)} signals ===\n")
        for s in results[:10]:
            print(f"[{s['metadata']['outlet']}] {s['name'][:80]}")
        if results:
            print(f"\nSample:\n{_json.dumps(results[0], indent=2, default=str)}")

    asyncio.run(_main())
