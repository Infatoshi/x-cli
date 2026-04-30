"""Click CLI for x-cli."""

from __future__ import annotations

import os
import urllib.parse

import click

from . import oauth2
from .api import XApiClient
from .auth import load_credentials
from .formatters import format_output
from .utils import parse_tweet_id, strip_at


class State:
    def __init__(self, mode: str, verbose: bool = False) -> None:
        self.mode = mode
        self.verbose = verbose
        self._client: XApiClient | None = None

    @property
    def client(self) -> XApiClient:
        if self._client is None:
            creds = load_credentials()
            self._client = XApiClient(creds)
        return self._client

    def output(self, data, title: str = "") -> None:
        format_output(data, self.mode, title, verbose=self.verbose)


pass_state = click.make_pass_decorator(State)


@click.group()
@click.option("--json", "-j", "fmt", flag_value="json", help="JSON output")
@click.option("--plain", "-p", "fmt", flag_value="plain", help="TSV output for piping")
@click.option("--markdown", "-md", "fmt", flag_value="markdown", help="Markdown output")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Verbose output (show metrics, timestamps, metadata)")
@click.pass_context
def cli(ctx, fmt, verbose):
    """x-cli: CLI for X/Twitter API v2."""
    ctx.ensure_object(dict)
    ctx.obj = State(fmt or "human", verbose=verbose)


# ============================================================
# tweet
# ============================================================

@cli.group()
def tweet():
    """Tweet operations."""


@tweet.command("post")
@click.argument("text")
@click.option("--poll", default=None, help="Comma-separated poll options")
@click.option("--poll-duration", default=1440, type=int, help="Poll duration in minutes")
@pass_state
def tweet_post(state, text, poll, poll_duration):
    """Post a tweet."""
    poll_options = [o.strip() for o in poll.split(",")] if poll else None
    data = state.client.post_tweet(text, poll_options=poll_options, poll_duration_minutes=poll_duration)
    state.output(data, "Posted")


@tweet.command("get")
@click.argument("id_or_url")
@pass_state
def tweet_get(state, id_or_url):
    """Fetch a tweet by ID or URL."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet(tid)
    state.output(data, f"Tweet {tid}")


@tweet.command("delete")
@click.argument("id_or_url")
@pass_state
def tweet_delete(state, id_or_url):
    """Delete a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.delete_tweet(tid)
    state.output(data, "Deleted")


@tweet.command("reply")
@click.argument("id_or_url")
@click.argument("text")
@pass_state
def tweet_reply(state, id_or_url, text):
    """Reply to a tweet.

    NOTE: As of Feb 2026, X restricts programmatic replies on all self-serve
    tiers (Free, Basic, Pro, Pay-Per-Use). You can only reply if the original
    author @mentioned you or quoted your post. Enterprise is exempt.
    Use 'tweet quote' as a workaround.
    """
    tid = parse_tweet_id(id_or_url)
    click.echo(
        "Warning: X restricts programmatic replies on all self-serve tiers "
        "(Free, Basic, Pro, Pay-Per-Use). This will only succeed if the "
        "original author @mentioned you or quoted your post. Enterprise is exempt.",
        err=True,
    )
    data = state.client.post_tweet(text, reply_to=tid)
    state.output(data, "Reply")


