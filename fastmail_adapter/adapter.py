"""Fastmail JMAP triage adapter — nine verb methods.

`mark_unread` is the mirror of `mark_read`: the freshness loop depends on a
deliberate "return this next cycle" gesture. `flag` sets `$flagged` so the
user can pin an email from within triage.
"""

import os

import requests

DEFAULT_HOST = "api.fastmail.com"
JMAP_MAIL_CAPABILITY = "urn:ietf:params:jmap:mail"


class FastmailError(Exception):
    """Base for all Fastmail adapter errors."""


class FastmailAuthError(FastmailError):
    """JMAP request was rejected (typically a bad or expired token)."""


class FastmailHTTPError(FastmailError):
    """Non-401 HTTP failure at the requests boundary."""


class FastmailMethodError(FastmailError):
    """JMAP method-level error or Email/set notUpdated entry."""


class FastmailAdapter:
    def __init__(self, token=None, host=DEFAULT_HOST):
        if token is None:
            token = os.environ.get("FASTMAIL_TOKEN")
        if not token:
            raise ValueError("FASTMAIL_TOKEN env var is not set; pass token= or export it.")
        self._token = token
        self._host = host
        self._account_id, self._api_url = self._bootstrap_session()
        self._role_to_mailbox_id = None

    def _bootstrap_session(self):
        response = requests.get(
            f"https://{self._host}/jmap/session",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        if response.status_code == 401:
            raise FastmailAuthError(
                "JMAP session request returned 401 — token rejected. "
                "Regenerate FASTMAIL_TOKEN in Fastmail Settings → Security → API Tokens."
            )
        if response.status_code >= 400:
            raise FastmailHTTPError(f"JMAP session request failed: HTTP {response.status_code}")
        session = response.json()
        return (
            session["primaryAccounts"][JMAP_MAIL_CAPABILITY],
            session["apiUrl"],
        )

    def list_mailboxes(self):
        responses = self._invoke(
            [
                ["Mailbox/get", {"accountId": self._account_id, "ids": None}, "m0"],
            ]
        )
        _, payload, _ = responses[0]
        return [{"id": m["id"], "name": m["name"]} for m in payload["list"]]

    def list_unread(self):
        # Triage scope is inbox-unread OR pinned-unread-anywhere.
        # Pin ($flagged) is the user's rule-driven allowlist — folders surface
        # by being pinned in their Fastmail rules, not by anything hardcoded here.
        inbox_id = self._mailbox_id_for_role("inbox")
        responses = self._invoke(
            [
                [
                    "Email/query",
                    {
                        "accountId": self._account_id,
                        "filter": {
                            "operator": "OR",
                            "conditions": [
                                {
                                    "operator": "AND",
                                    "conditions": [
                                        {"inMailbox": inbox_id},
                                        {"notKeyword": "$seen"},
                                    ],
                                },
                                {
                                    "operator": "AND",
                                    "conditions": [
                                        {"hasKeyword": "$flagged"},
                                        {"notKeyword": "$seen"},
                                    ],
                                },
                            ],
                        },
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                    },
                    "q0",
                ],
                [
                    "Email/get",
                    {
                        "accountId": self._account_id,
                        "#ids": {"resultOf": "q0", "name": "Email/query", "path": "/ids"},
                        "properties": [
                            "id",
                            "subject",
                            "from",
                            "receivedAt",
                            "preview",
                            "mailboxIds",
                        ],
                    },
                    "g0",
                ],
            ]
        )
        get_payload = next(r[1] for r in responses if r[2] == "g0")
        return [
            {
                "id": e["id"],
                "from": e.get("from"),
                "subject": e.get("subject"),
                "received_at": e.get("receivedAt"),
                "preview": e.get("preview"),
                "mailbox_ids": list((e.get("mailboxIds") or {}).keys()),
            }
            for e in get_payload["list"]
        ]

    def get_email(self, email_id):
        responses = self._invoke(
            [
                [
                    "Email/get",
                    {
                        "accountId": self._account_id,
                        "ids": [email_id],
                        "fetchTextBodyValues": True,
                        "properties": [
                            "id",
                            "subject",
                            "from",
                            "to",
                            "receivedAt",
                            "mailboxIds",
                            "textBody",
                            "bodyValues",
                        ],
                    },
                    "g0",
                ],
            ]
        )
        _, payload, _ = responses[0]
        if not payload.get("list"):
            raise LookupError(f"No email found with id={email_id}")
        email = payload["list"][0]
        body_values = email.get("bodyValues") or {}
        body = "\n\n".join(
            body_values[part["partId"]]["value"]
            for part in (email.get("textBody") or [])
            if part.get("partId") in body_values
        )
        return {
            "id": email["id"],
            "from": email.get("from"),
            "to": email.get("to"),
            "subject": email.get("subject"),
            "received_at": email.get("receivedAt"),
            "mailbox_ids": list((email.get("mailboxIds") or {}).keys()),
            "body": body,
        }

    def mark_read(self, email_id):
        return self._email_set(email_id, {"keywords/$seen": True})

    def mark_unread(self, email_id):
        return self._email_set(email_id, {"keywords/$seen": None})

    def flag(self, email_id):
        return self._email_set(email_id, {"keywords/$flagged": True})

    def archive(self, email_id):
        inbox_id = self._mailbox_id_for_role("inbox")
        archive_id = self._mailbox_id_for_role("archive")
        return self._email_set(
            email_id,
            {
                f"mailboxIds/{inbox_id}": None,
                f"mailboxIds/{archive_id}": True,
            },
        )

    def move(self, email_id, mailbox_id):
        return self._email_set(email_id, {"mailboxIds": {mailbox_id: True}})

    def trash(self, email_id):
        return self.move(email_id, self._mailbox_id_for_role("trash"))

    def _email_set(self, email_id, update_patch):
        responses = self._invoke(
            [
                [
                    "Email/set",
                    {
                        "accountId": self._account_id,
                        "update": {email_id: update_patch},
                    },
                    "s0",
                ],
            ]
        )
        _, payload, _ = responses[0]
        not_updated = payload.get("notUpdated") or {}
        if email_id in not_updated:
            err = not_updated[email_id]
            raise FastmailMethodError(
                f"Email/set failed for {email_id}: "
                f"{err.get('type')} — {err.get('description', '')}"
            )
        return (payload.get("updated") or {}).get(email_id)

    def _mailbox_id_for_role(self, role):
        if self._role_to_mailbox_id is None:
            responses = self._invoke(
                [
                    ["Mailbox/get", {"accountId": self._account_id, "ids": None}, "m0"],
                ]
            )
            _, payload, _ = responses[0]
            self._role_to_mailbox_id = {
                m["role"]: m["id"] for m in payload["list"] if m.get("role")
            }
        if role not in self._role_to_mailbox_id:
            raise LookupError(f"No mailbox found for role {role!r}")
        return self._role_to_mailbox_id[role]

    def _invoke(self, method_calls):
        response = requests.post(
            self._api_url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            json={
                "using": ["urn:ietf:params:jmap:core", JMAP_MAIL_CAPABILITY],
                "methodCalls": method_calls,
            },
        )
        if response.status_code == 401:
            raise FastmailAuthError("JMAP request returned 401 — token rejected.")
        if response.status_code >= 400:
            raise FastmailHTTPError(f"JMAP request failed: HTTP {response.status_code}")
        method_responses = response.json()["methodResponses"]
        for name, payload, _ in method_responses:
            if name == "error":
                raise FastmailMethodError(
                    f"JMAP method-level error: {payload.get('type')} — "
                    f"{payload.get('description', '')}"
                )
        return method_responses
