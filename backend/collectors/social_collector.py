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
    # Check for pre-collected social cache first
    cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "social_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                cache = json.load(f)
            cache_ts = datetime.fromisoformat(cache.get("collected_at", "2000-01-01"))
            age_hours = (datetime.utcnow() - cache_ts).total_seconds() / 3600
            if age_hours < 6:
                cached_signals = cache.get("signals", [])
                print(f"  → Social: using {len(cached_signals)} cached signals ({age_hours:.1f}h old)")
                # Still collect non-twitter signals live
                ecosystem_signals = await _collect_ecosystem_signals()
                reddit_signals = await _collect_reddit_signals()
                return cached_signals + ecosystem_signals + reddit_signals
        except Exception as e:
            print(f"  ⚠️ Cache load error: {e}")
    
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
    
    # Apply spam filter to twitter signals
    signals = filter_spam(signals)
    
    print(f"  → Social: {len(signals)} signals ({len(xbird_signals)} twitter, {len(ecosystem_signals)} ecosystem, {len(reddit_signals)} reddit)")
    return signals


async def _collect_via_xbird() -> List[Dict]:
    """Collect tweets via direct Twitter API (httpx) or fallback to Nitter/syndication."""
    from .twitter_api import search_tweets, get_home_timeline, get_credentials
    
    signals = []
    
    # Try direct Twitter API with cookie auth
    if get_credentials():
        try:
            # Home timeline - filter for Solana content
            home_tweets = await get_home_timeline(50)
            for tweet in home_tweets:
                if _is_solana_related(tweet.get("text", "")):
                    signals.append({
                        "source": "twitter",
                        "signal_type": "kol_tweet",
                        "name": f"@{tweet.get('author', 'unknown')}: {tweet.get('text', '')[:80]}",
                        "content": tweet.get("text", "")[:500],
                        "author": tweet.get("author", ""),
                        "url": tweet.get("url", ""),
                        "likes": tweet.get("likes", 0),
                        "retweets": tweet.get("retweets", 0),
                        "replies": tweet.get("replies", 0),
                        "engagement": tweet.get("likes", 0) + tweet.get("retweets", 0),
                        "engagement_score": tweet.get("engagement_score", 0),
                        "topics": _extract_topics(tweet.get("text", "")),
                        "collected_at": datetime.utcnow().isoformat()
                    })
            
            # Search queries — engagement-filtered + protocol-specific + KOLs
            search_queries = [
                '"solana" min_faves:50',
                '"building on solana" min_faves:20',
                '"$SOL" min_faves:100',
                '"jupiter solana" OR "jup airdrop" OR "@JupiterExchange" min_faves:20',
                '"jito solana" OR "jito tips" min_faves:20',
                '"pump.fun" OR "pumpfun" min_faves:30',
                '"solana ai agent" OR "eliza solana" OR "ai16z" min_faves:20',
                '"solana depin" OR "helium solana" min_faves:20',
                '"solana rwa" OR "tokenized assets solana" min_faves:10',
                '"solana staking" OR "liquid staking solana" min_faves:20',
                '"solana" "just launched" min_faves:10',
                '"solana" "alpha" min_faves:30',
                '"solana" "narrative" min_faves:20',
                '"solana" "bullish" min_faves:50',
                "from:0xMert_ solana",
                "from:aeyakovenko",
                "from:rajgokal",
            ]
            for query in search_queries:
                tweets = await search_tweets(query, 20)
                for tweet in tweets:
                    signals.append({
                        "source": "twitter",
                        "signal_type": "trending_topic",
                        "name": f"@{tweet.get('author', 'unknown')}: {tweet.get('text', '')[:60]}",
                        "query": query,
                        "content": tweet.get("text", "")[:500],
                        "author": tweet.get("author", ""),
                        "url": tweet.get("url", ""),
                        "likes": tweet.get("likes", 0),
                        "retweets": tweet.get("retweets", 0),
                        "replies": tweet.get("replies", 0),
                        "engagement": tweet.get("likes", 0) + tweet.get("retweets", 0),
                        "engagement_score": tweet.get("engagement_score", 0),
                        "topics": _extract_topics(tweet.get("text", "")),
                        "collected_at": datetime.utcnow().isoformat()
                    })
            if signals:
                return signals
        except Exception as e:
            print(f"  ⚠️ Twitter API collection error: {e}")
    else:
        print("  ⚠️ Twitter credentials not set, skipping direct API")
    
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
                                    "url": f"https://x.com/{kol}",
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
                                "url": f"https://x.com/{kol}",
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
                        "url": "https://solscan.io",
                        "topics": ["infrastructure"],
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
        
        # 2. Jupiter aggregator stats
        try:
            resp = await client.get("https://api.jup.ag/tokens/v1/trending")
            if resp.status_code == 200:
                data = resp.json()
                tokens = data if isinstance(data, list) else []
                for token in tokens[:5]:
                    name = token.get("name", "Unknown")
                    symbol = token.get("symbol", "?")
                    signals.append({
                        "source": "jupiter",
                        "signal_type": "trending_token",
                        "name": f"Jupiter trending: {symbol} ({name})",
                        "content": f"Trending token on Jupiter: {name} ({symbol})",
                        "url": "https://jup.ag",
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
                            "url": p.get("website", p.get("url", "")),
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
                        "url": f"https://defillama.com/yields/pool/{pool.get('pool', '')}",
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
                            "url": f"https://reddit.com{p.get('permalink', '')}",
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
                        "url": f"https://reddit.com{p.get('permalink', '')}",
                        "topics": _extract_topics(title),
                        "collected_at": datetime.utcnow().isoformat()
                    })
        except Exception:
            pass
    
    return signals


