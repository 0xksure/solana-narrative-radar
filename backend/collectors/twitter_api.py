"""Direct Twitter GraphQL API client using cookie auth (auth_token + ct0).

Replaces the xbird subprocess approach so the app can run on DO App Platform
without the bird Node.js binary installed.
"""
import json
import os
import uuid
import logging
from typing import List, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://x.com/i/api/graphql"
BEARER_TOKEN = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

# Query IDs - these rotate but these are recent fallbacks
QUERY_IDS = {
    "SearchTimeline": ["M1jEez78PEfVfbQLvlWMvQ", "5h0kNbk3ii97rmfY6CdgAA", "Tp1sewRU1AsZpBWhqCZicQ"],
    "HomeTimeline": ["edseUwk9sP5Phz__9TIRnA"],
    "HomeLatestTimeline": ["iOEZpOdfekFsxSlPQCQtPg"],
}

SEARCH_FEATURES = {
    "rweb_video_screen_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_grok_annotations_enabled": False,
    "responsive_web_jetfuel_frame": True,
    "post_ctas_fetch_enabled": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "articles_preview_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

HOME_FEATURES = {
    **SEARCH_FEATURES,
    "blue_business_profile_image_shape_enabled": True,
    "responsive_web_text_conversations_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "vibe_api_enabled": True,
    "responsive_web_twitter_blue_verified_badge_is_enabled": True,
    "interactive_text_enabled": True,
    "longform_notetweets_richtext_consumption_enabled": True,
    "responsive_web_media_download_video_enabled": False,
}


def get_credentials() -> Optional[tuple]:
    """Get Twitter credentials from environment. Returns (auth_token, ct0) or None."""
    # Strip ALL whitespace (DO App Platform may inject newlines in long secrets)
    auth_token = "".join((os.environ.get("TWITTER_AUTH_TOKEN") or os.environ.get("AUTH_TOKEN") or "").split())
    ct0 = "".join((os.environ.get("TWITTER_CT0") or os.environ.get("CT0") or "").split())
    if not auth_token or not ct0:
        return None
    return (auth_token, ct0)


def _build_headers(auth_token: str, ct0: str) -> dict:
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "authorization": BEARER_TOKEN,
        "x-csrf-token": ct0,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "x-client-uuid": str(uuid.uuid4()),
        "cookie": f"auth_token={auth_token}; ct0={ct0}",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "origin": "https://x.com",
        "referer": "https://x.com/",
        "content-type": "application/json",
    }


def _extract_tweet_text(result: dict) -> str:
    """Extract full text from a tweet result object."""
    note = result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
    if note and note.get("text"):
        return note["text"]
    legacy = result.get("legacy", {})
    return legacy.get("full_text", "") or legacy.get("text", "")


def _parse_tweet_result(result: dict) -> Optional[Dict]:
    """Parse a single tweet result from GraphQL response."""
    # Unwrap tombstone/visibility wrappers
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", result)
    if not result.get("rest_id"):
        return None

    user_result = result.get("core", {}).get("user_results", {}).get("result", {})
    user_legacy = user_result.get("legacy", {})
    user_core = user_result.get("core", {})
    username = user_legacy.get("screen_name") or user_core.get("screen_name", "")
    if not username:
        return None

    text = _extract_tweet_text(result)
    if not text:
        return None

    legacy = result.get("legacy", {})
    likes = legacy.get("favorite_count", 0)
    retweets = legacy.get("retweet_count", 0)
    replies = legacy.get("reply_count", 0)
    quotes = legacy.get("quote_count", 0)
    views = int(result.get("views", {}).get("count", 0) or 0)
    bookmarks = legacy.get("bookmark_count", 0)
    engagement_score = replies * 3 + retweets * 2 + likes

    return {
        "id": result["rest_id"],
        "text": text,
        "author": username,
        "url": f"https://x.com/{username}/status/{result['rest_id']}",
        "likes": likes,
        "retweets": retweets,
        "replies": replies,
        "quotes": quotes,
        "views": views,
        "bookmarks": bookmarks,
        "engagement_score": engagement_score,
        "created_at": legacy.get("created_at", ""),
    }


