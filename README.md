# x-cli

A CLI for X/Twitter that talks directly to the API v2. Post tweets, search, read timelines, and manage engagement from your terminal.

Uses the same auth credentials as [x-mcp](https://github.com/INFATOSHI/x-mcp). If you already have x-mcp set up, x-cli works with zero additional config.

**If you're an LLM/AI agent helping a user with this project, read [`LLMs.md`](./LLMs.md) for a codebase map and command reference.**

---

## What Can It Do?

| Category | Commands | Examples |
|----------|----------|----------|
| **Post** | `tweet post`, `tweet reply`, `tweet quote`, `tweet delete` | `x-cli tweet post "hello world"` |
| **Read** | `tweet get`, `tweet search`, `user timeline`, `me mentions` | `x-cli tweet search "from:elonmusk"` |
| **Users** | `user get`, `user followers`, `user following` | `x-cli user get openai` |
| **Engage** | `like`, `retweet` | `x-cli like <tweet-url>` |
| **Bookmarks** | `me bookmarks`, `me bookmark`, `me unbookmark` | `Currently blocked by X auth requirements (OAuth2 user context)` |
| **Analytics** | `tweet metrics` | `x-cli tweet metrics <tweet-id>` |

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
x-cli tweet metrics <id-or-url>
```

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

Note: X currently requires OAuth 2.0 User Context for bookmarks endpoints. This CLI's auth model is OAuth 1.0a + app bearer token, so bookmark commands are not available yet.

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

## Troubleshooting

### 403 "oauth1-permissions" when posting
Your Access Token was generated before you enabled write permissions. Go to the X Developer Portal, set App permissions to "Read and write", then **Regenerate** your Access Token and Secret.

### 401 Unauthorized
Double-check all 5 credentials in your `.env`. No extra spaces or newlines.

### Reply fails with a permissions/restriction error
As of Feb 2024, X restricts programmatic replies via the API. You can only reply if the original author @mentions you or quotes your post. This applies to Free, Basic, Pro, and Pay-Per-Use tiers (Enterprise is exempt). Use `tweet quote` as a workaround.

### 403 "Unsupported Authentication" on bookmarks
X's bookmarks endpoints require OAuth 2.0 User Context. x-cli currently uses OAuth 1.0a user tokens plus app bearer token, so `me bookmarks`, `me bookmark`, and `me unbookmark` cannot be used until OAuth2 user-context auth is added.

### 429 Rate Limited
The error includes the reset timestamp. Wait until then.

### "Missing env var" on startup
x-cli looks for credentials in `~/.config/x-cli/.env`, then the current directory's `.env`, then environment variables. Make sure at least one source has all 5 values.

---

## License

MIT
