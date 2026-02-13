"""Tests for all collectors — mock external APIs, test parsing logic"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import json

# ── Social collector unit tests ──

from collectors.social_collector import (
    _parse_xbird_output,
    _is_solana_related,
    _extract_topics,
    _parse_rss_items,
)


class TestParseXbirdOutput:
    def test_basic_tweet(self):
        output = "@alice Hello world\n\n@bob Solana is great\n"
        tweets = _parse_xbird_output(output)
        assert len(tweets) == 2
        assert tweets[0]["author"] == "alice"
        assert tweets[1]["author"] == "bob"

    def test_multiline_tweet(self):
        output = "@alice First line\nSecond line\n\n"
        tweets = _parse_xbird_output(output)
        assert len(tweets) == 1
        assert "Second line" in tweets[0]["text"]

    def test_engagement_parsing(self):
        output = "@alice Great post 50 likes 10 retweets\n"
        tweets = _parse_xbird_output(output)
        assert tweets[0].get("likes") == 50
        assert tweets[0].get("retweets") == 10

    def test_empty_output(self):
        assert _parse_xbird_output("") == []
        assert _parse_xbird_output("   ") == []

    def test_no_author_prefix(self):
        output = "Some random text\n"
        tweets = _parse_xbird_output(output)
        assert len(tweets) == 1
        assert tweets[0]["author"] == "unknown"


class TestIsSolanaRelated:
    def test_solana_keyword(self):
        assert _is_solana_related("Building on Solana")

    def test_defi_keyword(self):
        assert _is_solana_related("New DeFi protocol launch")

    def test_unrelated(self):
        assert not _is_solana_related("The weather is nice today")

    def test_case_insensitive(self):
        assert _is_solana_related("SOLANA to the moon")


class TestExtractTopicsSocial:
    def test_defi(self):
        topics = _extract_topics("new lending protocol with yield")
        assert "defi" in topics

    def test_ai_agents(self):
        topics = _extract_topics("ai agent framework for trading")
        assert "ai_agents" in topics

    def test_no_match(self):
        topics = _extract_topics("nothing here")
        assert topics == ["other"]


class TestParseRssItems:
    def test_cdata_items(self):
        xml = """
        <item><title><![CDATA[Hello Solana]]></title>
        <description><![CDATA[Great news about <b>SOL</b>]]></description></item>
        """
        items = _parse_rss_items(xml, "testuser")
        assert len(items) == 1
        assert "Great news about" in items[0]["text"]
        assert items[0]["author"] == "testuser"

    def test_plain_title_fallback(self):
        xml = "<item><title>Plain title</title></item>"
        items = _parse_rss_items(xml, "user")
        assert len(items) == 1
        assert items[0]["text"] == "Plain title"

    def test_empty_rss(self):
        assert _parse_rss_items("<rss></rss>", "user") == []


# ── DeFiLlama collector tests ──

class TestDefillamaCollector:
    @pytest.mark.asyncio
    async def test_collect_solana_tvl_parses_response(self):
        from collectors.defillama_collector import collect_solana_tvl

        mock_protocols = [
            {"name": "Jupiter", "tvl": 5_000_000, "change_1d": 2.5, "change_7d": 15.0,
             "chains": ["Solana"], "category": "Dexes", "url": "https://jup.ag"},
            {"name": "Aave", "tvl": 10_000_000, "change_1d": 1.0, "change_7d": 3.0,
             "chains": ["Ethereum"], "category": "Lending"},
            {"name": "SmallProto", "tvl": 500, "change_1d": 0, "change_7d": 0,
             "chains": ["Solana"], "category": "Other"},
        ]
        mock_chains = [{"name": "Solana", "tvl": 9_000_000_000}]

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            if "/protocols" in url and "/protocol/" not in url:
                resp.status_code = 200
                resp.json.return_value = mock_protocols
            elif "/v2/chains" in url:
                resp.status_code = 200
                resp.json.return_value = mock_chains
            elif "/protocol/" in url:
                # Historical protocol data
                resp.status_code = 200
                resp.json.return_value = {"tvl": [], "description": "Test protocol", "logo": "https://logo.png"}
            elif "historicalChainTvl" in url:
                resp.status_code = 200
                resp.json.return_value = []
            else:
                resp.status_code = 404
            return resp

        with patch("collectors.defillama_collector.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = mock_get
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            signals = await collect_solana_tvl()

        # Should include Jupiter (>1M TVL, Solana) but not Aave (Ethereum) or SmallProto (<1M)
        names = [s["name"] for s in signals]
        assert "Jupiter" in names
        assert "Aave" not in names
        assert "SmallProto" not in names
        # Should include chain TVL
        chain_signals = [s for s in signals if s["signal_type"] == "chain_tvl"]
        assert len(chain_signals) == 1

    @pytest.mark.asyncio
    async def test_collect_handles_api_error(self):
        from collectors.defillama_collector import collect_solana_tvl

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 500
            return resp

        with patch("collectors.defillama_collector.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = mock_get
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            signals = await collect_solana_tvl()
            assert signals == []


# ── GitHub collector tests ──

class TestGithubCollector:
    @pytest.mark.asyncio
    async def test_collect_new_repos(self):
        from collectors.github_collector import collect_new_solana_repos

        mock_response = {
            "items": [
                {
                    "full_name": "test/solana-sdk",
                    "description": "A Solana SDK",
                    "stargazers_count": 42,
                    "forks_count": 5,
                    "language": "Rust",
                    "created_at": "2026-02-01T00:00:00Z",
                    "html_url": "https://github.com/test/solana-sdk",
                    "topics": ["solana"],
                }
            ]
        }

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = mock_response
            return resp

        with patch("collectors.github_collector.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = mock_get
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            repos = await collect_new_solana_repos()

        assert len(repos) == 1
        assert repos[0]["name"] == "test/solana-sdk"
        assert repos[0]["stars"] == 42
        assert repos[0]["source"] == "github"

    @pytest.mark.asyncio
    async def test_collect_handles_error(self):
        from collectors.github_collector import collect_new_solana_repos

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 403
            return resp

        with patch("collectors.github_collector.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = mock_get
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            repos = await collect_new_solana_repos()
            assert repos == []


# ── Helius collector tests ──

class TestHeliusCollector:
    @pytest.mark.asyncio
    async def test_returns_empty_without_api_key(self):
        from collectors.helius_collector import collect_program_activity

        with patch("collectors.helius_collector.HELIUS_API_KEY", ""):
            signals = await collect_program_activity()
            assert signals == []
