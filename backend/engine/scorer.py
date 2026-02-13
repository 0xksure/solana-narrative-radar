"""Score raw signals based on velocity, convergence, novelty, authority, and quality"""
from typing import List, Dict, Set
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict

# Known Solana KOL handles for authority boosting
SOLANA_KOLS = {
    "aaboronkov", "aaboronkov_", "0xmert_", "rajgokal", "armaniferrante",
    "buffalu__", "solaboratory", "heaboratory", "taboratory", "anatoly_yakovenko",
    "jaraboratory", "solana_devs", "superteam", "jaboratory", "solana",
    "jito_sol", "mariaboratory", "drift_trade", "jupiterexchange",
    "helaboratory", "marginfi", "tensorhq", "kamino_finance", "raaboratory",
    "solendprotocol", "phantom", "backaboratory", "madlads", "bonk_inu",
    "waboratory", "solblaze_org",
}


def score_signals(signals: List[Dict]) -> List[Dict]:
    """Score each signal and return sorted by score"""

    # --- Build cross-source topic map ---
    # {topic: {source_type: count}}
    topic_sources: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # {topic: set of entity names seen}
    topic_entities: Dict[str, Set[str]] = defaultdict(set)
    # Track per-signal topics
    signal_topics_map: Dict[int, List[str]] = {}

    for i, s in enumerate(signals):
        topics = extract_topics(s)
        signal_topics_map[i] = topics
        source = _normalize_source(s.get("source", "unknown"))
        entity = (s.get("name") or "").strip().lower()
        for t in topics:
            topic_sources[t][source] += 1
            if entity:
                topic_entities[t].add(entity)

    # --- Build temporal data for acceleration ---
    signals_by_date: Dict[str, int] = defaultdict(int)
    topic_by_date: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for i, s in enumerate(signals):
        collected = s.get("collected_at") or s.get("created_at") or ""
        date_str = _parse_date_str(collected) or today_str
        signals_by_date[date_str] += 1
        for t in signal_topics_map[i]:
            topic_by_date[t][date_str] += 1

    # Cross-source entity overlap: entities appearing in 2+ source types
    cross_source_entities: Set[str] = set()
    entity_sources: Dict[str, Set[str]] = defaultdict(set)
    for i, s in enumerate(signals):
        source = _normalize_source(s.get("source", "unknown"))
        entity = (s.get("name") or "").strip().lower()
        if entity:
            entity_sources[entity].add(source)
    for ent, srcs in entity_sources.items():
        if len(srcs) >= 2:
            cross_source_entities.add(ent)

    scored = []
    for i, s in enumerate(signals):
        topics = signal_topics_map[i]

        velocity = calculate_velocity(s, signals_by_date, topic_by_date, topics, today_str)
        convergence_score = _calculate_convergence(s, topics, topic_sources, cross_source_entities)
        novelty = calculate_novelty(s)
        authority = calculate_authority(s)
        quality = _calculate_quality(s, topics, topic_sources, cross_source_entities)

        total_score = (
            velocity * 0.20 +
            convergence_score * 0.30 +
            novelty * 0.15 +
            authority * 0.15 +
            quality * 0.20
        )

        s["score"] = round(total_score, 1)
        s["score_breakdown"] = {
            "velocity": round(velocity, 1),
            "convergence": round(convergence_score, 1),
            "novelty": round(novelty, 1),
            "authority": round(authority, 1),
            "quality": round(quality, 1),
        }
        s["topics"] = topics
        scored.append(s)

    return sorted(scored, key=lambda x: x["score"], reverse=True)


def _normalize_source(source: str) -> str:
    """Normalize source variants to canonical type."""
    if source in ("twitter", "twitter_nitter", "twitter_syndication"):
        return "twitter"
    if source in ("solana_rpc", "solscan"):
        return "onchain"
    if source in ("defillama", "defillama_yields"):
        return "defillama"
    return source


def _parse_date_str(dt_str: str) -> str | None:
    """Extract YYYY-MM-DD from an ISO datetime string."""
    if not dt_str:
        return None
    try:
        return dt_str[:10]  # works for ISO format
    except Exception:
        return None


