"""Shared pytest fixtures: pre-bootstrapped adapter with session mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fastmail_adapter import FastmailAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def session_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = load_fixture("session.json")
    return response


@pytest.fixture
def adapter(session_response):
    with patch("fastmail_adapter.adapter.requests.get") as mock_get:
        mock_get.return_value = session_response
        yield FastmailAdapter(token="test-token-abc")
