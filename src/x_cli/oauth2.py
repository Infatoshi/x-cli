"""OAuth 2.0 User Context with PKCE for endpoints that require it (bookmarks).

X/Twitter deprecated OAuth 1.0a for some v2 endpoints. This module implements
the Authorization Code + PKCE flow with a manual redirect-capture step, so it
works on headless machines without needing a local callback server.

Token storage: ~/.config/x-cli/oauth2_tokens.json (0600).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
DEFAULT_SCOPES = ["tweet.read", "users.read", "bookmark.read", "bookmark.write", "offline.access"]
TOKEN_PATH = Path.home() / ".config" / "x-cli" / "oauth2_tokens.json"


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(client_id: str, redirect_uri: str, scopes: list[str]) -> tuple[str, str, str]:
    """Return (url, state, code_verifier). User visits url, we keep state+verifier."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", state, verifier


def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "client_id": client_id,
    }
    auth = httpx.BasicAuth(client_id, client_secret)
    resp = httpx.post(TOKEN_URL, data=data, auth=auth, timeout=30.0)
    if not resp.is_success:
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    auth = httpx.BasicAuth(client_id, client_secret)
    resp = httpx.post(TOKEN_URL, data=data, auth=auth, timeout=30.0)
    if not resp.is_success:
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


def save_tokens(payload: dict[str, Any]) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    enriched = dict(payload)
    if "expires_in" in payload and "expires_at" not in enriched:
        enriched["expires_at"] = int(time.time()) + int(payload["expires_in"]) - 30
    TOKEN_PATH.write_text(json.dumps(enriched, indent=2))
    os.chmod(TOKEN_PATH, 0o600)


def load_tokens() -> dict[str, Any] | None:
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text())
    except json.JSONDecodeError:
        return None


def get_valid_access_token(client_id: str, client_secret: str) -> str:
    """Return a non-expired access token, refreshing if needed."""
    tokens = load_tokens()
    if not tokens:
        raise RuntimeError(
            "No OAuth 2.0 tokens. Run: x-cli auth login"
        )
    if tokens.get("expires_at", 0) > int(time.time()):
        return tokens["access_token"]
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("Access token expired and no refresh token. Run: x-cli auth login")
    new_tokens = refresh_access_token(client_id, client_secret, refresh)
    if "refresh_token" not in new_tokens:
        new_tokens["refresh_token"] = refresh
    save_tokens(new_tokens)
    return new_tokens["access_token"]
