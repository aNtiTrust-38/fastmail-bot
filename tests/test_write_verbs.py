"""Write verbs — mark_read, mark_unread, flag, archive, move, trash. See-before-route enforced.

`mark_unread` is the mirror of `mark_read`: an `Email/set` that clears the `$seen`
keyword (patch value `None`/`null`) so the item bubbles back into a future
`list_unread()` cycle.

`flag` sets the `$flagged` keyword — the JMAP keyword for a Fastmail pin — so the
user can pin an email from within triage.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_fixture


def _post_response(fixture_name):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = load_fixture(fixture_name)
    return response


@patch("fastmail_adapter.adapter.requests.post")
def test_mark_read_sets_seen_keyword(mock_post, adapter):
    mock_post.return_value = _post_response("email_set_success.json")

    adapter.mark_read("M0001")

    body = mock_post.call_args.kwargs["json"]
    call = body["methodCalls"][0]
    assert call[0] == "Email/set"
    assert call[1]["accountId"] == "u1234abcd"
    assert call[1]["update"] == {"M0001": {"keywords/$seen": True}}


@patch("fastmail_adapter.adapter.requests.post")
def test_mark_unread_clears_seen_keyword(mock_post, adapter):
    """The eighth verb: Email/set clearing $seen so the item returns next cycle."""
    mock_post.return_value = _post_response("email_set_success.json")

    adapter.mark_unread("M0001")

    body = mock_post.call_args.kwargs["json"]
    call = body["methodCalls"][0]
    assert call[0] == "Email/set"
    assert call[1]["accountId"] == "u1234abcd"
    # Patch syntax: setting a keyword path to None clears that keyword.
    assert call[1]["update"] == {"M0001": {"keywords/$seen": None}}


@patch("fastmail_adapter.adapter.requests.post")
def test_mark_unread_issues_no_destroy_call(mock_post, adapter):
    """No destructive default: mark_unread never reaches Email/destroy."""
    mock_post.return_value = _post_response("email_set_success.json")

    adapter.mark_unread("M0001")

    for call in mock_post.call_args_list:
        for method in call.kwargs["json"]["methodCalls"]:
            assert "/destroy" not in method[0], f"mark_unread issued destroy call: {method[0]}"


@patch("fastmail_adapter.adapter.requests.post")
def test_flag_sets_flagged_keyword(mock_post, adapter):
    """The ninth verb: Email/set setting $flagged — pin the email."""
    mock_post.return_value = _post_response("email_set_success.json")

    adapter.flag("M0001")

    body = mock_post.call_args.kwargs["json"]
    call = body["methodCalls"][0]
    assert call[0] == "Email/set"
    assert call[1]["accountId"] == "u1234abcd"
    assert call[1]["update"] == {"M0001": {"keywords/$flagged": True}}


@patch("fastmail_adapter.adapter.requests.post")
def test_flag_issues_no_destroy_call(mock_post, adapter):
    """No destructive default: flag never reaches Email/destroy."""
    mock_post.return_value = _post_response("email_set_success.json")

    adapter.flag("M0001")

    for call in mock_post.call_args_list:
        for method in call.kwargs["json"]["methodCalls"]:
            assert "/destroy" not in method[0], f"flag issued destroy call: {method[0]}"


@patch("fastmail_adapter.adapter.requests.post")
def test_archive_removes_inbox_adds_archive(mock_post, adapter):
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_set_success.json"),
    ]

    adapter.archive("M0001")

    # First POST resolves mailbox roles.
    first_body = mock_post.call_args_list[0].kwargs["json"]
    assert first_body["methodCalls"][0][0] == "Mailbox/get"

    # Second POST is the Email/set patch.
    second_body = mock_post.call_args_list[1].kwargs["json"]
    set_call = second_body["methodCalls"][0]
    assert set_call[0] == "Email/set"
    update = set_call[1]["update"]["M0001"]
    # From the mailbox_get fixture: MB0001=Inbox, MB0002=Archive.
    assert update["mailboxIds/MB0001"] is None
    assert update["mailboxIds/MB0002"] is True


@patch("fastmail_adapter.adapter.requests.post")
def test_move_replaces_mailbox_ids_with_target(mock_post, adapter):
    mock_post.return_value = _post_response("email_set_success.json")

    adapter.move("M0001", "MB0099")

    body = mock_post.call_args.kwargs["json"]
    call = body["methodCalls"][0]
    assert call[0] == "Email/set"
    assert call[1]["update"] == {"M0001": {"mailboxIds": {"MB0099": True}}}


@patch("fastmail_adapter.adapter.requests.post")
def test_trash_replaces_mailbox_with_trash_role(mock_post, adapter):
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_set_success.json"),
    ]

    adapter.trash("M0001")

    second_body = mock_post.call_args_list[1].kwargs["json"]
    set_call = second_body["methodCalls"][0]
    assert set_call[0] == "Email/set"
    # From the mailbox_get fixture: MB0003=Trash.
    assert set_call[1]["update"] == {"M0001": {"mailboxIds": {"MB0003": True}}}


def test_adapter_source_forbids_email_destroy():
    """No destructive default: the adapter source never references Email/destroy."""
    source_dir = Path(__file__).parent.parent / "fastmail_adapter"
    for py_file in source_dir.glob("**/*.py"):
        content = py_file.read_text()
        assert (
            "Email/destroy" not in content
        ), f"{py_file.name} mentions Email/destroy — destructive default forbidden"
        assert (
            "/destroy" not in content
        ), f"{py_file.name} mentions /destroy — destructive default forbidden"


@patch("fastmail_adapter.adapter.requests.post")
def test_read_verbs_never_issue_write_calls(mock_post, adapter):
    """See-before-route: read verbs cannot reach a write call.

    list_unread issues a Mailbox/get to resolve the inbox role before
    the chained Email/query + Email/get — both still read-only.
    """
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),  # list_mailboxes
        _post_response("mailbox_get.json"),  # list_unread: inbox role resolution
        _post_response("email_query_get_chained.json"),  # list_unread: query + get
        _post_response("email_get_single.json"),  # get_email
    ]
    adapter.list_mailboxes()
    adapter.list_unread()
    adapter.get_email("M0001")

    for call in mock_post.call_args_list:
        for method in call.kwargs["json"]["methodCalls"]:
            method_name = method[0]
            assert "/set" not in method_name, f"Read verb issued write call: {method_name}"
            assert "/destroy" not in method_name, f"Read verb issued destroy call: {method_name}"