@tweet.command("quote")
@click.argument("id_or_url")
@click.argument("text")
@pass_state
def tweet_quote(state, id_or_url, text):
    """Quote tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.post_tweet(text, quote_tweet_id=tid)
    state.output(data, "Quote")


@tweet.command("search")
@click.argument("query")
@click.option("--max", "max_results", default=10, type=int, help="Max total results")
@click.option("--archive", is_flag=True, help="Use full-archive search (/2/tweets/search/all). Requires paid access.")
@click.option("--all-pages", is_flag=True, help="Paginate until exhausted or --max results are collected.")
@click.option("--start-time", default=None, help="Oldest UTC timestamp, e.g. 2026-01-01T00:00:00Z.")
@click.option("--end-time", default=None, help="Newest UTC timestamp, e.g. 2026-02-01T00:00:00Z.")
@pass_state
def tweet_search(state, query, max_results, archive, all_pages, start_time, end_time):
    """Search tweets.

    By default this uses recent search. Add --archive for full-archive search.
    """
    if all_pages:
        data = state.client.search_tweets_paginated(
            query,
            max_results,
            archive=archive,
            start_time=start_time,
            end_time=end_time,
        )
    elif archive:
        data = state.client.search_all_tweets(
            query,
            max_results,
            start_time=start_time,
            end_time=end_time,
        )
    else:
        data = state.client.search_tweets(
            query,
            max_results,
            start_time=start_time,
            end_time=end_time,
        )
    title = f"{'Archive search' if archive else 'Search'}: {query}"
    state.output(data, title)


@tweet.command("metrics")
@click.argument("id_or_url")
@pass_state
def tweet_metrics(state, id_or_url):
    """Get tweet engagement metrics."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet_metrics(tid)
    state.output(data, f"Metrics {tid}")


# ============================================================
# user
# ============================================================

@cli.group()
def user():
    """User operations."""


@user.command("get")
@click.argument("username")
@pass_state
def user_get(state, username):
    """Look up a user profile."""
    data = state.client.get_user(strip_at(username))
    state.output(data, f"@{strip_at(username)}")


@user.command("timeline")
@click.argument("username")
@click.option("--max", "max_results", default=10, type=int, help="Max results (5-100)")
@pass_state
def user_timeline(state, username, max_results):
    """Fetch a user's recent tweets."""
    uname = strip_at(username)
    user_data = state.client.get_user(uname)
    uid = user_data["data"]["id"]
    data = state.client.get_timeline(uid, max_results)
    state.output(data, f"@{uname} timeline")


@user.command("followers")
@click.argument("username")
@click.option("--max", "max_results", default=100, type=int, help="Max results (1-1000)")
@pass_state
def user_followers(state, username, max_results):
    """List a user's followers."""
    uname = strip_at(username)
    user_data = state.client.get_user(uname)
    uid = user_data["data"]["id"]
    data = state.client.get_followers(uid, max_results)
    state.output(data, f"@{uname} followers")


@user.command("following")
@click.argument("username")
@click.option("--max", "max_results", default=100, type=int, help="Max results (1-1000)")
@pass_state
def user_following(state, username, max_results):
    """List who a user follows."""
    uname = strip_at(username)
    user_data = state.client.get_user(uname)
    uid = user_data["data"]["id"]
    data = state.client.get_following(uid, max_results)
    state.output(data, f"@{uname} following")


# ============================================================
# me
# ============================================================

@cli.group()
def me():
    """Self operations (authenticated user)."""


@me.command("mentions")
@click.option("--max", "max_results", default=10, type=int, help="Max results (5-100)")
@pass_state
def me_mentions(state, max_results):
    """Fetch your recent mentions."""
    data = state.client.get_mentions(max_results)
    state.output(data, "Mentions")


@me.command("bookmarks")
@click.option("--max", "max_results", default=10, type=int, help="Max results (1-100)")
@pass_state
def me_bookmarks(state, max_results):
    """Fetch your bookmarks."""
    data = state.client.get_bookmarks(max_results)
    state.output(data, "Bookmarks")


@me.command("bookmark")
@click.argument("id_or_url")
@pass_state
def me_bookmark(state, id_or_url):
    """Bookmark a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.bookmark_tweet(tid)
    state.output(data, "Bookmarked")


@me.command("unbookmark")
@click.argument("id_or_url")
@pass_state
def me_unbookmark(state, id_or_url):
    """Remove a bookmark."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.unbookmark_tweet(tid)
    state.output(data, "Unbookmarked")


# ============================================================
# quick actions (top-level)
# ============================================================

