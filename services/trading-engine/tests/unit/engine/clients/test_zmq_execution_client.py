"""Smoke tests for :class:`ZmqExecutionClient` (story 10.5c).

A full Nautilus :class:`LiveExecutionClient` instance requires
``msgbus`` / ``cache`` / ``instrument_provider`` / ``clock`` plumbed
together — heavyweight for unit tests. We use ``object.__new__`` to
create an instance without firing the Cython ``__init__`` so we can
exercise the methods that don't depend on engine state, and verify
the constructor signature for downstream wiring (10.5e).
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest
from nautilus_trader.live.execution_client import LiveExecutionClient

from src.engine.clients.zmq_execution_client import ZmqExecutionClient


def _make_uninitialised_client() -> ZmqExecutionClient:
    """Create an instance bypassing the Cython base ``__init__``.

    Nautilus's Cython base reserves slots like ``_clock`` that cannot
    be set after construction; those attributes only get initialised
    inside the proper ``__init__`` chain. Tests that need them go
    through :func:`_make_test_subclass_instance` instead.
    """
    instance = ZmqExecutionClient.__new__(ZmqExecutionClient)
    instance._account_id = "acct-test"  # type: ignore[attr-defined]
    instance._validated_adapter = MagicMock()  # type: ignore[attr-defined]
    return instance


class _TestZmqExecutionClient(ZmqExecutionClient):
    """Test seam: provides ``_clock`` / ``_validated_adapter`` /
    ``_account_id`` without invoking the Cython base ``__init__``.

    We override ``_clock`` as a Python descriptor on the *subclass*
    (not the base) so the cdef slot conflict in
    :class:`nautilus_trader.common.component.Component` does not apply.
    """

    def __init__(self) -> None:  # noqa: D401 — test seam
        # Skip super().__init__ entirely — Nautilus base would require
        # MessageBus / Cache / InstrumentProvider / LiveClock plumbed.
        self._account_id = "acct-test"
        self._validated_adapter = MagicMock()
        # ``_clock`` lives in a Cython slot on the base — we cannot
        # rebind it. Instead expose ``_clock`` via a per-instance dict
        # attribute under a different name for the dispatcher to use.
        self.__test_clock = MagicMock()

    # Override the property used inside ``_submit_order`` so the
    # dispatcher gets our test clock instead of the unset Cython slot.
    @property
    def _clock(self):  # type: ignore[override]
        return self.__test_clock


def test_subclasses_live_execution_client() -> None:
    assert issubclass(ZmqExecutionClient, LiveExecutionClient)


@pytest.mark.parametrize(
    "method_name",
    [
        "_submit_order_list",
        "_modify_order",
        "_cancel_order",
        "_cancel_all_orders",
        "_batch_cancel_orders",
    ],
)
@pytest.mark.asyncio
async def test_unsupported_methods_raise_not_implemented(method_name: str) -> None:
    """Order modify/cancel/batch are explicitly unsupported in Epic 10."""
    instance = _make_uninitialised_client()
    method = getattr(instance, method_name)
    with pytest.raises(NotImplementedError):
        await method(MagicMock())


@pytest.mark.asyncio
async def test_submit_order_delegates_to_dispatcher(monkeypatch) -> None:
    """``_submit_order`` forwards ``self`` as emitter and the bound
    account_id + validated_adapter to ``dispatch_submit_order``."""
    instance = _TestZmqExecutionClient()

    captured: dict[str, object] = {}

    async def _fake_dispatch(
        nautilus_order, *, account_id, validated_adapter, emitter, clock
    ) -> None:
        captured["order"] = nautilus_order
        captured["account_id"] = account_id
        captured["validated_adapter"] = validated_adapter
        captured["emitter"] = emitter
        captured["clock"] = clock

    monkeypatch.setattr(
        "src.engine.clients.zmq_execution_client.dispatch_submit_order",
        _fake_dispatch,
    )

    command = MagicMock()
    command.order = MagicMock()

    await instance._submit_order(command)

    assert captured["order"] is command.order
    assert captured["account_id"] == "acct-test"
    assert captured["validated_adapter"] is instance._validated_adapter
    assert captured["emitter"] is instance
    assert captured["clock"] is instance._clock


def test_constructor_signature_accepts_required_params() -> None:
    """Verify the constructor exposes the expected keyword-only params.

    Story 10.5e wires this via
    :meth:`LiveOrchestrator._build_session_components`; if the keyword
    surface drifts the wiring breaks loudly.
    """
    sig = inspect.signature(ZmqExecutionClient.__init__)
    params = sig.parameters
    required = {
        "loop",
        "client_id",
        "venue",
        "instrument_provider",
        "msgbus",
        "cache",
        "clock",
        "account_id",
        "validated_adapter",
    }
    assert required <= set(params)
    # All non-self params should be keyword-only — keeps the call site
    # from accidentally swapping account_id and validated_adapter.
    for name in required:
        assert (
            params[name].kind is inspect.Parameter.KEYWORD_ONLY
        ), f"{name} must be keyword-only"
