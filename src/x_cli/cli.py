"""Click CLI for x-cli."""

from __future__ import annotations

import os
import time

import click
import httpx

from .api import XApiClient
from .auth import get_config_auth2_env_path, load_credentials, load_env_files
from .formatters import format_output
from .oauth2 import (
    DEFAULT_REDIRECT_URI,
    build_authorization_url,
    clear_oauth2_tokens,
    exchange_code_for_token,
    expires_at_from_expires_in,
    extract_code_from_redirect_url,
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
    persist_oauth2_tokens,
)
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
# auth
# ============================================================

@cli.group()
def auth():
    """OAuth2 authentication helpers."""


@auth.command("login")
def auth_login():
    """Run OAuth2 PKCE login for bookmarks endpoints."""
    load_env_files()
    client_id = os.environ.get("X_OAUTH2_CLIENT_ID")
    if not client_id:
        raise click.ClickException("Missing env var X_OAUTH2_CLIENT_ID.")
    client_secret = os.environ.get("X_OAUTH2_CLIENT_SECRET")

    redirect_uri = os.environ.get("X_OAUTH2_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    code_verifier = generate_code_verifier()
    state = generate_state()
    auth_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=generate_code_challenge(code_verifier),
    )

    click.echo("Open this URL in your browser and approve access:")
    click.echo(auth_url)
    click.echo("")
    click.echo(f"Use a callback URL configured in your X app (current: {redirect_uri}).")
    click.echo("Recommended callback URL: https://example.com/oauth/callback")
    redirected_url = click.prompt("Paste the full redirected URL from your browser address bar")

    try:
        code = extract_code_from_redirect_url(redirected_url, state)
        with httpx.Client(timeout=30.0) as http:
            token_data = exchange_code_for_token(
                http,
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )
    except RuntimeError as exc:
        msg = str(exc)
        if "Missing valid authorization header" in msg and not client_secret:
            msg += " Set X_OAUTH2_CLIENT_SECRET and retry `x-cli auth login`."
        raise click.ClickException(msg) from exc

    access_token = str(token_data["access_token"])
    refresh_token = token_data.get("refresh_token")
    expires_at = expires_at_from_expires_in(token_data.get("expires_in"))
    persist_oauth2_tokens(
        get_config_auth2_env_path(),
        access_token=access_token,
        refresh_token=str(refresh_token) if refresh_token else None,
        expires_at=expires_at,
    )
    if expires_at:
        ttl = max(0, expires_at - int(time.time()))
        click.echo(f"OAuth2 login successful. Token expires in about {ttl // 60} minutes.")
    else:
        click.echo("OAuth2 login successful.")


@auth.command("logout")
def auth_logout():
    """Remove stored OAuth2 tokens."""
    clear_oauth2_tokens(get_config_auth2_env_path())
    click.echo("Removed OAuth2 tokens from ~/.config/x-cli/.env.auth2")


@auth.command("status")
def auth_status():
    """Show OAuth2 login status."""
    load_env_files()
    access = os.environ.get("X_OAUTH2_ACCESS_TOKEN")
    refresh = os.environ.get("X_OAUTH2_REFRESH_TOKEN")
    expires_raw = os.environ.get("X_OAUTH2_EXPIRES_AT")
    if not access:
        click.echo("OAuth2: not logged in")
        return
    click.echo("OAuth2: logged in")
    click.echo(f"Refresh token: {'present' if refresh else 'missing'}")
    if not expires_raw:
        click.echo("Access token expiry: unknown")
        return
    try:
        expires_at = int(expires_raw)
    except ValueError:
        click.echo("Access token expiry: invalid value in X_OAUTH2_EXPIRES_AT")
        return
    remaining = expires_at - int(time.time())
    if remaining <= 0:
        click.echo("Access token expiry: expired")
    else:
        click.echo(f"Access token expiry: in {remaining // 60} minutes")


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

    NOTE: X restricts programmatic replies. You can only reply if the original
    author @mentioned you or quoted your post. Use 'tweet quote' as a workaround.
    """
    tid = parse_tweet_id(id_or_url)
    click.echo(
        "Warning: X restricts programmatic replies. This will only succeed if "
        "the original author @mentioned you or quoted your post.",
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
@click.option("--max", "max_results", default=10, type=int, help="Max results (10-100)")
@pass_state
def tweet_search(state, query, max_results):
    """Search recent tweets."""
    data = state.client.search_tweets(query, max_results)
    state.output(data, f"Search: {query}")


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
    """Like a tweet."""
    tid = parse_tweet_id(id_or_url)
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


def main():
    cli()


if __name__ == "__main__":
    main()
