"""Entrypoint: `python -m triage_bot`. Reads env, fails loud on missing required vars."""

import os

from fastmail_adapter import FastmailAdapter
from triage_bot import build_application

REQUIRED_ENV_VARS = (
    "FASTMAIL_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
)


def main():
    _require_env(REQUIRED_ENV_VARS)
    adapter = FastmailAdapter(token=os.environ["FASTMAIL_TOKEN"])
    application = build_application(
        adapter=adapter,
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        allowed_user_id=os.environ["TELEGRAM_ALLOWED_USER_ID"],
        nudge_schedule=os.environ.get("NUDGE_SCHEDULE"),
    )
    application.run_polling()


def _require_env(names):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            f"Required env vars not set: {', '.join(missing)}. "
            "Set these in your environment (or .env) before starting the bot."
        )


if __name__ == "__main__":
    main()
