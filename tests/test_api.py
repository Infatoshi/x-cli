"""Tests for x_cli.api error handling."""

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


def test_bookmarks_requires_oauth2_user_context_message(client):
    req = httpx.Request("GET", "https://api.x.com/2/users/123/bookmarks")
    resp = httpx.Response(
        403,
        request=req,
        json={
            "title": "Unsupported Authentication",
            "detail": (
                "Authenticating with OAuth 1.0a User Context is forbidden for this endpoint. "
                "Supported authentication types are [OAuth 2.0 User Context]."
            ),
            "type": "https://api.twitter.com/2/problems/unsupported-authentication",
            "status": 403,
        },
    )

    with pytest.raises(RuntimeError, match="Bookmarks endpoints require OAuth 2.0 User Context"):
        client._handle(resp)


def test_non_bookmark_error_uses_api_detail(client):
    req = httpx.Request("GET", "https://api.x.com/2/users/me")
    resp = httpx.Response(
        401,
        request=req,
        json={"title": "Unauthorized", "detail": "Could not authenticate you"},
    )

    with pytest.raises(RuntimeError, match="API error \\(HTTP 401\\): Could not authenticate you"):
        client._handle(resp)
