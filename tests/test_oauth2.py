"""Tests for x_cli.oauth2 helpers."""

import base64
import urllib.parse

import httpx

from pathlib import Path

from x_cli.oauth2 import (
    build_authorization_url,
    clear_oauth2_tokens,
    exchange_code_for_token,
    extract_code_from_redirect_url,
    generate_code_challenge,
    generate_code_verifier,
    refresh_access_token,
    persist_oauth2_tokens,
)


def test_generate_code_verifier_length():
    verifier = generate_code_verifier(64)
    assert len(verifier) == 64


def test_generate_code_challenge_known_value():
    # PKCE sample verifier from RFC 7636 Appendix B
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert generate_code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_build_authorization_url_contains_required_params():
    url = build_authorization_url(
        client_id="cid",
        redirect_uri="https://example.com/oauth/callback",
        state="state-123",
        code_challenge="challenge-abc",
    )
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "state=state-123" in url
    assert "code_challenge=challenge-abc" in url


def test_extract_code_from_redirect_url_valid():
    code = extract_code_from_redirect_url(
        "https://example.com/oauth/callback?code=abc123&state=s1",
        "s1",
    )
    assert code == "abc123"


def test_extract_code_from_redirect_url_state_mismatch():
    try:
        extract_code_from_redirect_url(
            "https://example.com/oauth/callback?code=abc123&state=wrong",
            "expected",
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "State mismatch" in str(exc)


def test_persist_and_clear_oauth2_tokens(tmp_path: Path):
    env_path = tmp_path / ".env"
    persist_oauth2_tokens(
        env_path,
        access_token="access",
        refresh_token="refresh",
        expires_at=1234,
    )
    text = env_path.read_text()
    assert "X_OAUTH2_ACCESS_TOKEN=access" in text
    assert "X_OAUTH2_REFRESH_TOKEN=refresh" in text
    assert "X_OAUTH2_EXPIRES_AT=1234" in text

    clear_oauth2_tokens(env_path)
    text2 = env_path.read_text()
    assert "X_OAUTH2_ACCESS_TOKEN" not in text2
    assert "X_OAUTH2_REFRESH_TOKEN" not in text2
    assert "X_OAUTH2_EXPIRES_AT" not in text2


def test_persist_oauth2_tokens_unsets_optional_fields_when_missing(tmp_path: Path):
    env_path = tmp_path / ".env"
    persist_oauth2_tokens(
        env_path,
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=1234,
    )
    persist_oauth2_tokens(
        env_path,
        access_token="access-2",
        refresh_token=None,
        expires_at=None,
    )
    text = env_path.read_text()
    assert "X_OAUTH2_ACCESS_TOKEN=access-2" in text
    assert "X_OAUTH2_REFRESH_TOKEN" not in text
    assert "X_OAUTH2_EXPIRES_AT" not in text


def test_exchange_code_for_token_uses_basic_header_when_secret_present():
    def handler(request: httpx.Request) -> httpx.Response:
        expected = base64.b64encode(b"cid:csecret").decode()
        assert request.headers.get("Authorization") == f"Basic {expected}"
        body = urllib.parse.parse_qs(request.content.decode())
        assert body["client_id"][0] == "cid"
        return httpx.Response(200, request=request, json={"access_token": "a"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        data = exchange_code_for_token(
            http,
            client_id="cid",
            client_secret="csecret",
            code="abc",
            code_verifier="verifier",
            redirect_uri="https://example.com/oauth/callback",
        )
    assert data["access_token"] == "a"


def test_refresh_access_token_uses_basic_header_when_secret_present():
    def handler(request: httpx.Request) -> httpx.Response:
        expected = base64.b64encode(b"cid:csecret").decode()
        assert request.headers.get("Authorization") == f"Basic {expected}"
        return httpx.Response(200, request=request, json={"access_token": "a2"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        data = refresh_access_token(
            http,
            client_id="cid",
            client_secret="csecret",
            refresh_token="r1",
        )
    assert data["access_token"] == "a2"
