"""Auth: env var loading and OAuth header generation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from .oauth2 import migrate_legacy_oauth2_tokens


@dataclass
class Credentials:
    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str
    bearer_token: str
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_access_token: str | None = None
    oauth2_refresh_token: str | None = None
    oauth2_expires_at: int | None = None


def get_config_env_path() -> Path:
    return Path.home() / ".config" / "x-cli" / ".env"


def get_config_auth2_env_path() -> Path:
    return Path.home() / ".config" / "x-cli" / ".env.auth2"


def load_env_files() -> None:
    """Load env files with auth2 token precedence over static config."""
    config_env = get_config_env_path()
    if config_env.exists():
        load_dotenv(config_env)
    load_dotenv()
    auth2_env = get_config_auth2_env_path()
    migrate_legacy_oauth2_tokens(config_env, auth2_env)
    if auth2_env.exists():
        load_dotenv(auth2_env, override=True)


def load_credentials() -> Credentials:
    """Load credentials from env vars, with .env fallback."""
    load_env_files()

    def require(name: str) -> str:
        val = os.environ.get(name)
        if not val:
            raise SystemExit(
                f"Missing env var: {name}. "
                "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_BEARER_TOKEN."
            )
        return val

    def optional_int(name: str) -> int | None:
        val = os.environ.get(name)
        if not val:
            return None
        try:
            return int(val)
        except ValueError as exc:
            raise SystemExit(f"Invalid env var: {name} must be an integer unix timestamp.") from exc

    return Credentials(
        api_key=require("X_API_KEY"),
        api_secret=require("X_API_SECRET"),
        access_token=require("X_ACCESS_TOKEN"),
        access_token_secret=require("X_ACCESS_TOKEN_SECRET"),
        bearer_token=require("X_BEARER_TOKEN"),
        oauth2_client_id=os.environ.get("X_OAUTH2_CLIENT_ID"),
        oauth2_client_secret=os.environ.get("X_OAUTH2_CLIENT_SECRET"),
        oauth2_access_token=os.environ.get("X_OAUTH2_ACCESS_TOKEN"),
        oauth2_refresh_token=os.environ.get("X_OAUTH2_REFRESH_TOKEN"),
        oauth2_expires_at=optional_int("X_OAUTH2_EXPIRES_AT"),
    )


def _percent_encode(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def generate_oauth_header(
    method: str,
    url: str,
    creds: Credentials,
    params: dict[str, str] | None = None,
) -> str:
    """Generate an OAuth 1.0a Authorization header (HMAC-SHA1)."""
    oauth_params = {
        "oauth_consumer_key": creds.api_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds.access_token,
        "oauth_version": "1.0",
    }

    # Combine oauth params with any query/body params for signature base
    all_params = {**oauth_params}
    if params:
        all_params.update(params)

    # Also include query string params from the URL
    parsed = urllib.parse.urlparse(url)
    if parsed.query:
        qs_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        for k, v in qs_params.items():
            all_params[k] = v[0]

    # Sort and encode
    sorted_params = sorted(all_params.items())
    param_string = "&".join(f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_params)

    # Base URL (no query string)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    # Signature base string
    base_string = f"{method.upper()}&{_percent_encode(base_url)}&{_percent_encode(param_string)}"

    # Signing key
    signing_key = f"{_percent_encode(creds.api_secret)}&{_percent_encode(creds.access_token_secret)}"

    # HMAC-SHA1
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()

    oauth_params["oauth_signature"] = signature

    # Build header
    header_parts = ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"
