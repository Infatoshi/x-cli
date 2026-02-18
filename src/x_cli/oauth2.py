"""OAuth2 PKCE helpers and token persistence for x-cli."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values, set_key, unset_key

AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
DEFAULT_REDIRECT_URI = "https://example.com/oauth/callback"
DEFAULT_SCOPES = (
    "tweet.read",
    "users.read",
    "bookmark.read",
    "bookmark.write",
    "offline.access",
)
OAUTH2_ENV_KEYS = ("X_OAUTH2_ACCESS_TOKEN", "X_OAUTH2_REFRESH_TOKEN", "X_OAUTH2_EXPIRES_AT")


def generate_code_verifier(length: int = 64) -> str:
    """Generate a PKCE verifier (43-128 chars, URL-safe)."""
    if length < 43 or length > 128:
        raise ValueError("PKCE code verifier length must be between 43 and 128.")
    raw = base64.urlsafe_b64encode(secrets.token_bytes(length)).decode().rstrip("=")
    if len(raw) < length:
        raw += "A" * (length - len(raw))
    return raw[:length]


def generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def generate_state(length: int = 24) -> str:
    return secrets.token_urlsafe(length)


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def extract_code_from_redirect_url(redirect_url: str, expected_state: str) -> str:
    parsed = urllib.parse.urlparse(redirect_url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("Invalid redirect URL. Paste the full URL from your browser address bar.")
    query = urllib.parse.parse_qs(parsed.query)
    error = (query.get("error") or [None])[0]
    if error:
        description = (query.get("error_description") or [""])[0]
        raise RuntimeError(f"OAuth2 authorization failed: {error} {description}".strip())
    code = (query.get("code") or [None])[0]
    state = (query.get("state") or [None])[0]
    if not code:
        raise RuntimeError("Missing `code` in redirect URL.")
    if state != expected_state:
        raise RuntimeError("State mismatch in redirect URL. Abort and retry login.")
    return code


def exchange_code_for_token(
    http: httpx.Client,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    resp = http.post(
        TOKEN_URL,
        headers=_token_headers(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    return _parse_token_response(resp)


def refresh_access_token(
    http: httpx.Client,
    *,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
) -> dict[str, Any]:
    resp = http.post(
        TOKEN_URL,
        headers=_token_headers(client_id, client_secret),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
    )
    return _parse_token_response(resp)


def token_expired(expires_at: int | None, buffer_seconds: int = 120) -> bool:
    if not expires_at:
        return False
    return int(time.time()) >= (expires_at - buffer_seconds)


def expires_at_from_expires_in(expires_in: Any) -> int | None:
    if expires_in is None:
        return None
    try:
        return int(time.time()) + int(expires_in)
    except (TypeError, ValueError):
        return None


def ensure_env_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch(mode=0o600)
    else:
        path.chmod(0o600)


def migrate_legacy_oauth2_tokens(config_env_path: Path, auth2_env_path: Path) -> None:
    """Move mutable OAuth2 token keys from .env to .env.auth2."""
    legacy_values = _read_legacy_oauth2_values(config_env_path)
    if not legacy_values:
        return

    try:
        merged_auth2 = _write_missing_auth2_values(auth2_env_path, legacy_values)
        _remove_migrated_legacy_values(config_env_path, legacy_values, merged_auth2)
    except OSError:
        # Best-effort migration: keep legacy values in .env if auth2 file is not writable.
        return


def _read_legacy_oauth2_values(config_env_path: Path) -> dict[str, str | None]:
    if not config_env_path.exists():
        return {}
    config_values = dotenv_values(config_env_path)
    return {key: config_values.get(key) for key in OAUTH2_ENV_KEYS if key in config_values}


def _write_missing_auth2_values(
    auth2_env_path: Path,
    legacy_values: dict[str, str | None],
) -> dict[str, str | None]:
    auth2_values = dotenv_values(auth2_env_path) if auth2_env_path.exists() else {}
    ensure_env_file(auth2_env_path)
    for key, value in legacy_values.items():
        if auth2_values.get(key) or not value:
            continue
        set_key(str(auth2_env_path), key, str(value), quote_mode="never")
    return dotenv_values(auth2_env_path)


def _remove_migrated_legacy_values(
    config_env_path: Path,
    legacy_values: dict[str, str | None],
    merged_auth2: dict[str, str | None],
) -> None:
    for key, value in legacy_values.items():
        # Remove from .env once value exists in .env.auth2 (or was empty in .env).
        if merged_auth2.get(key) or not value:
            unset_key(str(config_env_path), key, quote_mode="never")


def persist_oauth2_tokens(
    path: Path,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_at: int | None,
) -> None:
    ensure_env_file(path)
    set_key(str(path), "X_OAUTH2_ACCESS_TOKEN", access_token, quote_mode="never")
    if refresh_token:
        set_key(str(path), "X_OAUTH2_REFRESH_TOKEN", refresh_token, quote_mode="never")
    else:
        unset_key(str(path), "X_OAUTH2_REFRESH_TOKEN", quote_mode="never")
    if expires_at is not None:
        set_key(str(path), "X_OAUTH2_EXPIRES_AT", str(expires_at), quote_mode="never")
    else:
        unset_key(str(path), "X_OAUTH2_EXPIRES_AT", quote_mode="never")


def clear_oauth2_tokens(path: Path) -> None:
    if not path.exists():
        return
    for key in OAUTH2_ENV_KEYS:
        unset_key(str(path), key, quote_mode="never")


def _parse_token_response(resp: httpx.Response) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if not resp.is_success:
        msg = _extract_token_error(payload) or resp.text[:500]
        raise RuntimeError(f"OAuth2 token request failed (HTTP {resp.status_code}): {msg}")
    if "access_token" not in payload:
        raise RuntimeError("OAuth2 token response missing `access_token`.")
    return payload


def _token_headers(client_id: str, client_secret: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers


def _extract_token_error(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("error_description", "error", "detail", "title"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""
