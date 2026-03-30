"""Tests for watch module."""

from x_cli.watch import _matches_filters, WatchTarget, WatchStats


class TestMatchesFilters:
    def test_no_filters_matches_everything(self):
        assert _matches_filters("any text here", []) is True

    def test_single_filter_match(self):
        assert _matches_filters("Big $NVDA sweep today", ["$NVDA"]) is True

    def test_single_filter_no_match(self):
        assert _matches_filters("Big $TSLA sweep today", ["$NVDA"]) is False

    def test_case_insensitive(self):
        assert _matches_filters("nvidia is pumping", ["NVIDIA"]) is True
        assert _matches_filters("NVIDIA is pumping", ["nvidia"]) is True

    def test_multiple_filters_any_match(self):
        assert _matches_filters("$NVDA calls", ["$TSLA", "$NVDA"]) is True

    def test_multiple_filters_none_match(self):
        assert _matches_filters("$AAPL calls", ["$TSLA", "$NVDA"]) is False

    def test_partial_match(self):
        assert _matches_filters("Something about flow", ["flow"]) is True

    def test_empty_text(self):
        assert _matches_filters("", ["keyword"]) is False
        assert _matches_filters("", []) is True


class TestWatchTarget:
    def test_defaults(self):
        t = WatchTarget(username="CheddarFlow", user_id="123")
        assert t.username == "CheddarFlow"
        assert t.user_id == "123"
        assert t.last_seen_id is None

    def test_with_last_seen(self):
        t = WatchTarget(username="test", user_id="456", last_seen_id="789")
        assert t.last_seen_id == "789"


class TestWatchStats:
    def test_defaults(self):
        s = WatchStats()
        assert s.tweets_seen == 0
        assert s.polls == 0
        assert s.per_user == {}

    def test_accumulate(self):
        s = WatchStats()
        s.tweets_seen += 3
        s.polls += 1
        s.per_user["CheddarFlow"] = 3
        assert s.tweets_seen == 3
        assert s.per_user["CheddarFlow"] == 3