def _calculate_convergence(
    signal: Dict,
    topics: List[str],
    topic_sources: Dict[str, Dict[str, int]],
    cross_source_entities: Set[str],
) -> float:
    """Cross-source convergence scoring."""
    if not topics:
        return 20

    # Best topic by distinct source count
    best_distinct = 0
    for t in topics:
        distinct = len(topic_sources.get(t, {}))
        best_distinct = max(best_distinct, distinct)

    # Map distinct source count to score
    if best_distinct >= 4:
        score = 95
    elif best_distinct == 3:
        score = 75
    elif best_distinct == 2:
        score = 50
    else:
        score = 20

    # Bonus for cross-source entity match
    entity = (signal.get("name") or "").strip().lower()
    if entity and entity in cross_source_entities:
        score = min(score + 20, 100)

    return float(score)


def _calculate_quality(
    signal: Dict,
    topics: List[str],
    topic_sources: Dict[str, Dict[str, int]],
    cross_source_entities: Set[str],
) -> float:
    """Signal quality score (0-100)."""
    raw = 0

    # Has URL
    if signal.get("url") or signal.get("html_url"):
        raw += 10

    # Has engagement data
    if signal.get("engagement") or signal.get("engagement_score"):
        raw += 10

    # Rich content
    content = signal.get("content") or signal.get("description") or ""
    if len(content) > 100:
        raw += 10

    # Verified/known source
    source = signal.get("source", "")
    if source in ("solana_rpc", "solscan", "defillama", "defillama_yields", "birdeye"):
        raw += 15
    elif source == "github":
        raw += 10

    # Cross-source signal
    entity = (signal.get("name") or "").strip().lower()
    if entity and entity in cross_source_entities:
        raw += 20

    # Normalize 0-65 -> 0-100
    return min(raw / 65.0 * 100.0, 100.0)


def extract_topics(signal: Dict) -> List[str]:
    """Extract topic keywords from a signal"""
    text = " ".join([
        signal.get("name", "") or "",
        signal.get("description", "") or "",
        signal.get("content", "") or "",
        signal.get("category", "") or "",
        " ".join(signal.get("topics", []) or []),
    ]).lower()

    topic_keywords = {
        "ai_agents": ["ai agent", "agent", "autonomous", "llm", "chatbot", "eliza"],
        "defi": ["defi", "lending", "borrowing", "yield", "amm", "dex", "swap", "liquidity"],
        "payments": ["payment", "pay", "transfer", "remittance", "stablecoin"],
        "nft": ["nft", "collectible", "metaplex", "digital art"],
        "gaming": ["game", "gaming", "play-to-earn", "gamefi"],
        "depin": ["depin", "physical", "iot", "sensor", "infrastructure"],
        "social": ["social", "community", "messaging", "chat"],
        "privacy": ["privacy", "zero-knowledge", "zk", "confidential"],
        "rwa": ["rwa", "real world", "tokenized", "real-world asset"],
        "trading": ["trading", "perp", "perpetual", "futures", "options", "copy-trad"],
        "staking": ["staking", "stake", "liquid staking", "validator"],
        "bridge": ["bridge", "cross-chain", "interop", "wormhole"],
        "identity": ["identity", "did", "credential", "reputation"],
        "memecoins": ["meme", "memecoin", "pump.fun", "fair launch"],
        "infrastructure": ["infra", "rpc", "indexer", "sdk", "framework", "tooling"],
    }

    matched = []
    for topic, keywords in topic_keywords.items():
        if any(kw in text for kw in keywords):
            matched.append(topic)

    return matched if matched else ["other"]


