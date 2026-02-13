"""Tests for the persistent narrative store."""
import pytest
from engine.narrative_store import (
    _canonical, _word_overlap, find_match, merge_narratives,
    get_active_narratives, get_recently_faded, get_active_narrative_hints,
    store_entry_to_api, _dedup_signals, load_store,
)
from datetime import datetime, timezone, timedelta


class TestCanonical:
    def test_basic(self):
        assert _canonical("AI-Powered Trading Bots") == "ai trading bots"

    def test_removes_stop_words(self):
        assert _canonical("The Rise of Liquid Staking on Solana") == "rise liquid staking"

    def test_empty(self):
        assert _canonical("") == ""


class TestWordOverlap:
    def test_identical(self):
        assert _word_overlap("ai trading bots", "ai trading bots") == 1.0

    def test_partial(self):
        # "ai trading bots" vs "ai enhanced trading" -> overlap: {ai, trading} = 2, min(3,3)=3 -> 0.67
        assert _word_overlap("ai trading bots", "ai enhanced trading") > 0.5

    def test_no_overlap(self):
        assert _word_overlap("liquid staking", "meme coins") == 0.0

    def test_empty(self):
        assert _word_overlap("", "something") == 0.0


class TestFindMatch:
    def test_finds_match(self):
        store = {"narratives": {
            "abc": {"canonical_name": "ai trading bots"},
            "def": {"canonical_name": "liquid staking expansion"},
        }}
        assert find_match("ai enhanced trading bots", store) == "abc"

    def test_no_match(self):
        store = {"narratives": {
            "abc": {"canonical_name": "ai trading bots"},
        }}
        assert find_match("liquid staking expansion", store) is None


class TestMergeNarratives:
    def _make_narrative(self, name, confidence="HIGH", signals=None):
        return {
            "name": name,
            "confidence": confidence,
            "direction": "ACCELERATING",
            "explanation": f"Explanation for {name}",
            "trend_evidence": "",
            "market_opportunity": "",
            "topics": ["defi"],
            "supporting_signals": signals or [{"text": "sig1", "url": "https://example.com/1", "source": "twitter"}],
            "ideas": [],
            "references": [],
        }

    def test_new_narrative_created(self):
        store = {"narratives": {}, "total_pipeline_runs": 0}
        store = merge_narratives([self._make_narrative("AI Trading Bots")], store)
        assert len(store["narratives"]) == 1
        entry = list(store["narratives"].values())[0]
        assert entry["name"] == "AI Trading Bots"
        assert entry["detection_count"] == 1
        assert entry["status"] == "ACTIVE"

    def test_existing_narrative_matched(self):
        store = {"narratives": {}, "total_pipeline_runs": 0}
        store = merge_narratives([self._make_narrative("AI Trading Bots")], store)
        # Second run with slightly different name
        store = merge_narratives([self._make_narrative("AI-Powered Trading Bots")], store)
        assert len(store["narratives"]) == 1
        entry = list(store["narratives"].values())[0]
        assert entry["detection_count"] == 2
        assert entry["name"] == "AI-Powered Trading Bots"  # updated to latest

    def test_signals_accumulate(self):
        store = {"narratives": {}, "total_pipeline_runs": 0}
        store = merge_narratives([self._make_narrative("AI Bots", signals=[
            {"text": "s1", "url": "https://a.com", "source": "twitter"}
        ])], store)
        store = merge_narratives([self._make_narrative("AI Bots", signals=[
            {"text": "s2", "url": "https://b.com", "source": "github"}
        ])], store)
        entry = list(store["narratives"].values())[0]
        assert len(entry["all_signals"]) == 2

    def test_signals_dedup_by_url(self):
        store = {"narratives": {}, "total_pipeline_runs": 0}
        store = merge_narratives([self._make_narrative("AI Bots", signals=[
            {"text": "s1", "url": "https://a.com", "source": "twitter"}
        ])], store)
        store = merge_narratives([self._make_narrative("AI Bots", signals=[
            {"text": "s1 updated", "url": "https://a.com", "source": "twitter"}
        ])], store)
        entry = list(store["narratives"].values())[0]
        assert len(entry["all_signals"]) == 1

    def test_missed_count_increments(self):
        store = {"narratives": {}, "total_pipeline_runs": 0}
        store = merge_narratives([self._make_narrative("AI Bots")], store)
        # Run with different narrative
        store = merge_narratives([self._make_narrative("Liquid Staking")], store)
        ai_entry = [e for e in store["narratives"].values() if "ai" in e["canonical_name"]][0]
        assert ai_entry["missed_count"] == 1
        assert ai_entry["status"] == "ACTIVE"  # not faded yet

    def test_fades_after_3_misses(self):
        store = {"narratives": {}, "total_pipeline_runs": 0}
        store = merge_narratives([self._make_narrative("AI Bots")], store)
        for _ in range(3):
            store = merge_narratives([self._make_narrative("Liquid Staking")], store)
        ai_entry = [e for e in store["narratives"].values() if "ai" in e["canonical_name"]][0]
        assert ai_entry["status"] == "FADED"

    def test_reactivates_on_redetection(self):
        store = {"narratives": {}, "total_pipeline_runs": 0}
        store = merge_narratives([self._make_narrative("AI Bots")], store)
        for _ in range(3):
            store = merge_narratives([self._make_narrative("Liquid Staking")], store)
        # Re-detect AI Bots
        store = merge_narratives([self._make_narrative("AI Bots")], store)
        ai_entry = [e for e in store["narratives"].values() if "ai" in e["canonical_name"]][0]
        assert ai_entry["status"] == "ACTIVE"
        assert ai_entry["missed_count"] == 0


