"""Tweet/signal authenticity verification and confidence scoring.

Heuristic-based system to filter scam/noise from legitimate social signals.
Each signal gets a confidence score (0-100). Scores < 30 are excluded from
narrative detection entirely.
"""
import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Official project accounts (lowercase) — signals from these get a boost
OFFICIAL_ACCOUNTS = {
    "solana", "solanafndn", "jupiterexchange", "daboratory",  
    "heaboratory", "phantom", "tensorhq", "marginfi", "kamino_finance",
    "jito_sol", "marinade_finance", "raydiumprotocol", "aboratory",
    "backpackexchange", "madlads", "bonk_inu", "magiceden",
    "superteam", "solana_devs", "metaplex", "solendprotocol",
    "driftprotocol", "solblaze_org", "sanctumso",
    # Founders / KOLs
    "aeyakovenko", "rajgokal", "0xmert_", "armaniferrante",
}

# Scam/spam phrase patterns (compiled once)
SCAM_PHRASES = [
    r"free\s+airdrop",
    r"claim\s+(now|your|free|here)",
    r"connect\s+(your\s+)?wallet",
    r"send\s+\d+\s*(sol|eth|btc)",
    r"guaranteed\s+(return|profit|gain)",
    r"\d+x\s+guaranteed",
    r"100%\s+(safe|guaranteed|profit)",
    r"whitelist\s+spot.{0,20}(free|claim|hurry)",
    r"(first|next)\s+\d+\s+people",
    r"dm\s+(me|us)\s+to\s+(claim|get|receive)",
    r"limited\s+time.{0,20}(claim|free|airdrop)",
    r"act\s+(now|fast|quick)",
    r"don'?t\s+miss\s+(this|out)",
]
_SCAM_RE = [re.compile(p, re.IGNORECASE) for p in SCAM_PHRASES]

ENGAGEMENT_FARMING_PATTERNS = [
    r"like\s*(\+|and|&)\s*r(t|etweet)\s*(to\s+win|for\s+a\s+chance)",
    r"follow\s*(\+|and|&)\s*(like|rt|retweet)",
    r"tag\s+\d+\s+friends",
    r"retweet\s+to\s+(win|enter|claim)",
    r"giveaway.{0,30}(follow|like|rt)",
]
_FARMING_RE = [re.compile(p, re.IGNORECASE) for p in ENGAGEMENT_FARMING_PATTERNS]

# Suspicious shortened URL domains
SUSPICIOUS_DOMAINS = {
    "bit.ly", "t.co", "tinyurl.com", "ow.ly", "is.gd", "buff.ly",
    "goo.gl", "rb.gy", "shorturl.at", "cutt.ly",
}

# Known phishing TLD patterns
PHISHING_TLD_RE = re.compile(r'https?://[^/]*\.(xyz|top|icu|buzz|tk|ml|ga|cf|gq|pw|click|link|monster|rest|hair|cfd|sbs)\b', re.IGNORECASE)


def compute_confidence(signal: Dict) -> int:
    """Compute a 0-100 confidence score for a social signal.
    
    Higher = more likely legitimate. Returns the score.
    """
    source = signal.get("source", "")
    
    # Non-twitter sources get a default high confidence
    if source not in ("twitter", "twitter_nitter", "twitter_syndication"):
        return 80
    
    score = 50  # Start at neutral
    content = signal.get("content", "")
    content_lower = content.lower()
    author = signal.get("author", "").lower()
    
    # === Account credibility ===
    score += _account_score(signal)
    
    # === Content analysis ===
    score += _content_score(content, content_lower)
    
    # === Engagement sanity ===
    score += _engagement_score(signal)
    
    # === Official account bonus ===
    if author in OFFICIAL_ACCOUNTS:
        score += 25
    
    return max(0, min(100, score))


