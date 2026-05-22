"""Present-time freshness.

The mailbox's `$seen` flag is the single source of truth. The queue, sourced
once at `/mail`, is re-validated against current unread state right before
each item is presented; items no longer unread are silently skipped, no
matter what changed them (acted on in another client, read elsewhere, etc.).
No presented-set, no persistence — the recheck is against live mailbox state.

Also re-asserts see-before-route on the new path: rendering an item does not
mark it read; only an explicit tap changes mailbox state.
"""

from unittest.mock import AsyncMock, MagicMock

from triage_bot.bot import handle_callback, handle_mail

ALLOWED_USER_ID = 12345

THREE_UNREAD = [
    {
        "id": "M0001",
        "from": [{"name": "Alice", "email": "alice@example.com"}],
        "subject": "First",
        "received_at": "2026-05-21T10:00:00Z",
        "preview": "first preview",
        "mailbox_ids": ["MB0001"],
    },
    {
        "id": "M0002",
        "from": [{"name": "Bob", "email": "bob@example.com"}],
        "subject": "Second",
        "received_at": "2026-05-21T09:00:00Z",
        "preview": "second preview",
        "mailbox_ids": ["MB0001"],
    },
    {
        "id": "M0003",
        "from": [{"name": "Carol", "email": "carol@example.com"}],
        "subject": "Third",
        "received_at": "2026-05-21T08:00:00Z",
        "preview": "third preview",
        "mailbox_ids": ["MB0001"],
    },
]

WRITE_VERBS = ("mark_read", "mark_unread", "archive", "move", "trash")


def _make_callback_update(callback_data):
    update = MagicMock()
    update.effective_user.id = ALLOWED_USER_ID
    update.callback_query = AsyncMock()
    update.callback_query.data = callback_data
    return update


def _seeded_three(adapter, index=0):
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}
    context.user_data = {
        "triage_queue": [m["id"] for m in THREE_UNREAD],
        "triage_messages": {m["id"]: m for m in THREE_UNREAD},
        "triage_index": index,
    }
    return context


async def test_advance_skips_stale_items_silently():
    """Item read between snapshot and advance is dropped without showing it."""
    adapter = MagicMock()
    # M0002 has been read elsewhere; only M0001 and M0003 are currently unread.
    # (M0001 stays in the fresh set — irrelevant for this advance since the
    # current index already moved past it.)
    adapter.list_unread.return_value = [THREE_UNREAD[0], THREE_UNREAD[2]]
    update = _make_callback_update("skip:M0001")
    context = _seeded_three(adapter, index=0)

    await handle_callback(update, context)

    # M0002 was stale and silently skipped; M0003 is presented.
    assert context.user_data["triage_index"] == 2
    update.callback_query.edit_message_text.assert_called_once()
    args, _ = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert "Third" in text
    assert "Second" not in text  # never shown
    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()


async def test_advance_with_all_remaining_stale_completes_triage():
    """If every remaining queued item is no longer unread, triage ends cleanly."""
    adapter = MagicMock()
    # Nothing is unread anymore — all queued items were cleared elsewhere.
    adapter.list_unread.return_value = []
    update = _make_callback_update("skip:M0001")
    context = _seeded_three(adapter, index=0)

    await handle_callback(update, context)

    update.callback_query.edit_message_text.assert_called_once()
    args, _ = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert "complete" in text.lower() or "✓" in text
    assert "triage_queue" not in context.user_data
    assert "triage_index" not in context.user_data
    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()


async def test_advance_rechecks_freshness_via_list_unread():
    """The freshness recheck IS one list_unread call on the advance path."""
    adapter = MagicMock()
    adapter.list_unread.return_value = THREE_UNREAD
    update = _make_callback_update("skip:M0001")
    context = _seeded_three(adapter, index=0)

    await handle_callback(update, context)

    # Exactly one list_unread call on the advance path. Cheap, not chatty.
    adapter.list_unread.assert_called_once()


async def test_advance_does_not_call_any_write_verb():
    """See-before-route on the new recheck path: present never writes."""
    adapter = MagicMock()
    adapter.list_unread.return_value = THREE_UNREAD
    update = _make_callback_update("skip:M0001")
    context = _seeded_three(adapter, index=0)

    await handle_callback(update, context)

    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()


async def test_handle_mail_queue_sourced_from_fresh_list_unread():
    """The queue at /mail IS the fresh list_unread; no other source."""
    adapter = MagicMock()
    adapter.list_unread.return_value = THREE_UNREAD

    update = MagicMock()
    update.effective_user.id = ALLOWED_USER_ID
    update.message = AsyncMock()
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}
    context.user_data = {}

    await handle_mail(update, context)

    adapter.list_unread.assert_called_once()
    assert context.user_data["triage_queue"] == ["M0001", "M0002", "M0003"]


async def test_rendering_does_not_mark_read():
    """Viewing in Telegram MUST NOT mark mail read — only explicit taps do."""
    adapter = MagicMock()
    adapter.list_unread.return_value = THREE_UNREAD

    update = MagicMock()
    update.effective_user.id = ALLOWED_USER_ID
    update.message = AsyncMock()
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}
    context.user_data = {}

    await handle_mail(update, context)
    # Also advance; both render paths must not mark read.
    advance_update = _make_callback_update("skip:M0001")
    advance_context = _seeded_three(adapter, index=0)
    await handle_callback(advance_update, advance_context)

    adapter.mark_read.assert_not_called()


async def test_advance_surfaces_freshness_check_error_safely():
    """If list_unread fails during the recheck, error is surfaced safely."""
    SECRET = "fmu1-secret-leak"
    adapter = MagicMock()
    adapter._token = SECRET
    adapter.list_unread.side_effect = Exception(f"recheck failed with token={SECRET}")
    update = _make_callback_update("skip:M0001")
    context = _seeded_three(adapter, index=0)

    # Must not crash.
    await handle_callback(update, context)

    update.callback_query.edit_message_text.assert_called_once()
    args, _ = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert SECRET not in text
    assert "Error" in text or "⚠" in text
