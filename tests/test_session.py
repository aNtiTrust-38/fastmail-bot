"""Session bootstrap + bearer auth."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fastmail_adapter import FastmailAdapter, FastmailAuthError

FIXTURES = Path(__file__).parent / "fixtures"


def _ok_session_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = json.loads((FIXTURES / "session.json").read_text())
    return response


def _unauthorized_response():
    response = MagicMock()
    response.status_code = 401
    response.text = "Unauthorized"
    return response


@patch("fastmail_adapter.adapter.requests.get")
def test_session_sends_bearer_token(mock_get):
    mock_get.return_value = _ok_session_response()

    FastmailAdapter(token="test-token-abc", host="api.fastmail.com")

    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer test-token-abc"


@patch("fastmail_adapter.adapter.requests.get")
def test_session_hits_default_jmap_host(mock_get):
    mock_get.return_value = _ok_session_response()

    FastmailAdapter(token="test-token-abc")

    args, _ = mock_get.call_args
    assert args[0] == "https://api.fastmail.com/jmap/session"


@patch("fastmail_adapter.adapter.requests.get")
def test_session_respects_custom_host(mock_get):
    mock_get.return_value = _ok_session_response()

    FastmailAdapter(token="test-token-abc", host="jmap.example.com")

    args, _ = mock_get.call_args
    assert args[0] == "https://jmap.example.com/jmap/session"


@patch("fastmail_adapter.adapter.requests.get")
def test_session_parses_account_id_and_api_url(mock_get):
    mock_get.return_value = _ok_session_response()

    adapter = FastmailAdapter(token="test-token-abc")

    assert adapter._account_id == "u1234abcd"
    assert adapter._api_url == "https://api.fastmail.com/jmap/api/"


@patch("fastmail_adapter.adapter.requests.get")
def test_401_raises_clear_auth_error(mock_get):
    mock_get.return_value = _unauthorized_response()

    with pytest.raises(FastmailAuthError) as exc:
        FastmailAdapter(token="bad-token-xyz")

    assert "bad-token-xyz" not in str(exc.value)


def test_token_read_from_env_when_not_passed(monkeypatch):
    monkeypatch.setenv("FASTMAIL_TOKEN", "from-env-xyz")
    with patch("fastmail_adapter.adapter.requests.get") as mock_get:
        mock_get.return_value = _ok_session_response()
        FastmailAdapter()
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer from-env-xyz"


def test_missing_token_raises_clear_error(monkeypatch):
    monkeypatch.delenv("FASTMAIL_TOKEN", raising=False)
    with pytest.raises(ValueError) as exc:
        FastmailAdapter()
    assert "FASTMAIL_TOKEN" in str(exc.value)