def _parse_xbird_output(output: str) -> List[Dict]:
    """Parse xbird CLI output into structured tweets.
    
    xbird format:
    @handle (Display Name):
    Tweet text...
    📅 date
    🔗 https://x.com/...
    ──────────
    """
    tweets = []
    current_tweet = {}
    
    for line in output.strip().split("\n"):
        line = line.strip()
        
        # Separator line — finalize current tweet
        if line.startswith("─"):
            if current_tweet:
                tweets.append(current_tweet)
                current_tweet = {}
            continue
        
        if not line:
            continue
        
        # Tweet URL
        url_match = re.match(r'🔗\s*(https?://\S+)', line)
        if url_match:
            current_tweet["url"] = url_match.group(1)
            continue
        
        # Date line — skip
        if line.startswith("📅"):
            continue
        
        # Media thumbnail — skip
        if line.startswith("🎬"):
            continue
        
        # Author line
        author_match = re.match(r'^@(\w+)\b', line)
        if author_match:
            if current_tweet and current_tweet.get("text"):
                tweets.append(current_tweet)
            # Remainder after @handle becomes start of text
            remainder = line[author_match.end():].strip()
            # Strip optional "(Display Name):" prefix
            remainder = re.sub(r'^\([^)]*\):?\s*', '', remainder)
            current_tweet = {"author": author_match.group(1), "text": remainder}
            # Check for inline engagement numbers
            likes_match = re.search(r'(\d+)\s*likes?', remainder, re.I)
            rt_match = re.search(r'(\d+)\s*(?:retweets?|RTs?)', remainder, re.I)
            if likes_match:
                current_tweet["likes"] = int(likes_match.group(1))
            if rt_match:
                current_tweet["retweets"] = int(rt_match.group(1))
            continue
        
        # Content line
        if current_tweet is not None:
            current_tweet["text"] = (current_tweet.get("text", "") + " " + line).strip()
            if "author" not in current_tweet:
                current_tweet["author"] = "unknown"
        else:
            current_tweet = {"text": line, "author": "unknown"}
        
        # Extract engagement numbers if present
        likes_match = re.search(r'(\d+)\s*likes?', line, re.I)
        rt_match = re.search(r'(\d+)\s*(?:retweets?|RTs?)', line, re.I)
        if likes_match:
            current_tweet["likes"] = int(likes_match.group(1))
        if rt_match:
            current_tweet["retweets"] = int(rt_match.group(1))
    
    if current_tweet and current_tweet.get("text"):
        tweets.append(current_tweet)
    
    return tweets


def filter_spam(signals: List[Dict]) -> List[Dict]:
    """Filter out bot/spam tweets from collected signals."""
    seen_texts = set()
    filtered = []
    
    for signal in signals:
        content = signal.get("content", "")
        
        # Skip tweets shorter than 30 chars
        if len(content.strip()) < 30:
            continue
        
        # Skip tweets with more than 3 $TICKER mentions (shill bots)
        ticker_mentions = re.findall(r'\$[A-Z]{2,10}', content)
        if len(ticker_mentions) > 3:
            continue
        
        # Skip scam pattern: "airdrop" + "claim" + URL
        content_lower = content.lower()
        if ("airdrop" in content_lower and "claim" in content_lower
                and re.search(r'https?://', content)):
            continue
        
        # Skip pure price callouts with no substance (e.g. "$SOL $123.45" and nothing else)
        if re.match(r'^\s*\$[A-Z]{2,10}\s+\$?\d+[\d.,]*\s*$', content.strip()):
            continue
        
        # Deduplicate near-identical content (normalize whitespace for comparison)
        normalized = re.sub(r'\s+', ' ', content.strip().lower())[:200]
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)
        
        filtered.append(signal)
    
    return filtered


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
