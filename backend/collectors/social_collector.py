"""Collect social signals from X/Twitter and other sources"""
import subprocess
import json
import httpx
import os
import re
from datetime import datetime
from typing import List, Dict

# KOLs to monitor
SOLANA_KOLS = [
    "0xMert_",        # Mert (Helius)
    "aeyakovenko",    # Anatoly Yakovenko (Toly)
    "rajgokal",       # Raj (Solana co-founder)
    "armaboronnikov", # Akshay
    "shaboronnikov",  # Shaw (Eliza/ai16z)
    "JupiterExchange",
    "DriftProtocol",
    "heaboronnikov",  # Helius
    "solaboronnikov",  # Solana
]

SOLANA_KEYWORDS = [
    "solana", "sol", "defi", "nft", "anchor", "helius",
    "jupiter", "drift", "agent", "ai agent", "onchain",
    "jito", "marinade", "raydium", "orca", "phantom",
    "backpack", "tensor", "pump.fun", "bonk", "wif",
]


async def collect_kol_tweets() -> List[Dict]:
    """Collect social signals using multiple methods with fallbacks"""
    signals = []
    
    # Method 1: xbird CLI (local only)
    xbird_signals = await _collect_via_xbird()
    if xbird_signals:
        signals.extend(xbird_signals)
    
    # Method 2: Solana ecosystem RSS/APIs (always works)
    ecosystem_signals = await _collect_ecosystem_signals()
    signals.extend(ecosystem_signals)
    
    # Method 3: Reddit Solana community
    reddit_signals = await _collect_reddit_signals()
    signals.extend(reddit_signals)
    
    print(f"  → Social: {len(signals)} signals ({len(xbird_signals)} twitter, {len(ecosystem_signals)} ecosystem, {len(reddit_signals)} reddit)")
    return signals