class TestGetActiveNarratives:
    def test_sorted_by_confidence(self):
        store = {"narratives": {
            "a": {"status": "ACTIVE", "current_confidence": "LOW", "detection_count": 5},
            "b": {"status": "ACTIVE", "current_confidence": "HIGH", "detection_count": 1},
            "c": {"status": "FADED", "current_confidence": "HIGH", "detection_count": 10},
        }}
        active = get_active_narratives(store)
        assert len(active) == 2
        assert active[0]["current_confidence"] == "HIGH"


class TestDedupSignals:
    def test_caps_at_limit(self):
        signals = [{"url": f"https://x.com/{i}", "score": i} for i in range(50)]
        result = _dedup_signals(signals, cap=30)
        assert len(result) == 30

    def test_dedup_by_url(self):
        signals = [
            {"url": "https://x.com/1", "score": 10},
            {"url": "https://x.com/1", "score": 20},
        ]
        result = _dedup_signals(signals)
        assert len(result) == 1
        assert result[0]["score"] == 20


class TestStoreEntryToApi:
    def test_converts(self):
        entry = {
            "name": "Test",
            "current_confidence": "HIGH",
            "current_direction": "ACCELERATING",
            "explanation": "test",
            "trend_evidence": "",
            "market_opportunity": "",
            "topics": [],
            "all_signals": [{"text": "s"}],
            "ideas": [],
            "references": [],
            "status": "ACTIVE",
            "first_detected": "2026-01-01T00:00:00Z",
            "last_detected": "2026-01-01T00:00:00Z",
            "detection_count": 3,
        }
        api = store_entry_to_api(entry)
        assert api["confidence"] == "HIGH"
        assert api["detection_count"] == 3
        assert len(api["supporting_signals"]) == 1


class TestGetActiveNarrativeHints:
    def test_generates_hints(self):
        now = datetime.now(timezone.utc).isoformat()
        store = {"narratives": {
            "a": {"name": "AI Bots", "status": "ACTIVE", "detection_count": 3, "last_detected": now},
        }}
        hints = get_active_narrative_hints(store)
        assert len(hints) == 1
        assert "AI Bots" in hints[0]
        assert "detected 3 times" in hints[0]
