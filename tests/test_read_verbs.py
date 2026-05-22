"""Read verbs — list_mailboxes, list_unread, get_email."""

from unittest.mock import MagicMock, patch

from tests.conftest import load_fixture


def _post_response(fixture_name):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = load_fixture(fixture_name)
    return response


@patch("fastmail_adapter.adapter.requests.post")
def test_list_mailboxes_calls_mailbox_get(mock_post, adapter):
    mock_post.return_value = _post_response("mailbox_get.json")

    result = adapter.list_mailboxes()

    body = mock_post.call_args.kwargs["json"]
    assert body["using"] == [
        "urn:ietf:params:jmap:core",
        "urn:ietf:params:jmap:mail",
    ]
    call = body["methodCalls"][0]
    assert call[0] == "Mailbox/get"
    assert call[1]["accountId"] == "u1234abcd"
    assert call[1].get("ids") is None

    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-token-abc"

    assert all(set(m.keys()) == {"id", "name"} for m in result)
    names = {m["name"] for m in result}
    assert {"Inbox", "Archive", "Trash", "Newsletters"} == names


# Inbox role id from mailbox_get.json fixture.
INBOX_ID = "MB0001"

# The two OR branches list_unread's Email/query filter must contain.
INBOX_UNREAD_BRANCH = {
    "operator": "AND",
    "conditions": [
        {"inMailbox": INBOX_ID},
        {"notKeyword": "$seen"},
    ],
}
PINNED_UNREAD_BRANCH = {
    "operator": "AND",
    "conditions": [
        {"hasKeyword": "$flagged"},
        {"notKeyword": "$seen"},
    ],
}


def _list_unread_query_filter(mock_post):
    """Return the Email/query filter from list_unread's chained POST.

    list_unread first POSTs Mailbox/get (inbox role resolution), then the
    chained Email/query + Email/get — the query is in the last POST.
    """
    body = mock_post.call_args_list[-1].kwargs["json"]
    query_call = body["methodCalls"][0]
    assert query_call[0] == "Email/query"
    return query_call[1]["filter"]


@patch("fastmail_adapter.adapter.requests.post")
def test_list_unread_chains_query_then_get_in_one_post(mock_post, adapter):
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_query_get_chained.json"),
    ]

    result = adapter.list_unread()

    # POST 1 resolves the inbox role; POST 2 chains Email/query + Email/get.
    assert mock_post.call_count == 2
    body = mock_post.call_args_list[-1].kwargs["json"]
    calls = body["methodCalls"]
    assert len(calls) == 2
    assert calls[0][0] == "Email/query"
    assert calls[1][0] == "Email/get"

    query_args = calls[0][1]
    assert query_args["accountId"] == "u1234abcd"

    get_args = calls[1][1]
    assert get_args["accountId"] == "u1234abcd"
    assert get_args["#ids"] == {
        "resultOf": calls[0][2],
        "name": "Email/query",
        "path": "/ids",
    }

    expected_keys = {"id", "from", "subject", "received_at", "preview", "mailbox_ids"}
    assert all(set(e.keys()) == expected_keys for e in result)
    assert result[0]["id"] == "M0001"
    assert result[0]["subject"] == "Welcome"
    assert result[0]["mailbox_ids"] == ["MB0001"]
    assert set(result[1]["mailbox_ids"]) == {"MB0001", "MB0004"}


@patch("fastmail_adapter.adapter.requests.post")
def test_list_unread_sorted_newest_first(mock_post, adapter):
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_query_get_chained.json"),
    ]

    adapter.list_unread()

    body = mock_post.call_args_list[-1].kwargs["json"]
    sort = body["methodCalls"][0][1].get("sort")
    assert sort == [{"property": "receivedAt", "isAscending": False}]


