"""Skeleton: triage_bot package and entry point exist."""


def test_triage_bot_exposes_build_application():
    from triage_bot import build_application

    assert callable(build_application)
