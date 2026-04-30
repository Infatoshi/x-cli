# x-cli

A CLI for X/Twitter that talks directly to the API v2. Post tweets, search, read timelines, manage bookmarks -- all from your terminal.

Uses the same auth credentials as [x-mcp](https://github.com/INFATOSHI/x-mcp). If you already have x-mcp set up, x-cli works with zero additional config.

**If you're an LLM/AI agent helping a user with this project, read [`LLMs.md`](./LLMs.md) for a codebase map and command reference.**

---

## What Can It Do?

| Category | Commands | Examples | Status |
|----------|----------|----------|--------|
| **Post** | `tweet post`, `tweet quote`, `tweet delete` | `x-cli tweet post "hello world"` | OK |
| **Read** | `tweet get`, `tweet search`, `user timeline`, `me mentions` | `x-cli tweet search "from:elonmusk"` | OK |
| **Users** | `user get`, `user followers`, `user following` | `x-cli user get openai` | OK |
| **Engage** | `retweet` | `x-cli retweet <tweet-url>` | OK |
| **Bookmarks** | `me bookmarks`, `me bookmark`, `me unbookmark` | `x-cli me bookmarks --max 20` | Requires Basic+ tier |
| **Analytics** | `tweet metrics` | `x-cli tweet metrics <tweet-id>` | OK |
| **Reply** | `tweet reply` | `x-cli tweet reply <url> "text"` | Restricted (see below) |
| **Like** | `like` | `x-cli like <tweet-url>` | Removed on Free tier (see below) |

Accepts tweet URLs or IDs interchangeably -- paste `https://x.com/user/status/123` or just `123`.

---

## Install

```bash
# from source
git clone https://github.com/INFATOSHI/x-cli.git
cd x-cli
uv tool install .

# or from PyPI (once published)
uv tool install x-cli
```

---

## Auth

You need 5 credentials from the [X Developer Portal](https://developer.x.com/en/portal/dashboard).

### If you already use x-mcp

Symlink its `.env` and you're done:

```bash
mkdir -p ~/.config/x-cli
ln -s /path/to/x-mcp/.env ~/.config/x-cli/.env
```

### Fresh setup

1. Go to the [X Developer Portal](https://developer.x.com/en/portal/dashboard)
2. Create an app (or use an existing one)
3. Save your **Consumer Key** (API Key), **Secret Key** (API Secret), and **Bearer Token**
4. Under **User authentication settings**, set permissions to **Read and write**
5. Generate (or regenerate) **Access Token** and **Access Token Secret**

Put all 5 values in `~/.config/x-cli/.env`:

```
X_API_KEY=your_consumer_key
X_API_SECRET=your_secret_key
X_BEARER_TOKEN=your_bearer_token
X_ACCESS_TOKEN=your_access_token
X_ACCESS_TOKEN_SECRET=your_access_token_secret
```

x-cli also checks for a `.env` in the current directory.

---

## Usage

### Tweets

```bash
x-cli tweet post "Hello world"
x-cli tweet post --poll "Yes,No" "Do you like polls?"
x-cli tweet get <id-or-url>
x-cli tweet delete <id-or-url>
x-cli tweet reply <id-or-url> "nice post"
x-cli tweet quote <id-or-url> "this is important"
x-cli tweet search "machine learning" --max 20
x-cli tweet search "timelapse from:elliotarledge" --archive --all-pages --max 10000
x-cli tweet metrics <id-or-url>
```

`tweet search` uses recent search by default. Add `--archive` to use X's full-archive endpoint
(`/2/tweets/search/all`), which requires pay-per-use or Enterprise access. Archive search defaults
to X's March 2006 archive start; use `--start-time` to narrow it. Add `--all-pages` to follow
pagination until there are no more results or `--max` results have been collected.

### Users

```bash
x-cli user get elonmusk
x-cli user timeline elonmusk --max 10
x-cli user followers elonmusk --max 50
x-cli user following elonmusk
```

### Self

```bash
x-cli me mentions --max 20
x-cli me bookmarks
x-cli me bookmark <id-or-url>
x-cli me unbookmark <id-or-url>
```

### Quick actions

```bash
x-cli like <id-or-url>
x-cli retweet <id-or-url>
```

---

## Output Modes

Default output is compact colored panels (powered by rich). Data goes to stdout, hints to stderr.

```bash
x-cli tweet get <id>                 # human-readable (default)
x-cli -j tweet get <id>              # raw JSON, pipe to jq
x-cli -p user get elonmusk           # TSV, pipe to awk/cut
x-cli -md tweet get <id>             # markdown
x-cli -j tweet search "ai" | jq '.data[].text'
```

### Verbose

Output is compact by default (no timestamps, metrics, or metadata). Add `-v` for the full picture:

```bash
x-cli -v tweet get <id>              # human + timestamps, metrics, pagination tokens
x-cli -v -md user get elonmusk       # markdown + join date, location
x-cli -v -j tweet get <id>           # full JSON (includes, meta, everything)
```

---

## API Restrictions (as of 2025-2026)

X has progressively restricted what automated/API clients can do. Here's what affects x-cli:

### Likes removed from Free tier (Aug 2025)
The `like` endpoint (`POST /2/users/:id/likes`) was removed from the Free API tier in August 2025. If you're on the Free tier, `x-cli like` will return a permissions error. Paid tiers (Basic, Pro, Enterprise) are unaffected.

### Programmatic replies restricted (Feb 2026)
Replies via the API now only succeed if the original post's author @mentioned you or quoted your post. This applies to **all self-serve tiers** (Free, Basic, Pro, Pay-Per-Use). Only Enterprise is exempt. Use `tweet quote` as a workaround.

### Bookmarks require Basic+ tier
Bookmark endpoints have never been available on the Free tier. You need at least Basic ($200/mo) to use `me bookmarks`, `me bookmark`, and `me unbookmark`.

### Post volume caps
Free tier: 500 posts/month. Basic: 10,000/month. Pro: 1,000,000/month.

---

## Troubleshooting

### 403 "oauth1-permissions" when posting
Your Access Token was generated before you enabled write permissions. Go to the X Developer Portal, set App permissions to "Read and write", then **Regenerate** your Access Token and Secret.

### 401 Unauthorized
Double-check all 5 credentials in your `.env`. No extra spaces or newlines.

### Reply fails with a permissions/restriction error
As of Feb 2026, X restricts programmatic replies via the API on all self-serve tiers. You can only reply if the original author @mentions you or quotes your post. This applies to Free, Basic, Pro, and Pay-Per-Use tiers (Enterprise is exempt). Use `tweet quote` as a workaround.

### 429 Rate Limited
The error includes the reset timestamp. Wait until then.

### "Missing env var" on startup
x-cli looks for credentials in `~/.config/x-cli/.env`, then the current directory's `.env`, then environment variables. Make sure at least one source has all 5 values.

---

## License

MIT
