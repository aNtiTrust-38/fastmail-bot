"""Folder name in the digest.

Each triaged item shows which folder it lives in, so the user can tell a pinned
folder alert apart from an inbox item. Ids are resolved to names via
list_mailboxes(), fetched once per /mail session and cached in user_data —
not re-fetched per item. Read-only: rendering issues no write verb.
"""

from unittest.mock import AsyncMock, MagicMock

from triage_bot.bot import handle_callback, handle_mail

ALLOWED_USER_ID = 12345

SAMPLE_UNREAD = [
    {
        "id": "M0001",
        "from": [{"name": "Bob", "email": "bob@example.com"}],
        "subject": "Welcome",
        "received_at": "2026-05-21T10:00:00Z",
        "preview": "inbox preview",
        "mailbox_ids": ["MB0001"],
    },
    {
        "id": "M0002",
        "from": [{"name": "Klarna", "email": "no-reply@klarna.com"}],
        "subject": "Payment due",
        "received_at": "2026-05-21T09:00:00Z",
        "preview": "pinned folder preview",
        "mailbox_ids": ["MB0007"],
    },
]

# MB0007's name is deliberately unlike any sender/subject string, so a test
# asserting it appears can only be satisfied by the folder line itself.
SAMPLE_MAILBOXES = [
    {"id": "MB0001", "name": "Inbox"},
    {"id": "MB0002", "name": "Archive"},
    {"id": "MB0007", "name": "Receipts"},
]

WRITE_VERBS = ("mark_read", "mark_unread", "archive", "move", "trash", "flag")


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


def _make_context(adapter):
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}
    context.user_data = {}
    return context


async def test_digest_shows_folder_name_for_inbox_item():
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD
    adapter.list_mailboxes.return_value = SAMPLE_MAILBOXES

    update = _make_mail_update()
    context = _make_context(adapter)

    await handle_mail(update, context)

    _, kwargs = update.message.reply_text.call_args
    text = kwargs.get("text") or update.message.reply_text.call_args.args[0]
    assert "Folder: Inbox" in text  # M0001 lives in MB0001 -> "Inbox"


async def test_digest_shows_folder_name_for_pinned_folder_item():
    """A pinned, non-inbox item shows its folder name (e.g. Finance/Klarna leaf)."""
    adapter = MagicMock()
    # Queue starts on the pinned folder item.
    adapter.list_unread.return_value = [SAMPLE_UNREAD[1], SAMPLE_UNREAD[0]]
    adapter.list_mailboxes.return_value = SAMPLE_MAILBOXES

    update = _make_mail_update()
    context = _make_context(adapter)

    await handle_mail(update, context)

    _, kwargs = update.message.reply_text.call_args
    text = kwargs.get("text") or update.message.reply_text.call_args.args[0]
    assert "Folder: Receipts" in text  # M0002 lives in MB0007 -> "Receipts"


async def test_folder_names_resolved_once_per_session_not_per_item():
    """list_mailboxes is called once at /mail and cached — not per rendered item."""
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD
    adapter.list_mailboxes.return_value = SAMPLE_MAILBOXES

    context = _make_context(adapter)
    await handle_mail(_make_mail_update(), context)

    # Advance through the queue; rendering the next item must not re-fetch.
    await handle_callback(_make_callback_update("skip:M0001"), context)

    adapter.list_mailboxes.assert_called_once()


async def test_folder_name_cached_in_user_data():
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD
    adapter.list_mailboxes.return_value = SAMPLE_MAILBOXES

    context = _make_context(adapter)
    await handle_mail(_make_mail_update(), context)

    assert context.user_data["mailbox_names"]["MB0001"] == "Inbox"
    assert context.user_data["mailbox_names"]["MB0007"] == "Receipts"


async def test_render_path_issues_no_write_verb():
    """See-before-route: resolving + showing folder names changes no state."""
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD
    adapter.list_mailboxes.return_value = SAMPLE_MAILBOXES

    context = _make_context(adapter)
    await handle_mail(_make_mail_update(), context)
    await handle_callback(_make_callback_update("skip:M0001"), context)

    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()
