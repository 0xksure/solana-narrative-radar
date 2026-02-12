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

Respond in JSON format:
{{
  "narratives": [
    {{
      "name": "Narrative Name",
      "confidence": "HIGH|MEDIUM|LOW",
      "direction": "ACCELERATING|EMERGING|STABILIZING",
      "explanation": "Why this is happening now...",
      "supporting_signals": ["signal 1", "signal 2"],
      "topics": ["defi", "ai_agents"]
    }}
  ]
}}"""
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
2. One-line description
3. Target user (specific, not generic)
4. Key Solana protocols/tools to integrate
5. Build complexity: DAYS (weekend hack), WEEKS (MVP), MONTHS (full product)
6. Why this wins: what makes it compelling

Respond in JSON:
{{
  "ideas": [
    {{
      "name": "Product Name",
      "description": "One-line description",
      "target_user": "Specific user persona",
      "solana_integrations": ["Jupiter", "Helius"],
      "complexity": "DAYS|WEEKS|MONTHS",
      "why_it_wins": "Compelling reason"
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
    sections = {"github": [], "defillama": [], "twitter": [], "other": []}
    
    for s in signals:
        source = s.get("source", "other")
        if source not in sections:
            source = "other"
        
        if source == "github":
            sections["github"].append(
                f"- [{s.get('signal_type')}] {s.get('name')}: {s.get('description', 'N/A')} "
                f"(⭐{s.get('stars', 0)}, topics: {s.get('topics', [])}, score: {s.get('score', 0)})"
            )
        elif source == "defillama":
            sections["defillama"].append(
                f"- {s.get('name')}: TVL ${s.get('tvl', 0):,.0f}, "
                f"7d change: {s.get('change_7d', 0):+.1f}%, category: {s.get('category', 'N/A')}"
            )
        elif source == "twitter":
            sections["twitter"].append(
                f"- [{s.get('signal_type')}] {s.get('content', '')[:200]}"
            )
        else:
            sections["other"].append(f"- {s}")
    
    output = ""
    if sections["github"]:
        output += "DEVELOPER ACTIVITY (GitHub):\n" + "\n".join(sections["github"][:20]) + "\n\n"
    if sections["defillama"]:
        output += "DEFI/TVL DATA:\n" + "\n".join(sections["defillama"][:20]) + "\n\n"
    if sections["twitter"]:
        output += "SOCIAL SIGNALS (X/Twitter):\n" + "\n".join(sections["twitter"][:15]) + "\n\n"
    
    return output


def _fallback_clustering(signals: List[Dict]) -> Dict:
    """Rule-based narrative clustering when no LLM is available"""
    from collections import Counter, defaultdict
    
    # Group by topic
    topic_signals = defaultdict(list)
    for s in signals:
        for t in s.get("topics", ["other"]):
            topic_signals[t].append(s)
    
    # Sort topics by signal count * average score
    topic_scores = {}
    for topic, sigs in topic_signals.items():
        avg_score = sum(s.get("score", 0) for s in sigs) / len(sigs)
        topic_scores[topic] = len(sigs) * avg_score
    
    sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
    
    narratives = []
    for topic, composite_score in sorted_topics[:7]:
        sigs = topic_signals[topic]
        top_sigs = sorted(sigs, key=lambda x: x.get("score", 0), reverse=True)[:5]
        
        # Determine confidence based on signal count
        confidence = "HIGH" if len(sigs) > 15 else "MEDIUM" if len(sigs) > 5 else "LOW"
        
        narratives.append({
            "name": topic.replace("_", " ").title(),
            "confidence": confidence,
            "direction": "ACCELERATING" if len(sigs) > 10 else "EMERGING",
            "explanation": f"Detected {len(sigs)} signals related to {topic}. Top signals include: " + 
                          ", ".join(s.get("name", "unknown")[:40] for s in top_sigs[:3]),
            "supporting_signals": [s.get("name", "") for s in top_sigs],
            "topics": [topic],
            "ideas": []  # Will be filled by generate_ideas if LLM available
        })
    
    return {
        "narratives": narratives,
        "meta": {
            "signal_count": len(signals),
            "method": "rule-based-fallback"
        }
    }


def _fallback_ideas(narrative: Dict) -> List[Dict]:
    """Generate basic ideas without LLM"""
    topic = narrative.get("topics", ["other"])[0]
    
    idea_templates = {
        "ai_agents": [
            {"name": "AgentScope", "description": "Real-time monitoring dashboard for AI agent activity on Solana", "complexity": "WEEKS"},
            {"name": "AgentPay", "description": "Micropayment rails for agent-to-agent transactions", "complexity": "WEEKS"},
            {"name": "SafeAgent", "description": "Guardrails and spending limits for autonomous Solana agents", "complexity": "DAYS"},
        ],
        "defi": [
            {"name": "YieldRadar", "description": "Cross-protocol yield optimization for Solana DeFi", "complexity": "WEEKS"},
            {"name": "DeFi Sentinel", "description": "Real-time risk monitoring across Solana lending protocols", "complexity": "WEEKS"},
            {"name": "PositionPilot", "description": "Automated position management across Jupiter, Kamino, Drift", "complexity": "MONTHS"},
        ],
        "trading": [
            {"name": "AlphaTracker", "description": "Copy-trade smart money wallets with risk controls", "complexity": "WEEKS"},
            {"name": "SignalBot", "description": "AI-powered trading signals from on-chain patterns", "complexity": "WEEKS"},
        ],
        "infrastructure": [
            {"name": "DevPulse", "description": "Developer activity dashboard for Solana ecosystem", "complexity": "DAYS"},
            {"name": "RPCBench", "description": "RPC provider comparison and benchmarking tool", "complexity": "DAYS"},
        ],
        "memecoins": [
            {"name": "MemeScout", "description": "Early detection of memecoin narratives before they pump", "complexity": "DAYS"},
            {"name": "FairLaunchGuard", "description": "Rug-pull detection and safety scoring for new tokens", "complexity": "WEEKS"},
        ],
    }
    
    return idea_templates.get(topic, [
        {"name": f"{topic.title()}Builder", "description": f"Tool for the emerging {topic} narrative on Solana", "complexity": "WEEKS"}
    ])
