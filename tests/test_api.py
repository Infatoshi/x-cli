"""Tests for x_cli.api."""

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
