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
