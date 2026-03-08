# LLMs.md -- Guide for AI Agents

You are an AI agent working with the x-cli codebase. This file tells you where everything is and how it fits together.

---

## What This Is

x-cli is a Python CLI that talks directly to the Twitter/X API v2. It uses:
- OAuth 1.0a for user-context write/engagement endpoints (tweet post/delete, like, retweet, mentions).
- App Bearer token for public read endpoints.
- OAuth 2.0 User Context (PKCE) for bookmarks endpoints.

No third-party auth frameworks are used; OAuth signing/challenge logic is implemented in project code.

It shares static credentials with x-mcp via `~/.config/x-cli/.env`. Mutable OAuth2 token keys are stored in `~/.config/x-cli/.env.auth2`.

---

## Project Structure

```
src/x_cli/
    cli.py          -- Click command groups and entry point
    api.py          -- XApiClient: endpoint methods + auth routing
    auth.py         -- Env loading + OAuth 1.0a HMAC-SHA1 signing
    oauth2.py       -- OAuth2 PKCE helpers, token exchange/refresh, token persistence
    formatters.py   -- Human (rich), JSON, and TSV output modes
    utils.py        -- Tweet ID parsing from URLs, username stripping
tests/
    test_api.py
    test_cli_auth.py
    test_oauth2.py
    test_utils.py
    test_formatters.py
    test_auth.py
```

---

## Codebase Map

### `cli.py` -- Start here

The entry point. Defines Click command groups: `auth`, `tweet`, `user`, `me`, plus top-level `like` and `retweet`. Most commands follow the same pattern: parse args, call the API client, pass the response to a formatter.

The `State` object holds the output mode (`human`/`json`/`plain`/`markdown`) and verbose flag, and lazily initializes the API client. It's passed via Click's context system (`@pass_state`).

Global flags: `-j`/`--json`, `-p`/`--plain`, `-md`/`--markdown` control output mode. `-v`/`--verbose` adds timestamps, metrics, metadata, and pagination tokens. Default is compact human-readable rich output (non-verbose).

### `api.py` -- API client

`XApiClient` wraps all Twitter API v2 endpoints. Key patterns:

- **Read-only endpoints** (get_tweet, search, get_user, get_timeline, get_followers, get_following) use app Bearer token auth.
- **OAuth 1.0a endpoints** (post_tweet, delete_tweet, like, retweet, mentions) use `_oauth_request()`.
- **OAuth 2.0 user-context endpoints** (bookmarks) use `_oauth2_user_request()`.
- `get_authenticated_user_id()` caches OAuth1 user id; `get_authenticated_user_id_oauth2()` caches OAuth2 user id.
- OAuth2 refresh is automatic using stored refresh token and expiry metadata.
- OAuth2 token exchange/refresh optionally uses `X_OAUTH2_CLIENT_SECRET` for app types that require client authentication.

All methods return raw `dict` parsed from the API JSON response. Error handling is in `_handle()` -- raises `RuntimeError` on non-2xx or rate limit responses.

### `auth.py` -- Env + OAuth1 signing

Two responsibilities:

1. **`load_credentials()`** -- Loads static vars from `~/.config/x-cli/.env` and current directory `.env`, then overlays mutable OAuth2 token vars from `~/.config/x-cli/.env.auth2`.
2. **`generate_oauth_header()`** -- Builds an OAuth 1.0a `Authorization` header using HMAC-SHA1. Follows the standard OAuth signature base string construction: percent-encode params, sort, concatenate with `&`, sign with consumer secret + token secret.

Query string parameters from the URL are included in the signature base string (required by OAuth spec).

### `oauth2.py` -- OAuth2 PKCE + token management

- Generates PKCE verifier/challenge/state.
- Builds browser authorization URL.
- Parses redirected URL for code/state validation (user must paste full browser address-bar URL).
- Exchanges authorization code for tokens and refreshes access token.
- Persists/removes OAuth2 token env vars in `~/.config/x-cli/.env.auth2`.
- Auto-migrates legacy token keys from `~/.config/x-cli/.env` to `.env.auth2`.

### `formatters.py` -- Output

Four modes routed by `format_output(data, mode, title, verbose)`:

- **`human`** -- Rich panels for single tweets/users, rich tables for lists. Resolves author IDs to usernames using the `includes.users` array from API responses. Hints and progress go to stderr via `Console(stderr=True)`.
- **`json`** -- Non-verbose strips `includes`/`meta` and emits just `data`. Verbose emits the full response.
- **`plain`** -- TSV format. Non-verbose shows only key columns (id, author_id, text, created_at for tweets; username, name, description for users). Verbose shows all fields.
- **`markdown`** -- Markdown output. Tweets as `## heading` with bold author. Users as heading with metrics. Lists of users become markdown tables. Non-verbose omits timestamps and per-tweet metrics.

### `utils.py` -- Helpers

