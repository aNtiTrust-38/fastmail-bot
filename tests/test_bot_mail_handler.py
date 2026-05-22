"""/mail starts a session and renders the first message."""

from unittest.mock import AsyncMock, MagicMock

from telegram.ext import CommandHandler

from triage_bot import build_application
from triage_bot.bot import handle_mail

ALLOWED_USER_ID = 12345
NON_ALLOWED_USER_ID = 99999

SAMPLE_UNREAD = [
    {
        "id": "M0001",
        "from": [{"name": "Bob", "email": "bob@example.com"}],
        "subject": "Welcome",
        "received_at": "2026-05-19T10:00:00Z",
        "preview": "Hello there!",
        "mailbox_ids": ["MB0001"],
    },
    {
        "id": "M0002",
        "from": [{"name": "News", "email": "news@example.com"}],
        "subject": "Newsletter",
        "received_at": "2026-05-19T09:00:00Z",
        "preview": "Weekly digest",
        "mailbox_ids": ["MB0001", "MB0004"],
    },
]


def _make_update(user_id):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message = AsyncMock()
    return update


def _make_context(adapter, allowed_user_id=ALLOWED_USER_ID):
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": allowed_user_id}
    context.user_data = {}
    return context


def test_build_application_registers_mail_command():
    adapter = MagicMock()
    app = build_application(
        adapter=adapter,
        bot_token="123:fake-token",
        allowed_user_id=ALLOWED_USER_ID,
    )
    all_handlers = [h for hs in app.handlers.values() for h in hs]
    mail_handlers = [
        h for h in all_handlers if isinstance(h, CommandHandler) and "mail" in h.commands
    ]
    assert len(mail_handlers) == 1


async def test_mail_handler_renders_first_message_for_allowed_user():
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD

    update = _make_update(ALLOWED_USER_ID)
    context = _make_context(adapter)

    await handle_mail(update, context)

    adapter.list_unread.assert_called_once()
    update.message.reply_text.assert_called_once()
    _, kwargs = update.message.reply_text.call_args
    text = kwargs.get("text") or update.message.reply_text.call_args.args[0]
    assert "Bob" in text
    assert "Welcome" in text
    assert "2026-05-19" in text
    assert "Hello there!" in text
    assert kwargs.get("reply_markup") is not None


async def test_mail_handler_ignores_non_allowed_user():
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD

    update = _make_update(NON_ALLOWED_USER_ID)
    context = _make_context(adapter)

    await handle_mail(update, context)

    adapter.list_unread.assert_not_called()
    update.message.reply_text.assert_not_called()


async def test_mail_handler_handles_inbox_zero():
    adapter = MagicMock()
    adapter.list_unread.return_value = []

    update = _make_update(ALLOWED_USER_ID)
    context = _make_context(adapter)

    await handle_mail(update, context)

    adapter.list_unread.assert_called_once()
    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args.args[0]
    assert "zero" in text.lower() or "no unread" in text.lower() or "✓" in text


async def test_mail_handler_renders_keyboard_with_seven_actions():
    """Keyboard: Mark read / Mark unread / Archive / 📌 Pin / Move ▸ / 🗑 Trash / Skip."""
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD

    update = _make_update(ALLOWED_USER_ID)
    context = _make_context(adapter)

    await handle_mail(update, context)

    _, kwargs = update.message.reply_text.call_args
    keyboard = kwargs["reply_markup"]
    all_buttons = [b for row in keyboard.inline_keyboard for b in row]
    callback_actions = {b.callback_data.split(":")[0] for b in all_buttons}
    assert callback_actions == {
        "mark_read",
        "mark_unread",
        "archive",
        "pin",
        "move",
        "trash_confirm",
        "skip",
    }
    labels = {b.text for b in all_buttons}
    assert "Mark unread" in labels
    assert "📌 Pin" in labels
    # No unpin/unflag counterpart — mark-read is the "triaged" action.
    assert "unpin" not in callback_actions
    assert "unflag" not in callback_actions
    for button in all_buttons:
        assert button.callback_data.endswith(":M0001")


async def test_mail_handler_seeds_queue_state_in_user_data():
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD

    update = _make_update(ALLOWED_USER_ID)
    context = _make_context(adapter)

    await handle_mail(update, context)

    assert context.user_data["triage_queue"] == ["M0001", "M0002"]
    assert context.user_data["triage_index"] == 0
    assert context.user_data["triage_messages"]["M0001"]["subject"] == "Welcome"
