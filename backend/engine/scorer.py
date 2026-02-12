"""Score raw signals based on velocity, convergence, novelty, and authority"""
from typing import List, Dict
from datetime import datetime, timedelta
from collections import Counter

def score_signals(signals: List[Dict]) -> List[Dict]:
    """Score each signal and return sorted by score"""
    
    # Group signals by theme/topic
    topic_counts = Counter()
    for s in signals:
        topics = extract_topics(s)
        for t in topics:
            topic_counts[t] += 1
    
    scored = []
    for s in signals:
        topics = extract_topics(s)
        
        # Velocity: based on recency and growth metrics
        velocity = calculate_velocity(s)
        
        # Convergence: how many other signals point to same topic
        convergence = max(topic_counts.get(t, 0) for t in topics) if topics else 0
        convergence_score = min(convergence * 10, 100)
        
        # Novelty: new repos, new programs get higher scores
        novelty = calculate_novelty(s)
        
        # Authority: KOL tweets, high-star repos score higher
        authority = calculate_authority(s)
        
        # Weighted composite score
        total_score = (
            velocity * 0.30 +
            convergence_score * 0.40 +
            novelty * 0.20 +
            authority * 0.10
        )
        
        s["score"] = round(total_score, 1)
        s["score_breakdown"] = {
            "velocity": round(velocity, 1),
            "convergence": round(convergence_score, 1),
            "novelty": round(novelty, 1),
            "authority": round(authority, 1)
        }
        s["topics"] = topics
        scored.append(s)
    
    return sorted(scored, key=lambda x: x["score"], reverse=True)


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


def calculate_velocity(signal: Dict) -> float:
    """Calculate velocity score based on growth metrics"""
    score = 50  # baseline
    
    # GitHub repos: stars as proxy for velocity
    if signal.get("source") == "github":
        stars = signal.get("stars", 0)
        if stars > 100: score += 30
        elif stars > 50: score += 20
        elif stars > 10: score += 10
    
    # DeFiLlama: TVL change
    if signal.get("source") == "defillama":
        change_7d = abs(signal.get("change_7d", 0))
        if change_7d > 50: score += 40
        elif change_7d > 20: score += 25
        elif change_7d > 10: score += 15
    
    return min(score, 100)


def calculate_novelty(signal: Dict) -> float:
    """Calculate novelty based on creation recency"""
    score = 50
    
    created = signal.get("created_at", "")
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            days_old = (datetime.now(created_dt.tzinfo) - created_dt).days
            if days_old < 7: score = 90
            elif days_old < 14: score = 70
            elif days_old < 30: score = 50
            else: score = 30
        except:
            pass
    
    if signal.get("signal_type") == "new_repo":
        score += 15
    
    return min(score, 100)


def calculate_authority(signal: Dict) -> float:
    """Calculate authority score"""
    score = 50
    
    if signal.get("source") == "github":
        stars = signal.get("stars", 0)
        if stars > 500: score = 90
        elif stars > 100: score = 70
    
    if signal.get("source") == "twitter":
        if signal.get("signal_type") == "kol_tweet":
            score = 80
    
    if signal.get("source") == "defillama":
        tvl = signal.get("tvl", 0)
        if tvl > 100_000_000: score = 90
        elif tvl > 10_000_000: score = 70
    
    return min(score, 100)
