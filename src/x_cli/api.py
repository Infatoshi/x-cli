"""Twitter API v2 client with OAuth 1.0a and Bearer token auth."""

from __future__ import annotations

from typing import Any

import httpx

from .auth import Credentials, generate_oauth_header
from . import oauth2

API_BASE = "https://api.x.com/2"
FULL_ARCHIVE_START_TIME = "2006-03-21T00:00:00Z"


def _merge_paginated_responses(pages: list[dict[str, Any]]) -> dict[str, Any]:
    if not pages:
        return {"data": [], "meta": {"result_count": 0}}

    merged: dict[str, Any] = {"data": [], "includes": {}, "meta": {}}
    seen_tweets: set[str] = set()

    for page in pages:
        for tweet in page.get("data", []):
            tweet_id = tweet.get("id")
            if tweet_id and tweet_id in seen_tweets:
                continue
            if tweet_id:
                seen_tweets.add(tweet_id)
            merged["data"].append(tweet)

        for include_key, include_items in page.get("includes", {}).items():
            target = merged["includes"].setdefault(include_key, [])
            seen_include_ids = {
                item.get("id") or item.get("media_key")
                for item in target
                if isinstance(item, dict)
            }
            for item in include_items:
                item_id = item.get("id") or item.get("media_key")
                if item_id and item_id in seen_include_ids:
                    continue
                target.append(item)
                if item_id:
                    seen_include_ids.add(item_id)

    last_meta = pages[-1].get("meta", {})
    merged["meta"] = {
        **last_meta,
        "result_count": len(merged["data"]),
        "pages": len(pages),
    }
    return merged


