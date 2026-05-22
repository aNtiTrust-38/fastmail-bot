"""Error handling — fail-loud at requests and JMAP-method boundaries."""

from unittest.mock import MagicMock, patch

import pytest

from fastmail_adapter import (
    FastmailAdapter,
    FastmailAuthError,
    FastmailError,
    FastmailHTTPError,
    FastmailMethodError,
)
from tests.conftest import load_fixture


def _post_response(fixture_name):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = load_fixture(fixture_name)
    return response


def _http_failure(status):
    response = MagicMock()
    response.status_code = status
    response.text = f"HTTP {status}"
    return response


def test_error_hierarchy_is_rooted_at_fastmail_error():
    assert issubclass(FastmailAuthError, FastmailError)
    assert issubclass(FastmailHTTPError, FastmailError)
    assert issubclass(FastmailMethodError, FastmailError)


@patch("fastmail_adapter.adapter.requests.get")
def test_session_http_500_raises_typed_http_error(mock_get):
    mock_get.return_value = _http_failure(500)
    with pytest.raises(FastmailHTTPError) as exc:
        FastmailAdapter(token="test-token")
    assert "500" in str(exc.value)


@patch("fastmail_adapter.adapter.requests.post")
def test_post_http_500_raises_typed_http_error(mock_post, adapter):
    mock_post.return_value = _http_failure(500)
    with pytest.raises(FastmailHTTPError) as exc:
        adapter.list_mailboxes()
    assert "500" in str(exc.value)


@patch("fastmail_adapter.adapter.requests.post")
def test_post_http_401_raises_auth_error(mock_post, adapter):
    mock_post.return_value = _http_failure(401)
    with pytest.raises(FastmailAuthError):
        adapter.list_mailboxes()


@patch("fastmail_adapter.adapter.requests.post")
def test_jmap_method_level_error_raises_typed_error(mock_post, adapter):
    mock_post.return_value = _post_response("method_error.json")
    with pytest.raises(FastmailMethodError) as exc:
        adapter.list_mailboxes()
    assert "accountNotFound" in str(exc.value)


@patch("fastmail_adapter.adapter.requests.post")
def test_email_set_not_updated_raises_typed_error(mock_post, adapter):
    mock_post.return_value = _post_response("email_set_not_updated.json")
    with pytest.raises(FastmailMethodError) as exc:
        adapter.mark_read("M0001")
    assert "M0001" in str(exc.value)
    assert "notFound" in str(exc.value)


@patch("fastmail_adapter.adapter.requests.post")
def test_email_set_failure_does_not_return_silent_value(mock_post, adapter):
    """A failed Email/set must not return a success-looking value silently."""
    mock_post.return_value = _post_response("email_set_not_updated.json")
    try:
        result = adapter.mark_read("M0001")
    except FastmailMethodError:
        return
    pytest.fail(f"Expected FastmailMethodError, got silent return: {result!r}")
