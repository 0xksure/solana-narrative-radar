"""LLM-powered narrative detection and idea generation"""
import os
import json
from typing import List, Dict
from anthropic import Anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

def cluster_narratives(scored_signals: List[Dict]) -> Dict:
    """Use Claude to cluster signals into narratives"""
    
    # Take top signals (>40 score) for analysis
    top_signals = [s for s in scored_signals if s.get("score", 0) > 40][:50]
    
    if not top_signals:
        return {"narratives": [], "meta": {"signal_count": 0}}
    
    if not ANTHROPIC_API_KEY:
        print("⚠️ No Anthropic API key, using rule-based fallback")
        return _fallback_clustering(top_signals)
    
    # Format signals for the LLM
    signal_summary = format_signals_for_llm(top_signals)
    
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": f"""You are an expert Solana ecosystem analyst. Analyze these signals collected from the Solana ecosystem over the past 2 weeks and identify emerging narratives.

SIGNALS:
{signal_summary}

For each narrative you detect:
1. Give it a clear, concise name
2. Confidence level: HIGH, MEDIUM, or LOW
3. A 2-3 sentence explanation of why this narrative is emerging NOW
4. List the supporting signals (reference specific data points)
5. Trend direction: ACCELERATING, EMERGING, or STABILIZING

Identify 3-7 narratives. Prioritize NOVELTY and SIGNAL QUALITY over volume. Only include narratives with real supporting evidence.

For each supporting signal's "comment" field, explain the SIGNIFICANCE — why this data point matters for the narrative. Examples:
- GitHub repo with rapid star growth → "Rapid star growth indicates strong developer interest in this approach"
- KOL tweet with high engagement → "High engagement from ecosystem leader suggests mainstream awareness"
- TVL spike → "Capital flowing in validates real user demand, not just hype"
- Active Reddit discussion → "Active community debate signals this narrative has legs beyond speculation"

Respond in JSON format:
{{
  "narratives": [
    {{
      "name": "Narrative Name",
      "confidence": "HIGH|MEDIUM|LOW",
      "direction": "ACCELERATING|EMERGING|STABILIZING",
      "explanation": "2-3 sentences on WHY this narrative is emerging now and why it matters for builders. Go beyond signal counts — explain the underlying market dynamics, user demand, and technical catalysts driving this trend.",
      "market_opportunity": "2-3 sentences on the TAM/market size and why this narrative represents a real opportunity for builders and investors.",
      "references": ["https://relevant-protocol.com", "https://docs.example.com/relevant-page"],
      "supporting_signals": [{"text": "signal description", "url": "https://...", "source": "twitter|github|defillama|reddit|onchain", "comment": "1-2 sentence explanation of why this signal matters for the narrative and what it indicates about the trend"}],
      "topics": ["defi", "ai_agents"]
    }}
  ]
}}

For "references", include relevant links you know about: protocol websites, documentation pages, notable tweets/articles, or ecosystem resources related to the narrative."""
        }]
    )
    
    try:
        # Parse JSON from response
        text = response.content[0].text
        # Find JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            result["meta"] = {
                "signal_count": len(top_signals),
                "model": "claude-sonnet-4-20250514",
            }
            return result
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Failed to parse LLM response: {e}")
    
    return {"narratives": [], "meta": {"error": "Failed to parse response"}}


def generate_ideas(narratives: List[Dict]) -> List[Dict]:
    """Generate build ideas for each narrative"""
    
    if not narratives:
        return []
    
    if not ANTHROPIC_API_KEY:
        print("⚠️ No Anthropic API key, using fallback ideas")
        for n in narratives:
            n["ideas"] = _fallback_ideas(n)
        return narratives
    
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    enriched = []
    for narrative in narratives:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"""You are a Solana product strategist. Given this emerging narrative in the Solana ecosystem, generate 3-5 concrete product ideas.

NARRATIVE: {narrative['name']}
EXPLANATION: {narrative['explanation']}
CONFIDENCE: {narrative['confidence']}
DIRECTION: {narrative['direction']}

For each idea:
1. Product name (catchy, memorable)
2. Description: 2-3 sentences explaining what this product does, the core value proposition, and how it leverages the narrative
3. Target user (specific, not generic)
4. Key Solana protocols/tools to integrate
5. Build complexity: DAYS (weekend hack), WEEKS (MVP), MONTHS (full product)
6. Why this wins: what makes it compelling
7. Market analysis: 2-3 sentences on market size, existing competition, and how this product differentiates
8. Revenue model: how this product makes money (fees, subscriptions, token, etc.)
9. Reference links: URLs of existing similar products or inspirations
10. Key metrics: 3-5 quantified metrics with context (addressable market size, competition count, time to market, user base estimate, etc.)

