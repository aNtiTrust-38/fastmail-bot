# fastmail-bot

A Telegram-driven inbox-triage bot for a [Fastmail](https://www.fastmail.com/) mailbox. It presents unread mail **one item at a time** with tap-to-act buttons, so each triage decision is made deliberately after seeing the message — nothing is filed automatically.

## What it is

Send `/mail` to the bot and it walks you through your unread mail one message at a time. Each message shows sender, subject, folder, date, and a preview, with an inline keyboard:

- **Mark read** — set the message read; it drops from the queue.
- **Mark unread** — clear the read flag so the message resurfaces next session.
- **Archive** — move out of the inbox into the archive folder.
- **📌 Pin** — flag the message (`$flagged`) so it stays surfaced and pinned in Fastmail.
- **Move ▸** — pick a destination folder from your live folder list.
- **🗑 Trash** — move to Trash (with a confirm step). Reversible — never a permanent delete.
- **Skip** — move on without changing anything.

It triages **unread mail in the inbox, plus unread *pinned* mail in any folder**. Pinning (`$flagged`) acts as a user-controlled allowlist: set up server-side rules that pin the folders you want surfaced, and only those folders reach the triage queue. Changing what surfaces is a mail-rule change, not a code change.

An optional once-daily nudge messages you the unread count.

It is **read + file only** — there is no compose, reply, or send capability.

## Why

A large inbox becomes a wall of text, and a wall of text becomes unprocessable. Server-side filing rules can make it worse by routing mail out of sight before it is ever seen. This bot reframes triage as a sequence of small, bounded, one-at-a-time decisions, and keeps "what surfaces" under explicit user control via pinning.

## Architecture

```
Telegram  ──>  triage_bot  ──>  FastmailAdapter  ──>  Fastmail JMAP API
              (handlers,        (nine verbs,          (raw HTTP via
               inline kbd)       provider-neutral)     `requests`)
```

- **`FastmailAdapter`** — talks to Fastmail's JMAP API directly over `requests`. Nine verbs: `list_unread`, `get_email`, `list_mailboxes` (read) and `archive`, `move`, `mark_read`, `mark_unread`, `flag`, `trash` (write). Read verbs and write verbs are separated — the read path has no write capability. `trash` is a move to the Trash folder; there is no destroy call anywhere.
- **`triage_bot`** — the Telegram layer: the `/mail` command, a callback handler dispatching the inline buttons onto adapter verbs, and the scheduled nudge. An allowed-user gate means only the configured Telegram ID can drive the bot.
- The adapter interface is **provider-neutral** by design — the triage layer never sees provider-specific shapes.

## Requirements

- Python 3.11+
- A Fastmail account and a JMAP **API token**
- A Telegram **bot token** (from [@BotFather](https://t.me/BotFather))
- Your numeric Telegram **user ID** (from [@userinfobot](https://t.me/userinfobot))

## Configuration

The bot reads everything from environment variables. Copy `.env.example` to `.env` for local development, or set them in your host's dashboard.

| Variable | Required | What it is |
|---|---|---|
| `FASTMAIL_TOKEN` | yes | Fastmail JMAP API token — Fastmail Settings → Security → API Tokens. |
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from @BotFather. |
| `TELEGRAM_ALLOWED_USER_ID` | yes | Your numeric Telegram user ID — the bot ignores every other ID. |
| `NUDGE_SCHEDULE` | no | Daily nudge time, `HH:MM` or `HHMM` (e.g. `1600`). Empty/unset disables the nudge. |
| `TZ` | no | IANA timezone for the nudge (e.g. `America/New_York`). Hosts often default to UTC; set this so the nudge fires at the right wall-clock hour. |

Secrets are read from the environment only — never commit real values.

## Deploy

The repo includes a `Dockerfile` (`python:3.11-slim` → `pip install .` → `python -m triage_bot`). Deploying from the Dockerfile makes the build deterministic — a platform's auto-detecting builder will not reliably install dependencies from a bare `pyproject.toml`, so the Dockerfile is the supported path.

On [Railway](https://railway.app/) (or any container host): point a service at this repo, set the environment variables above, and deploy. The process is a long-running worker — it polls Telegram; no inbound webhook needed.

Locally:

```sh
pip install .
python -m triage_bot
```

## Usage

- DM the bot `/mail` to start a triage session; it shows the first unread item with the action buttons.
- Tap a button to act and advance to the next item.
- The queue is a fresh snapshot each `/mail`; items you mark read drop out, and an item is re-checked against current unread state right before it is shown, so mail you handled elsewhere is skipped silently.
- If `NUDGE_SCHEDULE` is set, the bot sends one message a day with the unread count.

## Security

- **Single-user by design.** The allowed-user gate means only the configured `TELEGRAM_ALLOWED_USER_ID` can issue commands or tap buttons; all other senders are ignored.
- **Secrets are environment-only** — never committed, never logged. Error messages sent to Telegram are scrubbed of the API token.
- **No permanent deletion.** Trash is a reversible folder move; the bot never issues a destroy.

## License

MIT — see `LICENSE`.

## Status

A personal project, shared publicly in case it is useful. Provided as-is, with no support guarantee.