- **`parse_tweet_id(input)`** -- Extracts numeric tweet ID from `x.com` or `twitter.com` URLs, or validates raw numeric strings. Raises `ValueError` on invalid input.
- **`strip_at(username)`** -- Removes leading `@` if present.

---

## Command Reference

### Tweet commands (`x-cli tweet <action>`)

| Command | Args | Flags | API method |
|---------|------|-------|------------|
| `post` | `TEXT` | `--poll OPTIONS` `--poll-duration MINS` | `post_tweet()` |
| `get` | `ID_OR_URL` | | `get_tweet()` |
| `delete` | `ID_OR_URL` | | `delete_tweet()` |
| `reply` | `ID_OR_URL` `TEXT` | | `post_tweet(reply_to=)` -- **Restricted**: only works if original author @mentioned you or quoted your post |
| `quote` | `ID_OR_URL` `TEXT` | | `post_tweet(quote_tweet_id=)` |
| `search` | `QUERY` | `--max N` | `search_tweets()` |
| `metrics` | `ID_OR_URL` | | `get_tweet_metrics()` |

### User commands (`x-cli user <action>`)

| Command | Args | Flags | API method |
|---------|------|-------|------------|
| `get` | `USERNAME` | | `get_user()` |
| `timeline` | `USERNAME` | `--max N` | `get_user()` then `get_timeline()` |
| `followers` | `USERNAME` | `--max N` | `get_user()` then `get_followers()` |
| `following` | `USERNAME` | `--max N` | `get_user()` then `get_following()` |

Note: `timeline`, `followers`, `following` resolve username to numeric ID automatically via `get_user()`.

### Self commands (`x-cli me <action>`)

| Command | Args | Flags | API method |
|---------|------|-------|------------|
| `mentions` | | `--max N` | `get_mentions()` |
| `bookmarks` | | `--max N` | `get_bookmarks()` (OAuth2 login required) |
| `bookmark` | `ID_OR_URL` | | `bookmark_tweet()` (OAuth2 login required) |
| `unbookmark` | `ID_OR_URL` | | `unbookmark_tweet()` (OAuth2 login required) |

### Auth commands (`x-cli auth <action>`)

| Command | Purpose |
|---------|---------|
| `login` | Run OAuth2 PKCE browser flow; store tokens |
| `status` | Show OAuth2 token presence/expiry |
| `logout` | Remove stored OAuth2 tokens |

### Top-level commands

| Command | Args | API method |
|---------|------|------------|
| `like` | `ID_OR_URL` | `like_tweet()` |
| `retweet` | `ID_OR_URL` | `retweet()` |

---

## Common Patterns

**Adding a new API endpoint:**
1. Add the method to `XApiClient` in `api.py`
2. Add a Click command in `cli.py` that calls it
3. The formatter handles the response automatically (it's generic over any dict/list structure)

**User commands that need a numeric ID:**
The Twitter API v2 requires numeric user IDs for timeline/followers/following endpoints. The CLI resolves usernames to IDs automatically -- see `user_timeline()` in `cli.py` for the pattern.

**Search query syntax:**
`search_tweets` supports X's full query language: `from:user`, `to:user`, `#hashtag`, `"exact phrase"`, `has:media`, `is:reply`, `-is:retweet`, `lang:en`. Combine with spaces (AND) or `OR`.

---

## Testing

```bash
uv run pytest tests/ -v
```

Tests cover utils, formatters, OAuth1 signing, OAuth2 helpers, API auth routing, and auth CLI command behavior. No live API calls in tests.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| 403 "oauth1-permissions" | Access Token is Read-only | Enable "Read and write" in app settings, regenerate Access Token |
| "Missing OAuth2 user token for bookmarks" | OAuth2 login not completed | Set `X_OAUTH2_CLIENT_ID` and run `x-cli auth login` |
| X consent page says "Something went wrong" | Callback URL mismatch | Configure callback exactly as `https://example.com/oauth/callback` (or set matching `X_OAUTH2_REDIRECT_URI`) |
| "OAuth2 token request failed (HTTP 401): Missing valid authorization header" | App requires OAuth2 client authentication for token exchange | Set `X_OAUTH2_CLIENT_SECRET` and retry `x-cli auth login` |
| "X_OAUTH2_ACCESS_TOKEN is not a user-context token" | Token is OAuth2 app-only bearer token | Run `x-cli auth login` and use returned user-context token |
| 401 on bookmarks after login | OAuth2 token expired/revoked and refresh failed | Re-run `x-cli auth login` |
| 401 Unauthorized | Bad credentials | Verify all 5 values in `.env` |
| Reply fails / restriction error | X restricts programmatic replies (Feb 2024) | Can only reply if original author @mentioned you or quoted your post. Use `tweet quote` instead |
| 429 Rate Limited | Too many requests | Error includes reset timestamp |
| "Missing env var" | Static `.env` missing required keys | Check `~/.config/x-cli/.env` (and optional cwd `.env`) |
| `RuntimeError: API error` | Twitter API returned an error | Check the error message for details (usually permissions or invalid IDs) |
