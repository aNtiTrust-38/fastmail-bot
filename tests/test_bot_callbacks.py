"""Button callbacks fire only their mapped verb and advance the queue."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import CallbackQueryHandler

from triage_bot import build_application
from triage_bot.bot import handle_callback, handle_mail

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
        "mailbox_ids": ["MB0001"],
    },
]

SAMPLE_MAILBOXES = [
    {"id": "MB0001", "name": "Inbox"},
    {"id": "MB0002", "name": "Archive"},
    {"id": "MB0004", "name": "Newsletters"},
]


def _make_callback_update(user_id, callback_data):
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query = AsyncMock()
    update.callback_query.data = callback_data
    return update


def _seeded_context(adapter, allowed_user_id=ALLOWED_USER_ID, index=0):
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": allowed_user_id}
    context.user_data = {
        "triage_queue": [m["id"] for m in SAMPLE_UNREAD],
        "triage_messages": {m["id"]: m for m in SAMPLE_UNREAD},
        "triage_index": index,
    }
    # Default freshness state: everything in the queue is still unread.
    # Tests that need to model staleness override adapter.list_unread.return_value.
    if not getattr(adapter.list_unread, "side_effect", None):
        adapter.list_unread.return_value = SAMPLE_UNREAD
    return context


WRITE_VERBS = ("mark_read", "mark_unread", "flag", "archive", "move", "trash")


def _assert_only_verb_called(adapter, expected_verb, expected_args=None):
    for verb in WRITE_VERBS:
        if verb == expected_verb:
            method = getattr(adapter, verb)
            method.assert_called_once()
            if expected_args is not None:
                method.assert_called_once_with(*expected_args)
        else:
            getattr(adapter, verb).assert_not_called()


def test_build_application_registers_callback_handler():
    app = build_application(
        adapter=MagicMock(),
        bot_token="123:fake-token",
        allowed_user_id=ALLOWED_USER_ID,
    )
    all_handlers = [h for hs in app.handlers.values() for h in hs]
    callback_handlers = [h for h in all_handlers if isinstance(h, CallbackQueryHandler)]
    assert len(callback_handlers) >= 1


async def test_handle_mail_does_not_call_write_verbs():
    """See-before-route: handle_mail only reads. Writes live in callbacks."""
    adapter = MagicMock()
    adapter.list_unread.return_value = SAMPLE_UNREAD

    update = MagicMock()
    update.effective_user.id = ALLOWED_USER_ID
    update.message = AsyncMock()
    context = MagicMock()
    context.bot_data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}
    context.user_data = {}

    await handle_mail(update, context)

    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()


@pytest.mark.parametrize(
    "action,verb,args",
    [
        ("mark_read", "mark_read", ("M0001",)),
        ("mark_unread", "mark_unread", ("M0001",)),
        ("pin", "flag", ("M0001",)),
        ("archive", "archive", ("M0001",)),
        ("trash_yes", "trash", ("M0001",)),
    ],
)
async def test_callback_fires_only_its_own_verb(action, verb, args):
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, f"{action}:M0001")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    _assert_only_verb_called(adapter, verb, args)


async def test_pin_callback_flags_then_advances():
    """Pin fires flag and advances — pinning does not end triage."""
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "pin:M0001")
    context = _seeded_context(adapter, index=0)

    await handle_callback(update, context)

    _assert_only_verb_called(adapter, "flag", ("M0001",))
    assert context.user_data["triage_index"] == 1
    args, _ = update.callback_query.edit_message_text.call_args
    assert "Newsletter" in args[0]  # advanced to M0002


async def test_skip_callback_fires_no_verb_and_advances():
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "skip:M0001")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()
    assert context.user_data["triage_index"] == 1


async def test_action_advances_queue_and_renders_next_message():
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "mark_read:M0001")
    context = _seeded_context(adapter, index=0)

    await handle_callback(update, context)

    assert context.user_data["triage_index"] == 1
    update.callback_query.edit_message_text.assert_called_once()
    args, _ = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert "Newsletter" in text  # M0002's subject


async def test_queue_end_shows_done_message_and_clears_state():
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "mark_read:M0002")
    context = _seeded_context(adapter, index=1)  # last message

    await handle_callback(update, context)

    args, _ = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert "complete" in text.lower() or "done" in text.lower() or "✓" in text
    assert "triage_queue" not in context.user_data
    assert "triage_index" not in context.user_data


async def test_trash_confirm_shows_yes_cancel_without_firing_trash():
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "trash_confirm:M0001")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    adapter.trash.assert_not_called()
    args, kwargs = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert "trash" in text.lower()
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    actions = {b.callback_data.split(":")[0] for b in buttons}
    assert actions == {"trash_yes", "trash_cancel"}
    assert context.user_data["triage_index"] == 0  # not advanced


async def test_trash_cancel_restores_original_keyboard_without_firing():
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "trash_cancel:M0001")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    adapter.trash.assert_not_called()
    args, kwargs = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert "Welcome" in text  # original message subject
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    actions = {b.callback_data.split(":")[0] for b in buttons}
    assert actions == {
        "mark_read",
        "mark_unread",
        "archive",
        "pin",
        "move",
        "trash_confirm",
        "skip",
    }
    assert context.user_data["triage_index"] == 0


async def test_move_shows_folder_picker_using_list_mailboxes():
    adapter = MagicMock()
    adapter.list_mailboxes.return_value = SAMPLE_MAILBOXES
    update = _make_callback_update(ALLOWED_USER_ID, "move:M0001")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    adapter.list_mailboxes.assert_called_once()
    adapter.move.assert_not_called()
    args, kwargs = update.callback_query.edit_message_text.call_args
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    labels = {b.text for b in buttons}
    assert {"Inbox", "Archive", "Newsletters"}.issubset(labels)
    # One Cancel button present
    assert any(b.callback_data.startswith("move_cancel") for b in buttons)
    assert context.user_data["triage_index"] == 0


async def test_move_to_fires_move_with_correct_mailbox_id():
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "move_to:M0001:MB0004")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    _assert_only_verb_called(adapter, "move", ("M0001", "MB0004"))
    assert context.user_data["triage_index"] == 1


async def test_move_cancel_restores_original_keyboard_without_firing():
    adapter = MagicMock()
    update = _make_callback_update(ALLOWED_USER_ID, "move_cancel:M0001")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    adapter.move.assert_not_called()
    args, kwargs = update.callback_query.edit_message_text.call_args
    text = args[0]
    assert "Welcome" in text
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    actions = {b.callback_data.split(":")[0] for b in buttons}
    assert actions == {
        "mark_read",
        "mark_unread",
        "archive",
        "pin",
        "move",
        "trash_confirm",
        "skip",
    }


async def test_callback_ignores_non_allowed_user():
    adapter = MagicMock()
    update = _make_callback_update(NON_ALLOWED_USER_ID, "mark_read:M0001")
    context = _seeded_context(adapter)

    await handle_callback(update, context)

    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()
    update.callback_query.answer.assert_not_called()
    update.callback_query.edit_message_text.assert_not_called()
