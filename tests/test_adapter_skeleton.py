"""Package skeleton exists and exposes the nine verbs.

`mark_unread` is the mirror of `mark_read` — the freshness loop depends
on a deliberate "return this next cycle" gesture. `flag` lets the user
pin an email from within triage.
"""

import pytest

from fastmail_adapter import FastmailAdapter

NINE_VERBS = (
    "list_unread",
    "get_email",
    "list_mailboxes",
    "archive",
    "move",
    "mark_read",
    "mark_unread",
    "flag",
    "trash",
)


def test_fastmail_adapter_importable():
    assert FastmailAdapter is not None


@pytest.mark.parametrize("verb", NINE_VERBS)
def test_fastmail_adapter_exposes_verb(verb):
    assert callable(
        getattr(FastmailAdapter, verb, None)
    ), f"FastmailAdapter missing required verb: {verb}"