@cli.command("like")
@click.argument("id_or_url")
@pass_state
def like(state, id_or_url):
    """Like a tweet.

    NOTE: As of Aug 2025, the like endpoint was removed from the Free API tier.
    This command only works on paid tiers (Basic, Pro, Enterprise).
    """
    tid = parse_tweet_id(id_or_url)
    click.echo(
        "Warning: The like endpoint was removed from the Free API tier in Aug 2025. "
        "This only works on paid tiers (Basic, Pro, Enterprise).",
        err=True,
    )
    data = state.client.like_tweet(tid)
    state.output(data, "Liked")


@cli.command("retweet")
@click.argument("id_or_url")
@pass_state
def retweet(state, id_or_url):
    """Retweet a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.retweet(tid)
    state.output(data, "Retweeted")


# ============================================================
# auth (OAuth 2.0 interactive flow)
# ============================================================

@cli.group()
def auth():
    """OAuth 2.0 authorization (required for bookmarks endpoint)."""


@auth.command("login")
@click.option("--redirect-uri", default=None,
              help="Must match one registered in the X developer portal. "
                   "Falls back to $X_OAUTH2_REDIRECT_URI.")
@click.option("--scopes", default=",".join(oauth2.DEFAULT_SCOPES),
              help="Comma-separated OAuth 2.0 scopes.")
def auth_login(redirect_uri, scopes):
    """Interactive OAuth 2.0 PKCE flow. Prints an auth URL, prompts for the pasted-back code."""
    creds = load_credentials()
    if not (creds.oauth2_client_id and creds.oauth2_client_secret):
        raise click.ClickException(
            "X_OAUTH2_CLIENT_ID / X_OAUTH2_CLIENT_SECRET not set."
        )
    redirect_uri = redirect_uri or os.environ.get("X_OAUTH2_REDIRECT_URI")
    if not redirect_uri:
        raise click.ClickException(
            "No redirect URI. Pass --redirect-uri or set X_OAUTH2_REDIRECT_URI. "
            "Must match one registered in the X dev portal (e.g. http://localhost:8080/callback)."
        )
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    url, state, verifier = oauth2.build_authorize_url(
        creds.oauth2_client_id, redirect_uri, scope_list,
    )
    click.echo("\n1. Open this URL in a browser and authorize:\n")
    click.echo(url)
    click.echo(
        "\n2. After authorizing, you will be redirected to a URL like:\n"
        f"   {redirect_uri}?state=...&code=...\n"
        "3. Paste the FULL redirect URL (or just the code) below.\n"
    )
    pasted = click.prompt("redirect URL or code", type=str).strip()
    code = pasted
    returned_state = None
    if pasted.startswith("http"):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        code = (qs.get("code") or [""])[0]
        returned_state = (qs.get("state") or [None])[0]
    if not code:
        raise click.ClickException("No code found in pasted input.")
    if returned_state is not None and returned_state != state:
        raise click.ClickException(f"State mismatch (got {returned_state!r}, expected {state!r})")
    tokens = oauth2.exchange_code(
        creds.oauth2_client_id, creds.oauth2_client_secret,
        code, verifier, redirect_uri,
    )
    oauth2.save_tokens(tokens)
    click.echo(f"\nSaved tokens to {oauth2.TOKEN_PATH}")


@auth.command("status")
def auth_status():
    """Show OAuth 2.0 token status."""
    tokens = oauth2.load_tokens()
    if not tokens:
        click.echo(f"No tokens at {oauth2.TOKEN_PATH}. Run: x-cli auth login")
        return
    import time as _t
    exp = tokens.get("expires_at", 0)
    remaining = exp - int(_t.time())
    state = "valid" if remaining > 0 else "expired (will refresh)"
    click.echo(f"path:       {oauth2.TOKEN_PATH}")
    click.echo(f"state:      {state}")
    click.echo(f"expires_in: {remaining}s")
    click.echo(f"scopes:     {tokens.get('scope', '(unknown)')}")
    click.echo(f"refresh:    {'yes' if tokens.get('refresh_token') else 'no'}")


def main():
    cli()


if __name__ == "__main__":
    main()