Respond in JSON:
{{
  "ideas": [
    {{
      "name": "Product Name",
      "description": "2-3 sentence description of the product, its value proposition, and how it leverages the narrative.",
      "target_user": "Specific user persona",
      "solana_integrations": ["Jupiter", "Helius"],
      "complexity": "DAYS|WEEKS|MONTHS",
      "why_it_wins": "Compelling reason",
      "market_analysis": "2-3 sentences on market size, competition landscape, and differentiation strategy.",
      "revenue_model": "How this product generates revenue.",
      "reference_links": ["https://similar-product.com", "https://inspiration.xyz"],
      "key_metrics": [
        {{"label": "Addressable Market", "value": "$X", "context": "Brief context on market size"}},
        {{"label": "Competition", "value": "N competitors", "context": "Competitive landscape summary"}},
        {{"label": "Time to Market", "value": "X weeks", "context": "What enables this timeline"}}
      ]
    }}
  ]
}}"""
            }]
        )
        
        try:
            text = response.content[0].text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                ideas_data = json.loads(text[start:end])
                narrative["ideas"] = ideas_data.get("ideas", [])
            else:
                narrative["ideas"] = []
        except Exception as e:
            print(f"Failed to generate ideas for {narrative['name']}: {e}")
            narrative["ideas"] = []
        
        enriched.append(narrative)
    
    return enriched


def format_signals_for_llm(signals: List[Dict]) -> str:
    """Format signals into a readable summary for the LLM"""
    sections = {"github": [], "defillama": [], "social": [], "onchain": [], "other": []}
    
    for s in signals:
        source = s.get("source", "other")
        
        url_suffix = f" | URL: {s.get('url')}" if s.get("url") else ""
        
        if source == "github":
            forks = s.get('forks', 0)
            created = s.get('created_at', '')
            lang = s.get('language', '')
            extra = []
            if forks:
                extra.append(f"forks: {forks}")
            if created:
                extra.append(f"created: {created[:10]}")
            if lang:
                extra.append(f"lang: {lang}")
            extra_str = f", {', '.join(extra)}" if extra else ""
            sections["github"].append(
                f"- [{s.get('signal_type')}] {s.get('name')}: {s.get('description', 'N/A')} "
                f"(⭐{s.get('stars', 0)}{extra_str}, topics: {s.get('topics', [])}, score: {s.get('score', 0)}){url_suffix}"
            )
        elif source in ("defillama", "defillama_yields"):
            change_1d = s.get('change_1d', 0)
            change_30d = s.get('change_30d', 0)
            apy = s.get('apy', 0)
            extra = []
            if change_1d:
                extra.append(f"1d: {change_1d:+.1f}%")
            if change_30d:
                extra.append(f"30d: {change_30d:+.1f}%")
            if apy:
                extra.append(f"APY: {apy:.1f}%")
            extra_str = f", {', '.join(extra)}" if extra else ""
            sections["defillama"].append(
                f"- {s.get('name')}: TVL ${s.get('tvl', 0):,.0f}, "
                f"7d change: {s.get('change_7d', 0):+.1f}%{extra_str}, category: {s.get('category', 'N/A')}{url_suffix}"
            )
        elif source in ("twitter", "twitter_nitter", "twitter_syndication", "reddit"):
            engagement = []
            for key in ('likes', 'retweets', 'replies', 'comments', 'upvotes', 'score'):
                val = s.get(key, 0)
                if val:
                    engagement.append(f"{key}: {val}")
            eng_str = f" ({', '.join(engagement)})" if engagement else ""
            author = s.get('author', '')
            author_str = f" by @{author}" if author else ""
            sections["social"].append(
                f"- [{source}/{s.get('signal_type')}]{author_str} {s.get('content', s.get('name', ''))[:200]}{eng_str}{url_suffix}"
            )
        elif source in ("solana_rpc", "birdeye", "solscan", "solanafm"):
            volume = s.get('volume', 0)
            price_change = s.get('price_change', 0)
            extra = []
            if volume:
                extra.append(f"vol: ${volume:,.0f}")
            if price_change:
                extra.append(f"price: {price_change:+.1f}%")
            extra_str = f" ({', '.join(extra)})" if extra else ""
            sections["onchain"].append(
                f"- [{source}] {s.get('name', '')}: {s.get('content', '')[:150]}{extra_str}{url_suffix}"
            )
        else:
            sections["other"].append(
                f"- [{source}] {s.get('name', '')[:100]} (score: {s.get('score', 0)}){url_suffix}"
            )
    
    output = ""
    if sections["github"]:
        output += "DEVELOPER ACTIVITY (GitHub):\n" + "\n".join(sections["github"][:20]) + "\n\n"
    if sections["defillama"]:
        output += "DEFI/TVL DATA:\n" + "\n".join(sections["defillama"][:20]) + "\n\n"
    if sections["social"]:
        output += "SOCIAL SIGNALS (Twitter/Reddit):\n" + "\n".join(sections["social"][:15]) + "\n\n"
    if sections["onchain"]:
        output += "ON-CHAIN DATA (Solana):\n" + "\n".join(sections["onchain"][:10]) + "\n\n"
    if sections["other"]:
        output += "OTHER SIGNALS:\n" + "\n".join(sections["other"][:10]) + "\n\n"
    
    return output


def _fallback_clustering(signals: List[Dict]) -> Dict:
    """Advanced rule-based narrative clustering when no LLM is available.
    
    Uses multi-signal convergence analysis:
    1. Topic grouping with co-occurrence detection
    2. Source diversity scoring (narratives across multiple sources = stronger)
    3. Score-weighted momentum calculation
    4. Cross-topic narrative merging
    """
    from collections import Counter, defaultdict
    
    # Group by topic
    topic_signals = defaultdict(list)
    for s in signals:
        for t in s.get("topics", ["other"]):
            topic_signals[t].append(s)
    
    # Detect co-occurring topics (signals that span multiple topics indicate convergence)
    cooccurrence = Counter()
    for s in signals:
        topics = s.get("topics", [])
        for i, t1 in enumerate(topics):
            for t2 in topics[i+1:]:
                pair = tuple(sorted([t1, t2]))
                cooccurrence[pair] += 1
    
    # Calculate source diversity per topic (signals from multiple sources = stronger narrative)
    topic_source_diversity = {}
    for topic, sigs in topic_signals.items():
        sources = set(s.get("source", "unknown") for s in sigs)
        topic_source_diversity[topic] = len(sources)
    
    # Composite scoring: count × avg_score × source_diversity_bonus
    topic_scores = {}
    for topic, sigs in topic_signals.items():
        avg_score = sum(s.get("score", 0) for s in sigs) / len(sigs)
        diversity_bonus = 1.0 + (topic_source_diversity.get(topic, 1) - 1) * 0.2
        topic_scores[topic] = len(sigs) * avg_score * diversity_bonus
    
    sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
    
    narratives = []
    for topic, composite_score in sorted_topics[:7]:
        sigs = topic_signals[topic]
        top_sigs = sorted(sigs, key=lambda x: x.get("score", 0), reverse=True)[:5]
        
        # Source diversity analysis
        sources = set(s.get("source", "unknown") for s in sigs)
        source_count = len(sources)
        
        # Confidence based on signal count AND source diversity
        if len(sigs) > 15 and source_count >= 3:
            confidence = "HIGH"
        elif len(sigs) > 8 or (len(sigs) > 5 and source_count >= 2):
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        
        # Direction based on score distribution
        high_score_ratio = len([s for s in sigs if s.get("score", 0) > 60]) / max(len(sigs), 1)
        if high_score_ratio > 0.3 and len(sigs) > 10:
            direction = "ACCELERATING"
        elif high_score_ratio > 0.15 or len(sigs) > 5:
            direction = "EMERGING"
        else:
            direction = "STABILIZING"
        
        # Build explanation with source breakdown
        source_breakdown = Counter(s.get("source", "unknown") for s in sigs)
        source_desc = ", ".join(f"{count} from {src}" for src, count in source_breakdown.most_common(3))
        
        # Find co-occurring topics for richer narrative description
        related_topics = []
        for pair, count in cooccurrence.most_common(10):
            if topic in pair and count >= 2:
                other = pair[0] if pair[1] == topic else pair[1]
                related_topics.append(other)
        
        explanation = f"Detected {len(sigs)} signals across {source_count} data sources ({source_desc}). "
        if related_topics:
            explanation += f"Converges with {', '.join(related_topics[:2])} narratives. "
        explanation += f"Top signals: " + ", ".join(s.get("name", "unknown")[:50] for s in top_sigs[:3])
        
        narratives.append({
            "name": topic.replace("_", " ").title(),
            "confidence": confidence,
            "direction": direction,
            "explanation": explanation,
            "market_opportunity": f"The {topic.replace('_', ' ')} sector on Solana is growing with {len(sigs)} active signals detected. This represents an emerging opportunity as developer and user activity converges around this narrative.",
            "references": [],
            "supporting_signals": [
                {
                    "text": s.get("name", ""),
                    "url": s.get("url", ""),
                    "source": s.get("source", ""),
                    "comment": f"Score {s.get('score', 0)} signal from {s.get('source', 'unknown')} — indicates active development in this area"
                }
                for s in top_sigs
            ],
            "topics": [topic] + related_topics[:2],
            "source_diversity": source_count,
            "ideas": []
        })
    
    return {
        "narratives": narratives,
        "meta": {
            "signal_count": len(signals),
            "method": "multi-signal-convergence",
            "co_occurrences_detected": len(cooccurrence)
        }
    }


def _fallback_ideas(narrative: Dict) -> List[Dict]:
    """Generate basic ideas without LLM"""
    topic = narrative.get("topics", ["other"])[0]
    
    _default_extra = {
        "market_analysis": "Market size and competition analysis not available in fallback mode. Run with LLM for detailed analysis.",
        "revenue_model": "Revenue model analysis not available in fallback mode.",
        "reference_links": [],
        "key_metrics": [
            {"label": "Addressable Market", "value": "TBD", "context": "Requires LLM analysis for estimation"},
            {"label": "Competition", "value": "TBD", "context": "Requires LLM analysis"},
            {"label": "Time to Market", "value": "TBD", "context": "See complexity field for estimate"},
        ],
    }

    idea_templates = {
        "ai_agents": [
            {"name": "AgentScope", "description": "Real-time monitoring dashboard for AI agent activity on Solana. Track agent transactions, spending patterns, and performance metrics across protocols. Essential tooling as autonomous agents become key DeFi participants.", "complexity": "WEEKS", **_default_extra},
            {"name": "AgentPay", "description": "Micropayment rails for agent-to-agent transactions on Solana. Enables seamless value transfer between autonomous agents with built-in escrow and verification. Leverages Solana's low fees for high-frequency micro-transfers.", "complexity": "WEEKS", **_default_extra},
            {"name": "SafeAgent", "description": "Guardrails and spending limits for autonomous Solana agents. Set transaction caps, whitelist protocols, and monitor agent behavior in real-time. Critical safety infrastructure as AI agents manage increasing capital.", "complexity": "DAYS", **_default_extra},
        ],
        "defi": [
            {"name": "YieldRadar", "description": "Cross-protocol yield optimization for Solana DeFi. Automatically discovers and ranks the best yield opportunities across lending, LP, and staking protocols. Provides risk-adjusted recommendations tailored to portfolio size.", "complexity": "WEEKS", **_default_extra},
            {"name": "DeFi Sentinel", "description": "Real-time risk monitoring across Solana lending protocols. Alerts users to liquidation risks, utilization spikes, and oracle anomalies before they impact positions. Essential risk management for serious DeFi users.", "complexity": "WEEKS", **_default_extra},
            {"name": "PositionPilot", "description": "Automated position management across Jupiter, Kamino, Drift. Rebalances, compounds, and hedges positions based on configurable strategies. Set-and-forget DeFi management for power users.", "complexity": "MONTHS", **_default_extra},
        ],
        "trading": [
            {"name": "AlphaTracker", "description": "Copy-trade smart money wallets with risk controls on Solana. Identifies profitable wallets, mirrors their trades with customizable position sizing, and includes automatic stop-losses. Democratizes alpha access for retail traders.", "complexity": "WEEKS", **_default_extra},
            {"name": "SignalBot", "description": "AI-powered trading signals from on-chain patterns on Solana. Analyzes token flows, whale movements, and DEX activity to generate actionable trade alerts. Integrates with Jupiter for one-click execution.", "complexity": "WEEKS", **_default_extra},
        ],
        "infrastructure": [
            {"name": "DevPulse", "description": "Developer activity dashboard for Solana ecosystem. Tracks GitHub commits, new programs deployed, and SDK adoption across the ecosystem. Helps investors and builders identify where developer momentum is concentrating.", "complexity": "DAYS", **_default_extra},
            {"name": "RPCBench", "description": "RPC provider comparison and benchmarking tool for Solana. Continuously tests latency, reliability, and feature support across providers. Helps developers pick the best infrastructure for their use case.", "complexity": "DAYS", **_default_extra},
        ],
        "memecoins": [
            {"name": "MemeScout", "description": "Early detection of memecoin narratives before they pump on Solana. Monitors social signals, token creation patterns, and early whale accumulation. Provides risk scores and narrative strength indicators.", "complexity": "DAYS", **_default_extra},
            {"name": "FairLaunchGuard", "description": "Rug-pull detection and safety scoring for new Solana tokens. Analyzes contract code, liquidity locks, team wallets, and social signals to rate token safety. Protects retail users from common scam patterns.", "complexity": "WEEKS", **_default_extra},
        ],
    }
    
    return idea_templates.get(topic, [
        {"name": f"{topic.title()}Builder", "description": f"Tool for the emerging {topic} narrative on Solana. Addresses a growing need in the ecosystem as this narrative gains momentum. Build early to capture first-mover advantage.", "complexity": "WEEKS", **_default_extra}
    ])
