"""Unit tests for :class:`LiveAccountSession` (story 10.5a)."""
from __future__ import annotations

import pytest

from src.engine.account_session import LiveAccountSession, SessionState


def test_starts_pending() -> None:
    session = LiveAccountSession(account_id="acct-1")
    assert session.state is SessionState.PENDING
    assert session.last_error is None
    assert session.is_running is False
    assert session.is_failed is False


def test_mark_running() -> None:
    session = LiveAccountSession(account_id="acct-1")
    session.mark_running()
    assert session.state is SessionState.RUNNING
    assert session.is_running is True


def test_mark_running_idempotent() -> None:
    session = LiveAccountSession(account_id="acct-1")
    session.mark_running()
    session.mark_running()  # second call is a no-op
    assert session.state is SessionState.RUNNING


def test_mark_running_clears_previous_error() -> None:
    session = LiveAccountSession(account_id="acct-1")
    session.mark_failed("transient error")
    # Cannot transition FAILED → RUNNING without going through STOPPED first
    with pytest.raises(RuntimeError):
        session.mark_running()


def test_mark_failed_records_error() -> None:
    session = LiveAccountSession(account_id="acct-1")
    session.mark_failed("MT5 disconnected")
    assert session.state is SessionState.FAILED
    assert session.last_error == "MT5 disconnected"
    assert session.is_failed is True


def test_mark_failed_after_running_overrides_state() -> None:
    session = LiveAccountSession(account_id="acct-1")
    session.mark_running()
    session.mark_failed("crashed mid-flight")
    assert session.state is SessionState.FAILED
    assert session.last_error == "crashed mid-flight"


def test_mark_stopped_works_from_any_state() -> None:
    s1 = LiveAccountSession(account_id="acct-1")
    s1.mark_stopped()
    assert s1.state is SessionState.STOPPED

    s2 = LiveAccountSession(account_id="acct-2")
    s2.mark_running()
    s2.mark_stopped()
    assert s2.state is SessionState.STOPPED

    s3 = LiveAccountSession(account_id="acct-3")
    s3.mark_failed("err")
    s3.mark_stopped()
    assert s3.state is SessionState.STOPPED


def test_attach_components_merges() -> None:
    session = LiveAccountSession(account_id="acct-1")
    session.attach_components(actor=object())
    session.attach_components(node=object())
    assert {"actor", "node"} <= session.components.keys()