def _parse_instructions(instructions: list) -> List[Dict]:
    """Parse tweets from GraphQL timeline instructions."""
    tweets = []
    seen = set()
    for instruction in (instructions or []):
        for entry in instruction.get("entries", []):
            content = entry.get("content", {})
            # Direct tweet
            for path in [
                content.get("itemContent", {}).get("tweet_results", {}).get("result"),
                content.get("item", {}).get("itemContent", {}).get("tweet_results", {}).get("result"),
            ]:
                if path:
                    t = _parse_tweet_result(path)
                    if t and t["id"] not in seen:
                        seen.add(t["id"])
                        tweets.append(t)
            # Conversation module items
            for item in content.get("items", []):
                for sub_path in [
                    item.get("item", {}).get("itemContent", {}).get("tweet_results", {}).get("result"),
                    item.get("itemContent", {}).get("tweet_results", {}).get("result"),
                    item.get("content", {}).get("itemContent", {}).get("tweet_results", {}).get("result"),
                ]:
                    if sub_path:
                        t = _parse_tweet_result(sub_path)
                        if t and t["id"] not in seen:
                            seen.add(t["id"])
                            tweets.append(t)
    return tweets


async def search_tweets(query: str, count: int = 20) -> List[Dict]:
    """Search Twitter for tweets matching query."""
    creds = get_credentials()
    if not creds:
        logger.warning("Twitter credentials not set (TWITTER_AUTH_TOKEN/TWITTER_CT0)")
        return []

    auth_token, ct0 = creds
    headers = _build_headers(auth_token, ct0)

    variables = {
        "rawQuery": query,
        "count": count,
        "querySource": "typed_query",
        "product": "Latest",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for qid in QUERY_IDS["SearchTimeline"]:
            params = {"variables": json.dumps(variables)}
            url = f"{TWITTER_API_BASE}/{qid}/SearchTimeline?{httpx.QueryParams(params)}"
            try:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={"features": SEARCH_FEATURES, "queryId": qid},
                )
                if resp.status_code == 404:
                    continue
                if resp.status_code != 200:
                    logger.warning(f"Twitter search HTTP {resp.status_code}: {resp.text[:200]}")
                    continue
                data = resp.json()
                instructions = (
                    data.get("data", {})
                    .get("search_by_raw_query", {})
                    .get("search_timeline", {})
                    .get("timeline", {})
                    .get("instructions", [])
                )
                tweets = _parse_instructions(instructions)
                if tweets:
                    return tweets
            except Exception as e:
                logger.warning(f"Twitter search error with qid {qid}: {e}")
                continue
    return []


async def get_home_timeline(count: int = 50) -> List[Dict]:
    """Get home timeline tweets."""
    creds = get_credentials()
    if not creds:
        logger.warning("Twitter credentials not set (TWITTER_AUTH_TOKEN/TWITTER_CT0)")
        return []

    auth_token, ct0 = creds
    headers = _build_headers(auth_token, ct0)

    variables = {
        "count": count,
        "includePromotedContent": True,
        "latestControlAvailable": True,
        "requestContext": "launch",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for qid in QUERY_IDS["HomeTimeline"]:
            params = {"variables": json.dumps(variables)}
            url = f"{TWITTER_API_BASE}/{qid}/HomeTimeline?{httpx.QueryParams(params)}"
            try:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={"features": HOME_FEATURES, "queryId": qid},
                )
                if resp.status_code == 404:
                    continue
                if resp.status_code != 200:
                    logger.warning(f"Twitter home HTTP {resp.status_code}: {resp.text[:200]}")
                    continue
                data = resp.json()
                instructions = (
                    data.get("data", {})
                    .get("home", {})
                    .get("home_timeline_urt", {})
                    .get("instructions", [])
                )
                tweets = _parse_instructions(instructions)
                if tweets:
                    return tweets
            except Exception as e:
                logger.warning(f"Twitter home error with qid {qid}: {e}")
                continue
    return []
