"""Tests for x_cli.api."""

from x_cli import oauth2
from x_cli.api import XApiClient
from x_cli.auth import Credentials


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.headers = {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return FakeResponse(self.responses.pop(0))


def make_client(responses):
    creds = Credentials(
        api_key="api-key",
        api_secret="api-secret",
        access_token="access-token",
        access_token_secret="access-token-secret",
        bearer_token="bearer-token",
    )
    client = XApiClient(creds)
    client._http = FakeHttp(responses)
    return client


def test_recent_search_uses_recent_endpoint():
    client = make_client([{"data": [{"id": "1"}], "meta": {"result_count": 1}}])

    client.search_tweets("timelapse from:elliotarledge", 25)

    call = client._http.calls[0]
    assert call["url"].endswith("/tweets/search/recent")
    assert call["params"]["query"] == "timelapse from:elliotarledge"
    assert call["params"]["max_results"] == "25"


def test_archive_search_uses_full_archive_endpoint_and_500_cap():
    client = make_client([{"data": [{"id": "1"}], "meta": {"result_count": 1}}])

    client.search_all_tweets("timelapse from:elliotarledge", 1000)

    call = client._http.calls[0]
    assert call["url"].endswith("/tweets/search/all")
    assert call["params"]["max_results"] == "500"
    assert call["params"]["start_time"] == "2006-03-21T00:00:00Z"


def test_paginated_archive_search_merges_pages_and_includes():
    client = make_client(
        [
            {
                "data": [{"id": "2", "author_id": "u1"}, {"id": "1", "author_id": "u1"}],
                "includes": {"users": [{"id": "u1", "username": "elliotarledge"}]},
                "meta": {"next_token": "next", "result_count": 2},
            },
            {
                "data": [{"id": "0", "author_id": "u1"}],
                "includes": {"users": [{"id": "u1", "username": "elliotarledge"}]},
                "meta": {"result_count": 1},
            },
        ]
    )

    data = client.search_tweets_paginated(
        "timelapse from:elliotarledge",
        10,
        archive=True,
    )

    assert [tweet["id"] for tweet in data["data"]] == ["2", "1", "0"]
    assert data["includes"]["users"] == [{"id": "u1", "username": "elliotarledge"}]
    assert data["meta"]["result_count"] == 3
    assert data["meta"]["pages"] == 2
    assert client._http.calls[1]["params"]["next_token"] == "next"


def test_get_liked_tweets_uses_oauth2_user_context_and_clamps_max(monkeypatch):
    client = make_client([])
    captured = {}

    monkeypatch.setattr(oauth2, "load_tokens", lambda: {"scope": "tweet.read users.read like.read"})
    client.get_authenticated_user_id = lambda: "123"  # type: ignore[method-assign]

    def fake_oauth2_request(method, url, json_body=None):
        captured["method"] = method
        captured["url"] = url
        captured["json_body"] = json_body
        return {"data": []}

    client._oauth2_request = fake_oauth2_request  # type: ignore[method-assign]

    client.get_liked_tweets(1_000)

    assert captured["method"] == "GET"
    assert captured["json_body"] is None
    assert captured["url"].startswith("https://api.x.com/2/users/123/liked_tweets?")
    assert "max_results=100" in captured["url"]


def test_get_liked_tweets_minimum_max_is_five(monkeypatch):
    client = make_client([])
    captured = {}

    monkeypatch.setattr(oauth2, "load_tokens", lambda: {"scope": "tweet.read users.read like.read"})
    client.get_authenticated_user_id = lambda: "123"  # type: ignore[method-assign]

    def fake_oauth2_request(method, url, json_body=None):
        captured["url"] = url
        return {"data": []}

    client._oauth2_request = fake_oauth2_request  # type: ignore[method-assign]

    client.get_liked_tweets(1)

    assert "max_results=5" in captured["url"]


def test_get_liked_tweets_requires_like_read_scope(monkeypatch):
    client = make_client([])
    monkeypatch.setattr(oauth2, "load_tokens", lambda: {"scope": "tweet.read users.read"})

    try:
        client.get_liked_tweets()
    except RuntimeError as exc:
        assert "missing like.read" in str(exc)
    else:
        raise AssertionError("expected missing like.read error")


def test_get_user_encodes_crafted_username_as_one_segment():
    client = make_client([{"data": {"id": "1", "username": "victim"}}])

    client.get_user("victim?user.fields=private")

    url = client._http.calls[0]["url"]
    assert "/users/by/username/victim%3Fuser.fields%3Dprivate?" in url
    assert "user.fields=private&" not in url


def test_get_timeline_encodes_crafted_user_id_as_one_segment():
    client = make_client([{"data": [], "meta": {"result_count": 0}}])

    client.get_timeline("123/followers")

    url = client._http.calls[0]["url"]
    assert url.endswith("/users/123%2Ffollowers/tweets")