@patch("fastmail_adapter.adapter.requests.post")
def test_list_unread_filter_scopes_to_inbox_and_pinned_unread(mock_post, adapter):
    """REGRESSION GUARD: the query is OR(inbox-unread, pinned-unread).

    list_unread is narrowed from account-wide unread to inbox-plus-pinned.
    If this assertion needs to change, the triage scope is changing —
    confirm that is intended and not a silent widen back to all unread mail.
    Covers (a) unread inbox mail surfaces and (b) unread pinned mail in any
    folder surfaces.
    """
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_query_get_chained.json"),
    ]

    adapter.list_unread()

    filter_ = _list_unread_query_filter(mock_post)
    assert filter_["operator"] == "OR"
    assert len(filter_["conditions"]) == 2
    assert INBOX_UNREAD_BRANCH in filter_["conditions"]  # (a) inbox unread
    assert PINNED_UNREAD_BRANCH in filter_["conditions"]  # (b) pinned unread, any folder


@patch("fastmail_adapter.adapter.requests.post")
def test_list_unread_resolves_inbox_id_from_live_mailbox_role(mock_post, adapter):
    """The inbox branch's inMailbox is the live role id — not hardcoded."""
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_query_get_chained.json"),
    ]

    adapter.list_unread()

    first_post = mock_post.call_args_list[0].kwargs["json"]
    assert first_post["methodCalls"][0][0] == "Mailbox/get"
    # MB0001 is the mailbox with role "inbox" in mailbox_get.json.
    assert INBOX_UNREAD_BRANCH in _list_unread_query_filter(mock_post)["conditions"]


@patch("fastmail_adapter.adapter.requests.post")
def test_list_unread_excludes_non_pinned_folder_mail(mock_post, adapter):
    """(c) StackSocial-noise case: unread mail in a folder, not pinned.

    Such mail matches neither OR branch (not in the inbox, not $flagged), so
    it cannot reach the queue. Asserted structurally: every branch constrains
    on inbox membership or the pin keyword — none keys on unread alone.
    """
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_query_get_chained.json"),
    ]

    adapter.list_unread()

    filter_ = _list_unread_query_filter(mock_post)
    for branch in filter_["conditions"]:
        keys = {k for cond in branch["conditions"] for k in cond}
        assert "inMailbox" in keys or "hasKeyword" in keys


@patch("fastmail_adapter.adapter.requests.post")
def test_list_unread_excludes_read_pinned_mail(mock_post, adapter):
    """(d) A pinned email that is already read must NOT surface.

    Both branches AND in notKeyword $seen, so a read ($seen) pinned email
    fails its branch. Unread-pinned, not all-pinned.
    """
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_query_get_chained.json"),
    ]

    adapter.list_unread()

    filter_ = _list_unread_query_filter(mock_post)
    for branch in filter_["conditions"]:
        assert {"notKeyword": "$seen"} in branch["conditions"]


@patch("fastmail_adapter.adapter.requests.post")
def test_list_unread_query_is_not_account_wide_regression(mock_post, adapter):
    """REGRESSION: the query must never revert to a bare account-wide filter.

    {"notKeyword": "$seen"} alone re-floods the queue with folder-routed
    mail — the bug this scope prevents. The filter must be a FilterOperator.
    """
    mock_post.side_effect = [
        _post_response("mailbox_get.json"),
        _post_response("email_query_get_chained.json"),
    ]

    adapter.list_unread()

    filter_ = _list_unread_query_filter(mock_post)
    assert filter_ != {"notKeyword": "$seen"}
    assert "operator" in filter_, "filter must be a FilterOperator, not a bare condition"


@patch("fastmail_adapter.adapter.requests.post")
def test_get_email_returns_body_and_headers(mock_post, adapter):
    mock_post.return_value = _post_response("email_get_single.json")

    result = adapter.get_email("M0001")

    body = mock_post.call_args.kwargs["json"]
    call = body["methodCalls"][0]
    assert call[0] == "Email/get"
    assert call[1]["ids"] == ["M0001"]
    assert call[1].get("fetchTextBodyValues") is True

    assert result["id"] == "M0001"
    assert result["subject"] == "Welcome"
    assert result["from"] == [{"name": "Bob", "email": "bob@example.com"}]
    assert result["to"] == [{"name": "Sam", "email": "sam@example.com"}]
    assert result["mailbox_ids"] == ["MB0001"]
    assert result["body"] == "Hello Sam,\n\nThis is the body.\n\n— Bob"