class XApiClient:
    def __init__(self, creds: Credentials) -> None:
        self.creds = creds
        self._user_id: str | None = None
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    # ---- internal ----

    def _bearer_get(self, url: str) -> dict[str, Any]:
        resp = self._http.get(url, headers={"Authorization": f"Bearer {self.creds.bearer_token}"})
        return self._handle(resp)

    def _oauth2_request(self, method: str, url: str, json_body: dict | None = None) -> dict[str, Any]:
        if not (self.creds.oauth2_client_id and self.creds.oauth2_client_secret):
            raise RuntimeError(
                "OAuth 2.0 client creds missing. Set X_OAUTH2_CLIENT_ID and X_OAUTH2_CLIENT_SECRET."
            )
        token = oauth2.get_valid_access_token(
            self.creds.oauth2_client_id, self.creds.oauth2_client_secret
        )
        headers = {"Authorization": f"Bearer {token}"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(method, url, headers=headers, json=json_body if json_body else None)
        return self._handle(resp)

    def _oauth_request(self, method: str, url: str, json_body: dict | None = None) -> dict[str, Any]:
        auth_header = generate_oauth_header(method, url, self.creds)
        headers: dict[str, str] = {"Authorization": auth_header}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(method, url, headers=headers, json=json_body if json_body else None)
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset", "unknown")
            raise RuntimeError(f"Rate limited. Resets at {reset}.")
        data = resp.json()
        if not resp.is_success:
            errors = data.get("errors", [])
            msg = "; ".join(e.get("detail") or e.get("message", "") for e in errors) or resp.text[:500]
            raise RuntimeError(f"API error (HTTP {resp.status_code}): {msg}")
        return data

    def get_authenticated_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        data = self._oauth_request("GET", f"{API_BASE}/users/me")
        self._user_id = data["data"]["id"]
        return self._user_id

    # ---- tweets ----

    def post_tweet(
        self,
        text: str,
        reply_to: str | None = None,
        quote_tweet_id: str | None = None,
        poll_options: list[str] | None = None,
        poll_duration_minutes: int = 1440,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text}
        if reply_to:
            # NOTE: X API restricts programmatic replies (Feb 2024). Replies only
            # succeed if the original author @mentioned you or quoted your post.
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        if quote_tweet_id:
            body["quote_tweet_id"] = quote_tweet_id
        if poll_options:
            body["poll"] = {"options": poll_options, "duration_minutes": poll_duration_minutes}
        return self._oauth_request("POST", f"{API_BASE}/tweets", body)

    def delete_tweet(self, tweet_id: str) -> dict[str, Any]:
        return self._oauth_request("DELETE", f"{API_BASE}/tweets/{tweet_id}")

    def get_tweet(self, tweet_id: str) -> dict[str, Any]:
        params = {
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,in_reply_to_user_id,referenced_tweets,attachments,entities,lang,note_tweet",
            "expansions": "author_id,referenced_tweets.id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url,public_metrics",
            "media.fields": "url,preview_image_url,type,width,height,alt_text",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return self._bearer_get(f"{API_BASE}/tweets/{tweet_id}?{qs}")

    def search_tweets(
        self,
        query: str,
        max_results: int = 10,
        *,
        next_token: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        max_results = max(10, min(max_results, 100))
        params = {
            "query": query,
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        if next_token:
            params["next_token"] = next_token
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        url = f"{API_BASE}/tweets/search/recent"
        resp = self._http.get(url, params=params, headers={"Authorization": f"Bearer {self.creds.bearer_token}"})
        return self._handle(resp)

    def search_all_tweets(
        self,
        query: str,
        max_results: int = 10,
        *,
        next_token: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        max_results = max(10, min(max_results, 500))
        start_time = start_time or FULL_ARCHIVE_START_TIME
        params = {
            "query": query,
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        if next_token:
            params["next_token"] = next_token
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        resp = self._http.get(
            f"{API_BASE}/tweets/search/all",
            params=params,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
        )
        return self._handle(resp)

    def search_tweets_paginated(
        self,
        query: str,
        max_results: int,
        *,
        archive: bool = False,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        page_size = 500 if archive else 100
        if archive:
            start_time = start_time or FULL_ARCHIVE_START_TIME
        remaining = max(10, max_results)
        next_token: str | None = None
        pages: list[dict[str, Any]] = []

        while remaining > 0:
            fetch_size = min(page_size, remaining)
            page = (
                self.search_all_tweets(
                    query,
                    fetch_size,
                    next_token=next_token,
                    start_time=start_time,
                    end_time=end_time,
                )
                if archive
                else self.search_tweets(
                    query,
                    fetch_size,
                    next_token=next_token,
                    start_time=start_time,
                    end_time=end_time,
                )
            )
            pages.append(page)
            remaining -= len(page.get("data", []))
            next_token = page.get("meta", {}).get("next_token")
            if not next_token or not page.get("data"):
                break

        return _merge_paginated_responses(pages)

    def get_tweet_metrics(self, tweet_id: str) -> dict[str, Any]:
        params = "tweet.fields=public_metrics,non_public_metrics,organic_metrics"
        return self._oauth_request("GET", f"{API_BASE}/tweets/{tweet_id}?{params}")

    # ---- users ----

    def get_user(self, username: str) -> dict[str, Any]:
        fields = "user.fields=created_at,description,public_metrics,verified,profile_image_url,url,location,pinned_tweet_id"
        return self._bearer_get(f"{API_BASE}/users/by/username/{username}?{fields}")

    def get_timeline(self, user_id: str, max_results: int = 10) -> dict[str, Any]:
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys,referenced_tweets.id",
            "user.fields": "name,username,verified",
            "media.fields": "url,preview_image_url,type",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_followers(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/followers",
            params=params,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_following(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/following",
            params=params,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_mentions(self, max_results: int = 10) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,note_tweet",
            "expansions": "author_id",
            "user.fields": "name,username,verified",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{API_BASE}/users/{user_id}/mentions?{qs}"
        return self._oauth_request("GET", url)

    # ---- engagement ----

    def like_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/likes", {"tweet_id": tweet_id})

    def retweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/retweets", {"tweet_id": tweet_id})

    # ---- bookmarks (require OAuth 2.0 User Context) ----

    def get_bookmarks(self, max_results: int = 10) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        max_results = max(1, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{API_BASE}/users/{user_id}/bookmarks?{qs}"
        return self._oauth2_request("GET", url)

    def bookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth2_request("POST", f"{API_BASE}/users/{user_id}/bookmarks", {"tweet_id": tweet_id})

    def unbookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth2_request("DELETE", f"{API_BASE}/users/{user_id}/bookmarks/{tweet_id}")
