"""Error surfacing — fail-loud and secret-safe."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from triage_bot.bot import _safe_error_text, handle_callback, handle_mail, nudge_job

ALLOWED_USER_ID = 12345

SAMPLE_MSG = {
    "id": "M0001",
    "from": [{"name": "Bob", "email": "bob@example.com"}],
    "subject": "Welcome",
    "received_at": "2026-05-19T10:00:00Z",
    "preview": "Hello there!",
    "mailbox_ids": ["MB0001"],
}


def _make_mail_update():
    update = MagicMock()
    update.effective_user.id = ALLOWED_USER_ID
    update.message = AsyncMock()
    return update


def _make_callback_update(callback_data):
    update = MagicMock()
    update.effective_user.id = ALLOWED_USER_ID
    update.callback_query = AsyncMock()
    update.callback_query.data = callback_data
    return update


def _seeded_context(adapter):
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}
    context.user_data = {
        "triage_queue": ["M0001"],
        "triage_messages": {"M0001": SAMPLE_MSG},
        "triage_index": 0,
    }
    return context


def test_safe_error_text_redacts_token_if_present():
    adapter = MagicMock()
    adapter._token = "fmu1-secret-do-not-leak"

    exc = Exception(f"auth failed with token {adapter._token}")
    result = _safe_error_text(exc, adapter)

    assert "fmu1-secret-do-not-leak" not in result
    assert "[REDACTED]" in result


def test_safe_error_text_passes_message_through_when_no_token_present():
    adapter = MagicMock()
    adapter._token = "fmu1-secret"

    exc = Exception("auth failed (no token in this message)")
    result = _safe_error_text(exc, adapter)

    assert "auth failed" in result
    assert "[REDACTED]" not in result


async def test_handle_mail_surfaces_adapter_error_without_leaking_token():
    SECRET = "fmu1-secret-leak"
    adapter = MagicMock()
    adapter._token = SECRET
    adapter.list_unread.side_effect = Exception(f"auth failed with {SECRET}")

    update = _make_mail_update()
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}
    context.user_data = {}

    # Must not crash.
    await handle_mail(update, context)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args.args[0]
    assert SECRET not in text
    assert "Error" in text or "⚠" in text


@pytest.mark.parametrize(
    "callback_data,failing_method",
    [
        ("mark_read:M0001", "mark_read"),
        ("archive:M0001", "archive"),
        ("trash_yes:M0001", "trash"),
        ("move:M0001", "list_mailboxes"),
        ("move_to:M0001:MB0099", "move"),
    ],
)
async def test_handle_callback_surfaces_adapter_error_without_leaking_token(
    callback_data,
    failing_method,
):
    SECRET = "fmu1-secret-leak"
    adapter = MagicMock()
    adapter._token = SECRET
    getattr(adapter, failing_method).side_effect = Exception(f"call failed with token={SECRET}")

    update = _make_callback_update(callback_data)
    context = _seeded_context(adapter)

    # Must not crash.
    await handle_callback(update, context)

    update.callback_query.edit_message_text.assert_called_once()
    call = update.callback_query.edit_message_text.call_args
    text = call.args[0] if call.args else call.kwargs.get("text", "")
    assert SECRET not in text
    assert "Error" in text or "⚠" in text


async def test_nudge_job_surfaces_adapter_error_without_leaking_token():
    SECRET = "fmu1-secret-leak"
    adapter = MagicMock()
    adapter._token = SECRET
    adapter.list_unread.side_effect = Exception(f"auth failed with {SECRET}")

    context = MagicMock()
    context.bot = AsyncMock()
    context.job.data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}

    # Must not crash.
    await nudge_job(context)

    context.bot.send_message.assert_called_once()
    text = context.bot.send_message.call_args.kwargs["text"]
    assert SECRET not in text
    assert "Error" in text or "⚠" in text
