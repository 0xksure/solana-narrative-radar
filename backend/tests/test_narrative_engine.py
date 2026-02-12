"""Tests for the narrative clustering engine"""
import pytest
from engine.narrative_engine import _fallback_clustering, _fallback_ideas


class TestFallbackClustering:
    def _make_signals(self, topics_list, source="github"):
        """Helper to create test signals"""
        return [
            {"name": f"signal-{i}", "topics": topics, "score": 60, "source": source}
            for i, topics in enumerate(topics_list)
        ]
    
    def test_groups_by_topic(self):
        signals = self._make_signals([["defi"]] * 10 + [["ai_agents"]] * 5)
        result = _fallback_clustering(signals)
        names = [n["name"] for n in result["narratives"]]
        assert "Defi" in names
        assert "Ai Agents" in names
    
    def test_high_confidence_requires_many_signals(self):
        signals = self._make_signals([["defi"]] * 20, "github") + \
                  self._make_signals([["defi"]] * 5, "defillama") + \
                  self._make_signals([["defi"]] * 3, "reddit")
        result = _fallback_clustering(signals)
        defi = next(n for n in result["narratives"] if n["name"] == "Defi")
        assert defi["confidence"] == "HIGH"
    
    def test_low_confidence_for_few_signals(self):
        signals = self._make_signals([["rwa"]] * 3)
        result = _fallback_clustering(signals)
        rwa = next(n for n in result["narratives"] if n["name"] == "Rwa")
        assert rwa["confidence"] == "LOW"
    
    def test_max_seven_narratives(self):
        topics = ["defi", "ai_agents", "trading", "nft", "gaming", "staking", "bridge", "rwa", "privacy"]
        signals = []
        for t in topics:
            signals.extend(self._make_signals([[t]] * 5))
        result = _fallback_clustering(signals)
        assert len(result["narratives"]) <= 7
    
    def test_source_diversity_tracked(self):
        signals = self._make_signals([["defi"]] * 5, "github") + \
                  self._make_signals([["defi"]] * 5, "defillama")
        result = _fallback_clustering(signals)
        defi = next(n for n in result["narratives"] if n["name"] == "Defi")
        assert defi.get("source_diversity", 0) >= 2
    
    def test_co_occurrence_detection(self):
        # Signals with multiple topics should create co-occurrences
        signals = self._make_signals([["defi", "ai_agents"]] * 5)
        result = _fallback_clustering(signals)
        assert result["meta"]["co_occurrences_detected"] > 0
    
    def test_empty_signals(self):
        result = _fallback_clustering([])
        assert result["narratives"] == []
    
    def test_method_label(self):
        signals = self._make_signals([["defi"]] * 5)
        result = _fallback_clustering(signals)
        assert result["meta"]["method"] == "multi-signal-convergence"


class TestFallbackIdeas:
    def test_defi_ideas(self):
        narrative = {"name": "DeFi", "topics": ["defi"]}
        ideas = _fallback_ideas(narrative)
        assert len(ideas) > 0
        assert all("name" in idea for idea in ideas)
    
    def test_ai_agents_ideas(self):
        narrative = {"name": "AI Agents", "topics": ["ai_agents"]}
        ideas = _fallback_ideas(narrative)
        assert len(ideas) > 0
    
    def test_unknown_topic_gets_generic_idea(self):
        narrative = {"name": "Unknown", "topics": ["quantum_computing"]}
        ideas = _fallback_ideas(narrative)
        assert len(ideas) >= 1
