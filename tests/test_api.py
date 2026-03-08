"""Tests for x_cli.api auth routing and error handling."""

import httpx
import pytest

from x_cli.api import XApiClient
from x_cli.auth import Credentials


@pytest.fixture
def client():
    creds = Credentials(
        api_key="test_key",
        api_secret="test_secret",
        access_token="test_token",
        access_token_secret="test_token_secret",
        bearer_token="test_bearer",
    )
    c = XApiClient(creds)
    yield c
    c.close()


def _set_transport(client: XApiClient, handler) -> None:
    client._http.close()
    client._http = httpx.Client(transport=httpx.MockTransport(handler))


def test_bookmarks_require_oauth2_login(client):
    with pytest.raises(RuntimeError, match="Missing OAuth2 user token"):
        client.get_bookmarks()


def test_bookmarks_use_oauth2_bearer_token(client):
    client.creds.oauth2_access_token = "oauth2_user_token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer oauth2_user_token"
        if request.url.path == "/2/users/me":
            return httpx.Response(200, request=request, json={"data": {"id": "42"}})
        if request.url.path == "/2/users/42/bookmarks":
            return httpx.Response(200, request=request, json={"data": []})
        return httpx.Response(404, request=request, json={"detail": "not found"})

    _set_transport(client, handler)
    data = client.get_bookmarks(max_results=10)
    assert data["data"] == []


def test_mentions_still_use_oauth1(client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("OAuth ")
        if request.url.path == "/2/users/me":
            return httpx.Response(200, request=request, json={"data": {"id": "100"}})
        if request.url.path == "/2/users/100/mentions":
            return httpx.Response(200, request=request, json={"data": [{"id": "1"}]})
        return httpx.Response(404, request=request, json={"detail": "not found"})

    _set_transport(client, handler)
    data = client.get_mentions(max_results=5)
    assert data["data"][0]["id"] == "1"


def test_oauth2_request_refreshes_on_401(client, monkeypatch):
    client.creds.oauth2_client_id = "client-id"
    client.creds.oauth2_access_token = "old-access"
    client.creds.oauth2_refresh_token = "refresh-1"

    calls = {"users_me": 0, "refresh": 0, "persist": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/users/me":
            calls["users_me"] += 1
            if calls["users_me"] == 1:
                assert request.headers["Authorization"] == "Bearer old-access"
                return httpx.Response(401, request=request, json={"detail": "expired"})
            assert request.headers["Authorization"] == "Bearer new-access"
            return httpx.Response(200, request=request, json={"data": {"id": "77"}})
        return httpx.Response(404, request=request, json={"detail": "not found"})

    def fake_refresh(http, *, client_id: str, client_secret: str | None, refresh_token: str):
        calls["refresh"] += 1
        assert client_id == "client-id"
        assert client_secret is None
        assert refresh_token == "refresh-1"
        return {"access_token": "new-access", "refresh_token": "refresh-2", "expires_in": 3600}

    def fake_persist(*args, **kwargs):
        calls["persist"] += 1

    monkeypatch.setattr("x_cli.api.refresh_access_token", fake_refresh)
    monkeypatch.setattr("x_cli.api.persist_oauth2_tokens", fake_persist)
    _set_transport(client, handler)

    user_id = client.get_authenticated_user_id_oauth2()
    assert user_id == "77"
    assert calls["refresh"] == 1
    assert calls["persist"] == 1
    assert client.creds.oauth2_access_token == "new-access"
    assert client.creds.oauth2_refresh_token == "refresh-2"


def test_oauth2_app_only_token_shows_actionable_error(client):
    client.creds.oauth2_access_token = "app-only-token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            request=request,
            json={
                "detail": (
                    "Authenticating with OAuth 2.0 Application-Only is forbidden for this endpoint. "
                    "Supported authentication types are [OAuth 1.0a User Context, OAuth 2.0 User Context]."
                ),
            },
        )

    _set_transport(client, handler)
    with pytest.raises(RuntimeError, match="not a user-context token"):
        client.get_bookmarks()
