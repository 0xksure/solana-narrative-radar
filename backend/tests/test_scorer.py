"""Tests for the signal scoring engine"""
import pytest
from engine.scorer import score_signals, extract_topics, calculate_velocity, calculate_authority, calculate_novelty


class TestExtractTopics:
    def test_defi_keywords(self):
        signal = {"name": "New DeFi lending protocol", "content": "AMM with yield farming"}
        topics = extract_topics(signal)
        assert "defi" in topics
    
    def test_ai_agents(self):
        signal = {"name": "AI agent framework", "content": "autonomous LLM-powered agent"}
        topics = extract_topics(signal)
        assert "ai_agents" in topics
    
    def test_multiple_topics(self):
        signal = {"name": "AI agent for DeFi trading", "content": "autonomous swap agent"}
        topics = extract_topics(signal)
        assert "ai_agents" in topics
        assert "defi" in topics or "trading" in topics
    
    def test_no_match_returns_other(self):
        signal = {"name": "Random project", "content": "nothing relevant"}
        topics = extract_topics(signal)
        assert topics == ["other"]
    
    def test_empty_signal(self):
        topics = extract_topics({})
        assert topics == ["other"]


class TestCalculateVelocity:
    def test_high_star_github(self):
        signal = {"source": "github", "stars": 200}
        score = calculate_velocity(signal)
        assert score >= 70
    
    def test_high_tvl_change(self):
        signal = {"source": "defillama", "change_7d": 60}
        score = calculate_velocity(signal)
        assert score >= 80
    
    def test_trending_token(self):
        signal = {"source": "birdeye", "signal_type": "token_trending"}
        score = calculate_velocity(signal)
        assert score >= 70
    
    def test_kol_tweet_with_engagement(self):
        signal = {"source": "twitter", "signal_type": "kol_tweet", "engagement": 150}
        score = calculate_velocity(signal)
        assert score >= 80
    
    def test_baseline(self):
        signal = {"source": "unknown"}
        score = calculate_velocity(signal)
        assert score == 50


class TestCalculateAuthority:
    def test_onchain_high_authority(self):
        signal = {"source": "solana_rpc"}
        score = calculate_authority(signal)
        assert score >= 80
    
    def test_kol_tweet(self):
        signal = {"source": "twitter", "signal_type": "kol_tweet"}
        score = calculate_authority(signal)
        assert score >= 75
    
    def test_high_star_repo(self):
        signal = {"source": "github", "stars": 1000}
        score = calculate_authority(signal)
        assert score >= 85


class TestScoreSignals:
    def test_sorts_by_score_descending(self):
        signals = [
            {"source": "github", "name": "low", "stars": 1},
            {"source": "github", "name": "high", "stars": 500},
        ]
        scored = score_signals(signals)
        assert scored[0]["name"] == "high"
        assert scored[0]["score"] > scored[1]["score"]
    
    def test_adds_score_breakdown(self):
        signals = [{"source": "github", "name": "test", "stars": 10}]
        scored = score_signals(signals)
        assert "score_breakdown" in scored[0]
        assert "velocity" in scored[0]["score_breakdown"]
        assert "convergence" in scored[0]["score_breakdown"]
    
    def test_empty_input(self):
        assert score_signals([]) == []


class TestCalculateNovelty:
    def test_new_repo_bonus(self):
        signal = {"signal_type": "new_repo"}
        score = calculate_novelty(signal)
        assert score > 50
