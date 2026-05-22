"""Scheduled nudge — daily ping at NUDGE_SCHEDULE time, never writes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from triage_bot import build_application
from triage_bot.bot import _parse_schedule, nudge_job

ALLOWED_USER_ID = 12345
WRITE_VERBS = ("mark_read", "archive", "move", "trash")


@pytest.mark.parametrize(
    "input_str,expected_hour,expected_min",
    [
        ("16:00", 16, 0),
        ("1600", 16, 0),
        ("08:30", 8, 30),
        ("0830", 8, 30),
        ("00:00", 0, 0),
    ],
)
def test_parse_schedule_supports_hhmm_and_hh_colon_mm(input_str, expected_hour, expected_min):
    result = _parse_schedule(input_str)
    assert result.hour == expected_hour
    assert result.minute == expected_min


def test_parse_schedule_returns_none_for_empty():
    assert _parse_schedule(None) is None
    assert _parse_schedule("") is None


def test_parse_schedule_raises_for_invalid():
    with pytest.raises(ValueError):
        _parse_schedule("not-a-time")


def test_build_application_does_not_schedule_nudge_when_off():
    app = build_application(
        adapter=MagicMock(),
        bot_token="123:fake-token",
        allowed_user_id=ALLOWED_USER_ID,
        nudge_schedule=None,
    )
    assert app.job_queue.jobs() == ()


def test_build_application_does_not_schedule_nudge_when_empty_string():
    app = build_application(
        adapter=MagicMock(),
        bot_token="123:fake-token",
        allowed_user_id=ALLOWED_USER_ID,
        nudge_schedule="",
    )
    assert app.job_queue.jobs() == ()


def test_build_application_schedules_one_daily_nudge_when_set():
    app = build_application(
        adapter=MagicMock(),
        bot_token="123:fake-token",
        allowed_user_id=ALLOWED_USER_ID,
        nudge_schedule="1600",
    )
    jobs = app.job_queue.jobs()
    assert len(jobs) == 1


async def test_nudge_job_sends_message_when_unread_present():
    adapter = MagicMock()
    adapter.list_unread.return_value = [
        {"id": "M0001"},
        {"id": "M0002"},
        {"id": "M0003"},
    ]

    context = MagicMock()
    context.bot = AsyncMock()
    context.job.data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}

    await nudge_job(context)

    adapter.list_unread.assert_called_once()
    context.bot.send_message.assert_called_once()
    _, kwargs = context.bot.send_message.call_args
    assert kwargs["chat_id"] == ALLOWED_USER_ID
    assert "3" in kwargs["text"]
    assert "/mail" in kwargs["text"]


async def test_nudge_job_sends_nothing_on_zero_unread():
    adapter = MagicMock()
    adapter.list_unread.return_value = []

    context = MagicMock()
    context.bot = AsyncMock()
    context.job.data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}

    await nudge_job(context)

    adapter.list_unread.assert_called_once()
    context.bot.send_message.assert_not_called()


async def test_nudge_job_never_calls_write_verbs():
    adapter = MagicMock()
    adapter.list_unread.return_value = [{"id": "M0001"}]

    context = MagicMock()
    context.bot = AsyncMock()
    context.job.data = {"adapter": adapter, "allowed_user_id": ALLOWED_USER_ID}

    await nudge_job(context)

    for verb in WRITE_VERBS:
        getattr(adapter, verb).assert_not_called()