def _account_score(signal: Dict) -> int:
    """Score based on account metadata. Returns adjustment (-30 to +20)."""
    adj = 0
    author = signal.get("author", "").lower()
    
    followers = signal.get("followers", 0)
    following = signal.get("following", 0)
    verified = signal.get("verified", False)
    account_age_days = signal.get("account_age_days", None)
    
    # Verified accounts
    if verified:
        adj += 10
    
    # Follower count tiers
    if followers >= 10000:
        adj += 15
    elif followers >= 1000:
        adj += 8
    elif followers >= 100:
        adj += 2
    elif followers > 0 and followers < 50:
        adj -= 10  # Very low follower count is suspicious
    
    # Follower/following ratio (bots often follow many, have few followers)
    if following > 0 and followers > 0:
        ratio = followers / following
        if ratio < 0.1 and following > 500:
            adj -= 15  # Following way more than followers — bot pattern
        elif ratio > 2:
            adj += 5  # Healthy ratio
    
    # New accounts are suspicious
    if account_age_days is not None:
        if account_age_days < 30:
            adj -= 20
        elif account_age_days < 90:
            adj -= 10
        elif account_age_days > 365:
            adj += 5
    
    # Username patterns common in scam bots (e.g., random numbers at end)
    if re.search(r'\d{5,}$', author):
        adj -= 10
    if re.search(r'^[a-z]{1,3}\d{4,}', author):
        adj -= 10
    
    return adj


def _content_score(content: str, content_lower: str) -> int:
    """Score based on content analysis. Returns adjustment (-40 to +15)."""
    adj = 0
    
    # Scam phrase detection
    scam_hits = sum(1 for r in _SCAM_RE if r.search(content_lower))
    if scam_hits >= 2:
        adj -= 40  # Multiple scam phrases = almost certainly scam
    elif scam_hits == 1:
        adj -= 20
    
    # Engagement farming
    farming_hits = sum(1 for r in _FARMING_RE if r.search(content_lower))
    if farming_hits > 0:
        adj -= 25
    
    # Suspicious links
    urls = re.findall(r'https?://([^/\s]+)', content)
    for domain in urls:
        domain_lower = domain.lower()
        # Check shortened URLs
        if any(d in domain_lower for d in SUSPICIOUS_DOMAINS):
            adj -= 10
        # Check phishing TLDs
        if PHISHING_TLD_RE.search(f"https://{domain_lower}"):
            adj -= 15
    
    # Excessive caps (shouting = often scam/hype)
    if len(content) > 20:
        caps_ratio = sum(1 for c in content if c.isupper()) / len(content)
        if caps_ratio > 0.6:
            adj -= 10
    
    # Excessive emojis (common in scam tweets)
    emoji_count = len(re.findall(r'[\U0001F600-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FA6F]', content))
    if emoji_count > 8:
        adj -= 10
    
    # Substantive content bonus
    word_count = len(content.split())
    if word_count > 30:
        adj += 10  # Longer, more detailed content
    elif word_count > 15:
        adj += 5
    
    # Technical/substantive language bonus
    technical_terms = ["tvl", "protocol", "governance", "validator", "staking",
                       "liquidity", "integration", "deployed", "mainnet", "testnet",
                       "upgrade", "proposal", "audit", "open source"]
    tech_hits = sum(1 for t in technical_terms if t in content_lower)
    if tech_hits >= 2:
        adj += 10
    elif tech_hits == 1:
        adj += 5
    
    return adj


def _engagement_score(signal: Dict) -> int:
    """Score based on engagement patterns. Returns adjustment (-10 to +10)."""
    adj = 0
    likes = signal.get("likes", 0)
    retweets = signal.get("retweets", 0)
    replies = signal.get("replies", 0)
    
    # High engagement = likely legitimate
    total = likes + retweets + replies
    if total > 100:
        adj += 10
    elif total > 20:
        adj += 5
    
    # Suspicious ratio: many retweets but few likes (bot amplification)
    if retweets > 50 and likes > 0 and retweets / likes > 5:
        adj -= 10
    
    return adj


def verify_signals(signals: List[Dict]) -> List[Dict]:
    """Add confidence scores to all signals. Modifies signals in-place and returns them."""
    for signal in signals:
        signal["confidence_score"] = compute_confidence(signal)
    
    verified = len([s for s in signals if s["confidence_score"] >= 30])
    filtered = len(signals) - verified
    logger.info("Tweet verification: %d signals scored, %d above threshold, %d filtered",
                len(signals), verified, filtered)
    
    return signals


def filter_low_confidence(signals: List[Dict], threshold: int = 30) -> List[Dict]:
    """Remove signals below the confidence threshold."""
    return [s for s in signals if s.get("confidence_score", 80) >= threshold]
