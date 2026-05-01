"""Unit tests for :class:`LockLostMediator` (story 10.2)."""
from __future__ import annotations

from src.engine.lock_lost import LockLostMediator


def test_unbound_invocation_is_a_noop():
    """Calling the mediator before bind() must not raise."""
    mediator = LockLostMediator()
    mediator()  # no handler → silent no-op


def test_invocation_routes_to_bound_handler():
    """After bind(), invoking the mediator runs the handler."""
    calls: list[bool] = []
    mediator = LockLostMediator()
    mediator.bind(lambda: calls.append(True))
    mediator()
    mediator()
    assert calls == [True, True]


def test_rebind_replaces_handler():
    """bind() is idempotent — the latest handler wins."""
    first: list[int] = []
    second: list[int] = []
    mediator = LockLostMediator()
    mediator.bind(lambda: first.append(1))
    mediator()
    mediator.bind(lambda: second.append(2))
    mediator()
    assert first == [1]
    assert second == [2]