async def _collect_via_xbird() -> List[Dict]:
    """Collect tweets via xbird CLI (only works locally) or Nitter RSS fallback"""
    signals = []
    
    # Try xbird CLI first (local dev only)
    try:
        result = subprocess.run(["which", "xbird"], capture_output=True, timeout=5)
        if result.returncode == 0:
            result = subprocess.run(
                ["xbird", "home", "--count", "50"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                tweets = _parse_xbird_output(result.stdout)
                for tweet in tweets:
                    if _is_solana_related(tweet.get("text", "")):
                        signals.append({
                            "source": "twitter",
                            "signal_type": "kol_tweet",
                            "name": f"@{tweet.get('author', 'unknown')}: {tweet.get('text', '')[:80]}",
                            "content": tweet.get("text", "")[:500],
                            "author": tweet.get("author", ""),
                            "engagement": tweet.get("likes", 0) + tweet.get("retweets", 0),
                            "topics": _extract_topics(tweet.get("text", "")),
                            "collected_at": datetime.utcnow().isoformat()
                        })
            
            for query in ["solana narrative", "building on solana", "solana alpha"]:
                result = subprocess.run(
                    ["xbird", "search", query, "--count", "20"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    tweets = _parse_xbird_output(result.stdout)
                    for tweet in tweets:
                        signals.append({
                            "source": "twitter",
                            "signal_type": "trending_topic",
                            "name": f"Search '{query}': {tweet.get('text', '')[:60]}",
                            "query": query,
                            "content": tweet.get("text", "")[:500],
                            "topics": _extract_topics(tweet.get("text", "")),
                            "collected_at": datetime.utcnow().isoformat()
                        })
            if signals:
                return signals
    except Exception as e:
        print(f"  ⚠️ xbird collection error: {e}")
    
    # Fallback: Nitter RSS feeds for KOL monitoring
    nitter_signals = await _collect_via_nitter()
    signals.extend(nitter_signals)
    
    # Fallback: Syndication API (Twitter's public embed API)
    syndication_signals = await _collect_via_syndication()
    signals.extend(syndication_signals)
    
    return signals


async def _collect_via_nitter() -> List[Dict]:
    """Collect KOL tweets via Nitter RSS instances (no auth needed)"""
    signals = []
    nitter_instances = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.net",
    ]
    
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for kol in SOLANA_KOLS[:6]:  # Top 6 KOLs to avoid rate limits
            for instance in nitter_instances:
                try:
                    resp = await client.get(f"{instance}/{kol}/rss")
                    if resp.status_code == 200 and "<item>" in resp.text:
                        items = _parse_rss_items(resp.text, kol)
                        for item in items:
                            if _is_solana_related(item.get("text", "")):
                                signals.append({
                                    "source": "twitter_nitter",
                                    "signal_type": "kol_tweet",
                                    "name": f"@{kol}: {item['text'][:80]}",
                                    "content": item["text"][:500],
                                    "author": kol,
                                    "topics": _extract_topics(item["text"]),
                                    "collected_at": datetime.utcnow().isoformat()
                                })
                        break  # Got data from this instance, move to next KOL
                except Exception:
                    continue  # Try next instance
    
    return signals


async def _collect_via_syndication() -> List[Dict]:
    """Collect tweets via Twitter's public syndication/search API"""
    signals = []
    
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        # Twitter syndication timeline (public, no auth)
        for kol in SOLANA_KOLS[:4]:
            try:
                resp = await client.get(
                    f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{kol}",
                    headers={"User-Agent": "Mozilla/5.0 (compatible; NarrativeRadar/1.0)"}
                )
                if resp.status_code == 200:
                    # Extract tweet text from HTML response
                    tweet_texts = re.findall(r'<p[^>]*class="[^"]*timeline-Tweet-text[^"]*"[^>]*>(.*?)</p>', resp.text, re.S)
                    for text in tweet_texts[:5]:
                        clean_text = re.sub(r'<[^>]+>', '', text).strip()
                        if clean_text and _is_solana_related(clean_text):
                            signals.append({
                                "source": "twitter_syndication",
                                "signal_type": "kol_tweet",
                                "name": f"@{kol}: {clean_text[:80]}",
                                "content": clean_text[:500],
                                "author": kol,
                                "topics": _extract_topics(clean_text),
                                "collected_at": datetime.utcnow().isoformat()
                            })
            except Exception:
                pass
    
    return signals


def _parse_rss_items(rss_xml: str, author: str) -> List[Dict]:
    """Parse RSS XML into tweet items"""
    items = []
    # Simple regex parsing for RSS items
    item_blocks = re.findall(r'<item>(.*?)</item>', rss_xml, re.S)
    for block in item_blocks[:10]:
        title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', block, re.S)
        if not title_match:
            title_match = re.search(r'<title>(.*?)</title>', block, re.S)
        desc_match = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>', block, re.S)
        
        text = ""
        if desc_match:
            text = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip()
        elif title_match:
            text = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        
        if text:
            items.append({"text": text, "author": author})
    
    return items


async def _collect_ecosystem_signals() -> List[Dict]:
    """Collect signals from Solana ecosystem APIs (no auth needed)"""
    signals = []
    
    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Solana Beach validators/stats (free API)
        try:
            resp = await client.get("https://api.solscan.io/chaininfo")
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                if data:
                    signals.append({
                        "source": "solscan",
                        "signal_type": "chain_stats",
                        "name": f"Solana TPS: {data.get('transactionCount', 'N/A')}",
                        "content": json.dumps(data),
                        "topics": ["infrastructure"],
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
        
        # 2. Jupiter aggregator stats
        try:
            resp = await client.get("https://stats.jup.ag/info/day")
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    signals.append({
                        "source": "jupiter",
                        "signal_type": "dex_stats",
                        "name": f"Jupiter daily volume: ${data.get('volumeInUSD', 0):,.0f}" if isinstance(data.get('volumeInUSD'), (int, float)) else "Jupiter stats",
                        "content": json.dumps(data)[:500],
                        "topics": ["defi", "trading"],
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
        
        # 3. Solana ecosystem project list from SolanaFM
        try:
            resp = await client.get("https://hyper.solana.fm/v0/ecosystem")
            if resp.status_code == 200:
                projects = resp.json()
                if isinstance(projects, list):
                    for p in projects[:20]:
                        category = p.get("category", "other").lower()
                        signals.append({
                            "source": "solanafm",
                            "signal_type": "ecosystem_project",
                            "name": p.get("name", "Unknown"),
                            "content": p.get("description", "")[:300],
                            "topics": [category] if category else ["other"],
                            "collected_at": datetime.utcnow().isoformat()
                        })
        except Exception:
            pass
        
        # 4. DeFi Llama Solana yields (trending yields = narrative signal)
        try:
            resp = await client.get("https://yields.llama.fi/pools")
            if resp.status_code == 200:
                pools = resp.json().get("data", [])
                solana_pools = [p for p in pools if p.get("chain") == "Solana"]
                # Sort by TVL change to find trending
                for pool in sorted(solana_pools, key=lambda x: x.get("tvlUsd", 0), reverse=True)[:10]:
                    signals.append({
                        "source": "defillama_yields",
                        "signal_type": "yield_signal",
                        "name": f"{pool.get('project', '?')}/{pool.get('symbol', '?')} APY:{pool.get('apy', 0):.1f}% TVL:${pool.get('tvlUsd', 0):,.0f}",
                        "content": json.dumps({
                            "project": pool.get("project"),
                            "symbol": pool.get("symbol"),
                            "apy": pool.get("apy"),
                            "tvl": pool.get("tvlUsd"),
                        }),
                        "topics": ["defi", "staking"] if "stake" in pool.get("symbol", "").lower() else ["defi"],
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
    
    return signals


async def _collect_reddit_signals() -> List[Dict]:
    """Collect signals from r/solana Reddit (no auth needed)"""
    signals = []
    
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "SolanaNarrativeRadar/1.0"}) as client:
        try:
            # Get hot posts from r/solana
            resp = await client.get("https://www.reddit.com/r/solana/hot.json?limit=25")
            if resp.status_code == 200:
                posts = resp.json().get("data", {}).get("children", [])
                for post in posts:
                    p = post.get("data", {})
                    title = p.get("title", "")
                    score = p.get("score", 0)
                    num_comments = p.get("num_comments", 0)
                    
                    if score > 10:  # Only meaningful posts
                        signals.append({
                            "source": "reddit",
                            "signal_type": "community_discussion",
                            "name": f"r/solana: {title[:80]}",
                            "content": f"{title} | Score: {score} | Comments: {num_comments} | {p.get('selftext', '')[:200]}",
                            "engagement": score + num_comments,
                            "topics": _extract_topics(title),
                            "collected_at": datetime.utcnow().isoformat()
                        })
        except Exception as e:
            print(f"  ⚠️ Reddit collection error: {e}")
        
        # Also check r/solanadev for developer signals
        try:
            resp = await client.get("https://www.reddit.com/r/solanadev/hot.json?limit=15")
            if resp.status_code == 200:
                posts = resp.json().get("data", {}).get("children", [])
                for post in posts:
                    p = post.get("data", {})
                    title = p.get("title", "")
                    signals.append({
                        "source": "reddit",
                        "signal_type": "dev_discussion",
                        "name": f"r/solanadev: {title[:80]}",
                        "content": f"{title} | {p.get('selftext', '')[:200]}",
                        "topics": _extract_topics(title),
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
    
    return signals


def _parse_xbird_output(output: str) -> List[Dict]:
    """Parse xbird CLI output into structured tweets"""
    tweets = []
    current_tweet = {}
    
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            if current_tweet:
                tweets.append(current_tweet)
                current_tweet = {}
            continue
        
        # Try to extract author from @mention pattern
        author_match = re.match(r'^@(\w+)', line)
        if author_match:
            if current_tweet:
                tweets.append(current_tweet)
            current_tweet = {"author": author_match.group(1), "text": line}
        elif current_tweet:
            current_tweet["text"] = current_tweet.get("text", "") + " " + line
        else:
            current_tweet = {"text": line, "author": "unknown"}
        
        # Extract engagement numbers if present
        likes_match = re.search(r'(\d+)\s*likes?', line, re.I)
        rt_match = re.search(r'(\d+)\s*(?:retweets?|RTs?)', line, re.I)
        if likes_match:
            current_tweet["likes"] = int(likes_match.group(1))
        if rt_match:
            current_tweet["retweets"] = int(rt_match.group(1))
    
    if current_tweet:
        tweets.append(current_tweet)
    
    return tweets


def _is_solana_related(text: str) -> bool:
    """Check if text is related to Solana ecosystem"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in SOLANA_KEYWORDS)


def _extract_topics(text: str) -> List[str]:
    """Extract topic categories from text"""
    text_lower = text.lower()
    topics = []
    
    topic_keywords = {
        "defi": ["defi", "lending", "borrowing", "yield", "liquidity", "amm", "dex", "swap", "tvl"],
        "ai_agents": ["ai agent", "agent", "autonomous", "llm", "gpt", "claude", "eliza"],
        "trading": ["trading", "trade", "perp", "futures", "leverage", "long", "short"],
        "infrastructure": ["rpc", "validator", "node", "infrastructure", "sdk", "framework"],
        "memecoins": ["memecoin", "meme", "bonk", "wif", "pump", "degen"],
        "staking": ["staking", "stake", "validator", "delegation", "msol", "jitosol"],
        "nft": ["nft", "collection", "mint", "tensor", "magiceden"],
        "gaming": ["gaming", "game", "play", "metaverse"],
        "rwa": ["rwa", "real world", "tokenized", "treasury"],
        "payments": ["payment", "pay", "transfer", "remittance"],
    }
    
    for topic, keywords in topic_keywords.items():
        if any(kw in text_lower for kw in keywords):
            topics.append(topic)
    
    return topics if topics else ["other"]
