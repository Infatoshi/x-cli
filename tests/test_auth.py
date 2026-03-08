"""Tests for x_cli.auth."""

import os
from pathlib import Path

import pytest

from x_cli.auth import Credentials, generate_oauth_header, load_env_files


@pytest.fixture
def creds():
    return Credentials(
        api_key="test_key",
        api_secret="test_secret",
        access_token="test_token",
        access_token_secret="test_token_secret",
        bearer_token="test_bearer",
    )


class TestGenerateOAuthHeader:
    def test_returns_oauth_prefix(self, creds):
        header = generate_oauth_header("GET", "https://api.x.com/2/tweets/123", creds)
        assert header.startswith("OAuth ")

    def test_contains_consumer_key(self, creds):
        header = generate_oauth_header("GET", "https://api.x.com/2/tweets/123", creds)
        assert "oauth_consumer_key" in header
        assert "test_key" in header

    def test_contains_signature(self, creds):
        header = generate_oauth_header("POST", "https://api.x.com/2/tweets", creds)
        assert "oauth_signature=" in header

    def test_contains_token(self, creds):
        header = generate_oauth_header("GET", "https://api.x.com/2/users/me", creds)
        assert "oauth_token" in header
        assert "test_token" in header

    def test_different_urls_different_signatures(self, creds):
        h1 = generate_oauth_header("GET", "https://api.x.com/2/tweets/1", creds)
        h2 = generate_oauth_header("GET", "https://api.x.com/2/tweets/2", creds)
        # Extract signatures
        import re
        sig1 = re.search(r'oauth_signature="([^"]+)"', h1).group(1)
        sig2 = re.search(r'oauth_signature="([^"]+)"', h2).group(1)
        assert sig1 != sig2

    def test_url_with_query_params(self, creds):
        url = "https://api.x.com/2/tweets/123?tweet.fields=created_at,public_metrics"
        header = generate_oauth_header("GET", url, creds)
        assert header.startswith("OAuth ")


def test_load_env_files_prefers_auth2_file(monkeypatch, tmp_path: Path):
    config_env = tmp_path / ".env"
    auth2_env = tmp_path / ".env.auth2"
    config_env.write_text("X_OAUTH2_ACCESS_TOKEN=config-token\n")
    auth2_env.write_text("X_OAUTH2_ACCESS_TOKEN=auth2-token\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("x_cli.auth.get_config_env_path", lambda: config_env)
    monkeypatch.setattr("x_cli.auth.get_config_auth2_env_path", lambda: auth2_env)
    monkeypatch.delenv("X_OAUTH2_ACCESS_TOKEN", raising=False)

    load_env_files()

    assert os.environ.get("X_OAUTH2_ACCESS_TOKEN") == "auth2-token"
