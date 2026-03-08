"""Twitter API v2 client with OAuth 1.0a and Bearer token auth."""

from __future__ import annotations

from typing import Any

import httpx

from .auth import Credentials, generate_oauth_header, get_config_auth2_env_path
from .oauth2 import expires_at_from_expires_in, persist_oauth2_tokens, refresh_access_token, token_expired

API_BASE = "https://api.x.com/2"


class XApiClient:
    def __init__(self, creds: Credentials) -> None:
        self.creds = creds
        self._user_id: str | None = None
        self._oauth2_user_id: str | None = None
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    # ---- internal ----

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> httpx.Response:
        return self._http.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body if json_body is not None else None,
        )

    @staticmethod
    def _query_url(base_url: str, params: dict[str, str]) -> str:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base_url}?{qs}" if qs else base_url

    def _bearer_get(self, url: str) -> dict[str, Any]:
        resp = self._request("GET", url, headers={"Authorization": f"Bearer {self.creds.bearer_token}"})
        return self._handle(resp)

    def _oauth_request(self, method: str, url: str, json_body: dict | None = None) -> dict[str, Any]:
        auth_header = generate_oauth_header(method, url, self.creds)
        headers: dict[str, str] = {"Authorization": auth_header}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._request(method, url, headers=headers, json_body=json_body)
        return self._handle(resp)

    def _oauth2_user_request(
        self,
        method: str,
        url: str,
        json_body: dict | None = None,
        *,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        self._ensure_oauth2_access_token()
        headers: dict[str, str] = {"Authorization": f"Bearer {self.creds.oauth2_access_token}"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._request(method, url, headers=headers, json_body=json_body)
        if resp.status_code == 401 and retry_on_401:
            self._refresh_oauth2_access_token()
            return self._oauth2_user_request(method, url, json_body, retry_on_401=False)
        if resp.status_code == 403:
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            detail = str(payload.get("detail", ""))
            if "OAuth 2.0 Application-Only" in detail:
                raise RuntimeError(
                    "Stored X_OAUTH2_ACCESS_TOKEN is not a user-context token. "
                    "Run `x-cli auth login` to obtain an OAuth2 User Context token for bookmarks."
                )
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset", "unknown")
            raise RuntimeError(f"Rate limited. Resets at {reset}.")
        data = resp.json()
        if not resp.is_success:
            msg = self._extract_error_message(resp, data)
            raise RuntimeError(f"API error (HTTP {resp.status_code}): {msg}")
        return data

    @staticmethod
    def _extract_error_message(resp: httpx.Response, data: dict[str, Any]) -> str:
        errors = data.get("errors", [])
        if isinstance(errors, list):
            details = [e.get("detail") or e.get("message", "") for e in errors if isinstance(e, dict)]
            details = [d for d in details if d]
            if details:
                return "; ".join(details)
        detail = data.get("detail")
        if detail:
            return str(detail)
        title = data.get("title")
        if title:
            return str(title)
        return resp.text[:500]

    def _ensure_oauth2_access_token(self) -> None:
        if not self.creds.oauth2_access_token:
            raise RuntimeError(
                "Missing OAuth2 user token for bookmarks. Run `x-cli auth login` to set "
                "X_OAUTH2_ACCESS_TOKEN/X_OAUTH2_REFRESH_TOKEN."
            )
        if token_expired(self.creds.oauth2_expires_at):
            self._refresh_oauth2_access_token()

    def _refresh_oauth2_access_token(self) -> None:
        if not self.creds.oauth2_client_id:
            raise RuntimeError(
                "Missing env var X_OAUTH2_CLIENT_ID. Set it first, then run `x-cli auth login`."
            )
        if not self.creds.oauth2_refresh_token:
            raise RuntimeError(
                "OAuth2 access token expired and no refresh token is available. Run `x-cli auth login`."
            )
        data = refresh_access_token(
            self._http,
            client_id=self.creds.oauth2_client_id,
            client_secret=self.creds.oauth2_client_secret,
            refresh_token=self.creds.oauth2_refresh_token,
        )
        self._persist_oauth2_tokens_from_response(data)

    def _persist_oauth2_tokens_from_response(self, data: dict[str, Any]) -> None:
        access_token = str(data["access_token"])
        refresh_token = data.get("refresh_token") or self.creds.oauth2_refresh_token
        expires_at = expires_at_from_expires_in(data.get("expires_in"))

        self.creds.oauth2_access_token = access_token
        self.creds.oauth2_refresh_token = str(refresh_token) if refresh_token else None
        self.creds.oauth2_expires_at = expires_at

        persist_oauth2_tokens(
            get_config_auth2_env_path(),
            access_token=access_token,
            refresh_token=self.creds.oauth2_refresh_token,
            expires_at=expires_at,
        )

    def get_authenticated_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        data = self._oauth_request("GET", f"{API_BASE}/users/me")
        self._user_id = data["data"]["id"]
        return self._user_id

    def get_authenticated_user_id_oauth2(self) -> str:
        if self._oauth2_user_id:
            return self._oauth2_user_id
        data = self._oauth2_user_request("GET", f"{API_BASE}/users/me")
        self._oauth2_user_id = data["data"]["id"]
        return self._oauth2_user_id

    def _get_user_id(self, *, oauth2: bool = False) -> str:
        if oauth2:
            return self.get_authenticated_user_id_oauth2()
        return self.get_authenticated_user_id()

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
        return self._bearer_get(self._query_url(f"{API_BASE}/tweets/{tweet_id}", params))

    def search_tweets(self, query: str, max_results: int = 10) -> dict[str, Any]:
        max_results = max(10, min(max_results, 100))
        params = {
            "query": query,
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        url = f"{API_BASE}/tweets/search/recent"
        resp = self._request(
            "GET",
            url,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
            params=params,
        )
        return self._handle(resp)

    def get_tweet_metrics(self, tweet_id: str) -> dict[str, Any]:
        return self._oauth_request(
            "GET",
            self._query_url(
                f"{API_BASE}/tweets/{tweet_id}",
                {"tweet.fields": "public_metrics,non_public_metrics,organic_metrics"},
            ),
        )

    # ---- users ----

    def get_user(self, username: str) -> dict[str, Any]:
        return self._bearer_get(
            self._query_url(
                f"{API_BASE}/users/by/username/{username}",
                {"user.fields": "created_at,description,public_metrics,verified,profile_image_url,url,location,pinned_tweet_id"},
            )
        )

    def get_timeline(self, user_id: str, max_results: int = 10) -> dict[str, Any]:
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys,referenced_tweets.id",
            "user.fields": "name,username,verified",
            "media.fields": "url,preview_image_url,type",
        }
        resp = self._request(
            "GET",
            f"{API_BASE}/users/{user_id}/tweets",
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
            params=params,
        )
        return self._handle(resp)

    def get_followers(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._request(
            "GET",
            f"{API_BASE}/users/{user_id}/followers",
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
            params=params,
        )
        return self._handle(resp)

    def get_following(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._request(
            "GET",
            f"{API_BASE}/users/{user_id}/following",
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
            params=params,
        )
        return self._handle(resp)

    def get_mentions(self, max_results: int = 10) -> dict[str, Any]:
        user_id = self._get_user_id()
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,note_tweet",
            "expansions": "author_id",
            "user.fields": "name,username,verified",
        }
        url = self._query_url(f"{API_BASE}/users/{user_id}/mentions", params)
        return self._oauth_request("GET", url)

    # ---- engagement ----

    def like_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self._get_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/likes", {"tweet_id": tweet_id})

    def retweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self._get_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/retweets", {"tweet_id": tweet_id})

    # ---- bookmarks (OAuth 2.0 User Context) ----

    def get_bookmarks(self, max_results: int = 10) -> dict[str, Any]:
        user_id = self._get_user_id(oauth2=True)
        max_results = max(1, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        url = self._query_url(f"{API_BASE}/users/{user_id}/bookmarks", params)
        return self._oauth2_user_request("GET", url)

    def bookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self._get_user_id(oauth2=True)
        return self._oauth2_user_request("POST", f"{API_BASE}/users/{user_id}/bookmarks", {"tweet_id": tweet_id})

    def unbookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self._get_user_id(oauth2=True)
        return self._oauth2_user_request("DELETE", f"{API_BASE}/users/{user_id}/bookmarks/{tweet_id}")
