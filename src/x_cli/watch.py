"""Watch mode: poll accounts for new tweets in real-time."""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console

from .api import RateLimitError, XApiClient
from .formatters import format_output

_stderr = Console(stderr=True)


@dataclass
class WatchTarget:
    """A user being watched."""

    username: str
    user_id: str
    last_seen_id: str | None = None


@dataclass
class WatchStats:
    """Accumulated stats for the session."""

    tweets_seen: int = 0
    polls: int = 0
    per_user: dict[str, int] = field(default_factory=dict)


def _matches_filters(text: str, filters: list[str]) -> bool:
    """Return True if tweet text matches any of the filter keywords (case-insensitive)."""
    if not filters:
        return True
    text_lower = text.lower()
    return any(f.lower() in text_lower for f in filters)


def _notify(username: str, text: str) -> None:
    """Send a desktop notification (macOS only, silent fail elsewhere)."""
    if platform.system() != "Darwin":
        print("\a", end="", flush=True)  # terminal bell fallback
        return
    preview = text[:100].replace('"', '\\"').replace("\n", " ")
    script = f'display notification "{preview}" with title "x-cli: @{username}"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def _seed_last_seen(client: XApiClient, target: WatchTarget) -> None:
    """Fetch the most recent tweet ID so we only show new ones."""
    try:
        data = client.get_timeline(target.user_id, max_results=5)
        tweets = data.get("data", [])
        if tweets:
            target.last_seen_id = tweets[0]["id"]
    except RuntimeError:
        pass


def _print_summary(stats: WatchStats, targets: list[WatchTarget]) -> None:
    _stderr.print()
    _stderr.print("[bold]Watch session summary[/bold]")
    _stderr.print(f"  Polls: {stats.polls}")
    _stderr.print(f"  Tweets seen: {stats.tweets_seen}")
    for t in targets:
        count = stats.per_user.get(t.username, 0)
        _stderr.print(f"  @{t.username}: {count} new tweets")


def watch_loop(
    client: XApiClient,
    targets: list[WatchTarget],
    interval: int,
    filters: list[str],
    notify: bool,
    max_tweets: int | None,
    mode: str,
    verbose: bool,
) -> None:
    """Main polling loop. Runs until Ctrl+C or max_tweets reached."""
    stats = WatchStats()

    # Seed last_seen_id for each target so we skip existing tweets
    _stderr.print("[dim]Initializing watch...[/dim]")
    for target in targets:
        _seed_last_seen(client, target)
        _stderr.print(f"[dim]  Tracking @{target.username} (id={target.user_id})[/dim]")

    usernames = ", ".join(f"@{t.username}" for t in targets)
    _stderr.print(f"[bold green]Watching {usernames}[/bold green] (every {interval}s, Ctrl+C to stop)")
    if filters:
        _stderr.print(f"[dim]Filters: {', '.join(filters)}[/dim]")
    _stderr.print()

    try:
        while True:
            for target in targets:
                try:
                    data = client.get_timeline(
                        target.user_id,
                        max_results=10,
                        since_id=target.last_seen_id,
                    )
                except RateLimitError as e:
                    reset_ts = e.reset_at
                    try:
                        wait = max(0, int(reset_ts) - int(time.time())) + 5
                    except ValueError:
                        wait = 60
                    _stderr.print(f"[yellow]Rate limited. Waiting {wait}s...[/yellow]")
                    time.sleep(wait)
                    continue
                except RuntimeError as exc:
                    _stderr.print(f"[red]Error for @{target.username}: {exc}[/red]")
                    continue

                tweets = data.get("data", [])
                if not tweets:
                    continue

                includes = data.get("includes", {})

                # Tweets come newest-first; process oldest-first for chronological output
                for tweet in reversed(tweets):
                    text = tweet.get("text", "")
                    note = tweet.get("note_tweet", {})
                    if note and note.get("text"):
                        text = note["text"]

                    if not _matches_filters(text, filters):
                        continue

                    # Build a single-tweet payload for the formatter
                    payload: dict[str, Any] = {
                        "data": tweet,
                        "includes": includes,
                    }
                    format_output(payload, mode, f"@{target.username}", verbose=verbose)

                    if notify:
                        _notify(target.username, text)

                    stats.tweets_seen += 1
                    stats.per_user[target.username] = stats.per_user.get(target.username, 0) + 1

                    if max_tweets and stats.tweets_seen >= max_tweets:
                        _stderr.print(f"\n[bold]Reached --max {max_tweets} tweets.[/bold]")
                        _print_summary(stats, targets)
                        return

                # Update cursor to newest tweet
                target.last_seen_id = tweets[0]["id"]

            stats.polls += 1
            time.sleep(interval)

    except KeyboardInterrupt:
        _print_summary(stats, targets)
