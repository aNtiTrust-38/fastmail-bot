"""Deploy entrypoint — env-reading + fail-loud + secret-safe."""

import os
from unittest.mock import MagicMock, patch

import pytest

from triage_bot.__main__ import REQUIRED_ENV_VARS, main

VALID_ENV = {
    "FASTMAIL_TOKEN": "fmu1-fake-fastmail-token",
    "TELEGRAM_BOT_TOKEN": "123:fake-telegram-token",
    "TELEGRAM_ALLOWED_USER_ID": "12345",
    "NUDGE_SCHEDULE": "1600",
}


@patch("triage_bot.__main__.build_application")
@patch("triage_bot.__main__.FastmailAdapter")
def test_main_wires_adapter_and_app_then_runs_polling(mock_adapter_cls, mock_build):
    mock_adapter = MagicMock()
    mock_adapter_cls.return_value = mock_adapter
    mock_app = MagicMock()
    mock_build.return_value = mock_app

    with patch.dict(os.environ, VALID_ENV, clear=True):
        main()

    mock_adapter_cls.assert_called_once_with(token="fmu1-fake-fastmail-token")

    mock_build.assert_called_once()
    kwargs = mock_build.call_args.kwargs
    assert kwargs["adapter"] is mock_adapter
    assert kwargs["bot_token"] == "123:fake-telegram-token"
    assert kwargs["allowed_user_id"] == "12345"
    assert kwargs["nudge_schedule"] == "1600"

    mock_app.run_polling.assert_called_once()


@patch("triage_bot.__main__.build_application")
@patch("triage_bot.__main__.FastmailAdapter")
def test_main_passes_none_when_nudge_schedule_unset(mock_adapter_cls, mock_build):
    env_without_nudge = {k: v for k, v in VALID_ENV.items() if k != "NUDGE_SCHEDULE"}
    with patch.dict(os.environ, env_without_nudge, clear=True):
        main()
    assert mock_build.call_args.kwargs["nudge_schedule"] is None


@pytest.mark.parametrize("missing_var", REQUIRED_ENV_VARS)
def test_main_raises_clear_error_when_a_required_var_is_missing(missing_var):
    incomplete = {k: v for k, v in VALID_ENV.items() if k != missing_var}
    with patch.dict(os.environ, incomplete, clear=True):
        with pytest.raises(RuntimeError) as exc:
            main()
        assert missing_var in str(exc.value)


def test_main_lists_every_missing_required_var_in_one_error():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError) as exc:
            main()
        for var in REQUIRED_ENV_VARS:
            assert var in str(exc.value)


def test_main_error_message_does_not_echo_any_secret_value():
    SECRET = "fmu1-do-not-leak-this-secret"
    only_one_var_set = {"FASTMAIL_TOKEN": SECRET}
    with patch.dict(os.environ, only_one_var_set, clear=True):
        with pytest.raises(RuntimeError) as exc:
            main()
        assert SECRET not in str(exc.value)