def calculate_velocity(
    signal: Dict,
    signals_by_date: Dict[str, int] | None = None,
    topic_by_date: Dict[str, Dict[str, int]] | None = None,
    topics: List[str] | None = None,
    today_str: str | None = None,
) -> float:
    """Calculate velocity score using temporal acceleration when data available."""
    score = 50  # baseline

    # --- Temporal acceleration (if data provided) ---
    if signals_by_date and today_str:
        today_count = signals_by_date.get(today_str, 0)
        all_counts = list(signals_by_date.values())
        avg = sum(all_counts) / len(all_counts) if all_counts else 1
        if avg > 0:
            ratio = today_count / avg
            if ratio > 2.0:
                score += 25  # strong acceleration
            elif ratio > 1.5:
                score += 15  # moderate
            elif ratio < 0.8:
                score -= 10  # declining

    # Topic-specific acceleration
    if topic_by_date and topics and today_str:
        best_topic_boost = 0
        for t in topics:
            dates = topic_by_date.get(t, {})
            t_today = dates.get(today_str, 0)
            t_counts = list(dates.values())
            t_avg = sum(t_counts) / len(t_counts) if t_counts else 1
            if t_avg > 0:
                t_ratio = t_today / t_avg
                if t_ratio > 2.0:
                    best_topic_boost = max(best_topic_boost, 15)
                elif t_ratio > 1.5:
                    best_topic_boost = max(best_topic_boost, 8)
        score += best_topic_boost

    # --- Source-specific signals (kept from original) ---
    source = signal.get("source", "")

    if source == "defillama":
        change_7d = abs(signal.get("change_7d", 0))
        if change_7d > 50:
            score += 40
        elif change_7d > 20:
            score += 25
        elif change_7d > 10:
            score += 15

    if source in ("solana_rpc", "birdeye", "solscan"):
        if signal.get("signal_type") == "token_trending":
            score += 25
        elif signal.get("signal_type") == "network_activity":
            score += 10

    if source in ("twitter", "twitter_nitter", "twitter_syndication", "reddit"):
        engagement = signal.get("engagement", 0)
        if engagement > 100:
            score += 30
        elif engagement > 50:
            score += 20
        elif engagement > 10:
            score += 10
        if signal.get("signal_type") == "kol_tweet":
            score += 10

    if source == "defillama_yields":
        score += 15

    if source == "github":
        stars = signal.get("stars", 0)
        if stars > 100:
            score += 20
        elif stars > 50:
            score += 12
        elif stars > 10:
            score += 5

    return min(score, 100)


def calculate_novelty(signal: Dict) -> float:
    """Calculate novelty based on creation recency"""
    score = 50

    created = signal.get("created_at", "")
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            days_old = (datetime.now(created_dt.tzinfo) - created_dt).days
            if days_old < 7:
                score = 90
            elif days_old < 14:
                score = 70
            elif days_old < 30:
                score = 50
            else:
                score = 30
        except Exception:
            pass

    if signal.get("signal_type") == "new_repo":
        score += 15

    return min(score, 100)


def calculate_authority(signal: Dict) -> float:
    """Calculate authority score based on source credibility and engagement data"""
    score = 50

    source = signal.get("source", "")

    if source == "github":
        stars = signal.get("stars", 0)
        if stars > 500:
            score = 90
        elif stars > 100:
            score = 70
        elif stars > 20:
            score = 60

        # Recent push activity boost
        pushed_at = signal.get("pushed_at", "")
        if pushed_at:
            try:
                pushed_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                days_since = (datetime.now(pushed_dt.tzinfo) - pushed_dt).days
                if days_since < 7:
                    score = min(score + 15, 100)
                elif days_since < 30:
                    score = min(score + 5, 100)
            except Exception:
                pass

    if source in ("twitter", "twitter_nitter", "twitter_syndication"):
        # Use engagement_score if available
        eng = signal.get("engagement_score", 0)
        if eng > 500:
            score = 95
        elif eng > 200:
            score = 85
        elif eng > 50:
            score = 70
        elif eng > 10:
            score = 55
        elif signal.get("signal_type") == "kol_tweet":
            score = 80
        else:
            score = 55

        # KOL handle boost
        handle = (signal.get("author") or signal.get("handle") or "").lower().strip("@")
        if handle in SOLANA_KOLS:
            score = min(score + 15, 100)

    if source == "reddit":
        engagement = signal.get("engagement", 0)
        if engagement > 100:
            score = 75
        elif engagement > 30:
            score = 60
        if signal.get("signal_type") == "dev_discussion":
            score += 10

    if source == "defillama":
        tvl = signal.get("tvl", 0)
        if tvl > 100_000_000:
            score = 90
        elif tvl > 10_000_000:
            score = 70

    if source == "defillama_yields":
        score = 70

    if source in ("solana_rpc", "solscan"):
        score = 85

    if source == "birdeye":
        score = 70

    return min(score, 100)
