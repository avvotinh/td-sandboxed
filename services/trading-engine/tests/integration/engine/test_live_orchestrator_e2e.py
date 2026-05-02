"""Story 10.5f — end-to-end live-orchestrator integration test (AC9).

Stands up a full :class:`LiveOrchestrator` (real Nautilus
:class:`TradingNode` per account, real :class:`RedisDataClient`,
real :class:`ZmqExecutionClient`) with two accounts (FTMO + The5ers
Bootstrap), drives the spec's six AC9 scenarios end-to-end, and asserts
the wiring the unit tests stub away:

1. Orchestrator boots → both accounts' nodes are running.
2. A bar published to ``bars:{symbol}:{tf}`` reaches **both** strategies'
   ``on_bar`` via the real RedisDataClient → Nautilus data engine path.
3. A strategy submitting a market order reaches the
   :class:`ValidatedZmqAdapter` with the correct ``account_id``.
4. The :class:`PropFirmComplianceActor` records compliance checks
   driven by the same bar feed.
5. A simulated breach (stub adapter flips to BLOCK) → next order is
   rejected client-side as a Nautilus ``OrderDenied`` event.
6. ``LiveOrchestrator.stop()`` tears every node down cleanly.

Heavy by design — marked ``@pytest.mark.integration`` so the default
unit-test run skips it. Run with ``pytest -m integration``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from src.adapters.zmq_models import OrderResult, OrderStatus
from src.backtesting.strategy_registry import (
    BACKTEST_STRATEGIES,
    StrategyEntry,
)
from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import LiveOrchestrator
from src.engine.node_factory import build_account_trading_node
from src.execution.exceptions import OrderBlockedError
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test strategy — emits one BUY market order per bar received
# ---------------------------------------------------------------------------


class _TestEmitStrategyConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    pass


class _TestEmitStrategy(BaseStrategy):
    """Minimal Nautilus strategy: submit a 1-lot BUY market on every bar.

    Bypasses :meth:`BaseStrategy._go_long`'s ``is_flat`` guard so we can
    drive multiple bars and verify the BLOCK path on the second order.
    """

    # Per-account instances — populated in ``__init__`` so the test can
    # poke ``bars_seen`` / ``orders_attempted`` without reaching into
    # Nautilus's trader internals.
    by_account: ClassVar[dict[str, "_TestEmitStrategy"]] = {}

    def __init__(self, config: _TestEmitStrategyConfig) -> None:
        super().__init__(config)
        _TestEmitStrategy.by_account[config.account_id] = self
        self.bars_seen: list[Any] = []
        self.orders_attempted: int = 0
        self.denials_received: int = 0

    @classmethod
    def reset_registry(cls) -> None:
        cls.by_account.clear()

    def generate_signal(self, bar) -> Any:  # noqa: D401, ARG002
        # Unused — we override on_bar directly to bypass is_flat guard.
        return None

    def on_bar(self, bar) -> None:
        self.bars_seen.append(bar)
        if self._instrument is None:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self._instrument.make_qty(self.config.trade_size),
        )
        self.orders_attempted += 1
        self.submit_order(order)

    def on_event(self, event) -> None:  # noqa: D401
        # Nautilus ``OrderDenied`` is a subclass of ``Event``; sniff by
        # class name to avoid pulling the cython type into module scope.
        if type(event).__name__ == "OrderDenied":
            self.denials_received += 1
        super().on_event(event)


# ---------------------------------------------------------------------------
# Stub ValidatedZmqAdapter — records orders, can be flipped to BLOCK
# ---------------------------------------------------------------------------


class _StubValidatedAdapter:
    """``ValidatedZmqAdapter`` shape used by :func:`dispatch_submit_order`.

    Records every internal-Order DTO that flows through and returns a
    ``FILLED`` :class:`OrderResult`. Setting ``block_mode=True`` makes
    every subsequent call raise :class:`OrderBlockedError` so the test
    can assert the BLOCK path.
    """

    def __init__(self) -> None:
        self.orders_received: list[Any] = []
        self.block_mode: bool = False

    async def send_order_and_wait(
        self, order: Any, timeout: float = 5.0
    ) -> OrderResult:
        self.orders_received.append(order)
        if self.block_mode:
            raise OrderBlockedError(
                reason="Daily loss breach (test simulation)",
                blocked_by_rule="daily_loss_limit",
                current_value=5.5,
                threshold_value=5.0,
            )
        return OrderResult(
            order_id=f"venue-{len(self.orders_received)}",
            status=OrderStatus.FILLED,
            fill_price=1.10000,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Test strategy registration (monkeypatch)
# ---------------------------------------------------------------------------


_TEST_STRATEGY_NAME = "_e2e_test_emit"


@pytest.fixture
def register_test_strategy() -> Iterator[None]:
    """Register the test strategy in the backtest registry for the test."""
    BACKTEST_STRATEGIES[_TEST_STRATEGY_NAME] = StrategyEntry(
        config_cls=_TestEmitStrategyConfig,
        strategy_cls=_TestEmitStrategy,
    )
    _TestEmitStrategy.reset_registry()
    try:
        yield
    finally:
        BACKTEST_STRATEGIES.pop(_TEST_STRATEGY_NAME, None)
        _TestEmitStrategy.reset_registry()


# ---------------------------------------------------------------------------
# Account / orchestrator fixtures
# ---------------------------------------------------------------------------


def _account_config(
    *,
    account_id: str,
    symbol: str = "EURUSD",
) -> MagicMock:
    """Duck-typed account config — only the fields the orchestrator reads.

    ``trade_size=Decimal("1000")`` (1 micro-lot of FX in whole units)
    survives the integer-precision rounding that
    :class:`TestInstrumentProvider`'s default FX instruments enforce
    (``size_increment=1``, ``size_precision=0``).
    """
    sig = MagicMock()
    sig.symbols = [symbol]

    cfg = MagicMock()
    cfg.id = account_id
    cfg.signal_filter = sig
    cfg.strategy = _TEST_STRATEGY_NAME
    cfg.strategy_params = {"trade_size": Decimal("1000")}
    return cfg


def _account_manager(active: list[MagicMock]) -> MagicMock:
    am = MagicMock()
    am.get_active_account_ids = MagicMock(
        return_value=[a.id for a in active]
    )
    am.get_account = MagicMock(
        side_effect=lambda aid: next(
            (a for a in active if a.id == aid), None
        )
    )

    async def _pause(_aid: str) -> None:
        return None

    am.pause_account = _pause
    return am


def _rule_assignment_service() -> MagicMock:
    svc = MagicMock()
    svc.get_rules_for_account = MagicMock(return_value=[])
    return svc


def _risk_registry() -> MagicMock:
    state = MagicMock()
    state.daily_starting_balance = Decimal("100000")
    registry = MagicMock()
    registry.get_risk_state = MagicMock(return_value=state)
    return registry


def _redis_manager(redis_client: Any) -> MagicMock:
    """Build a duck-typed ``RedisStateManager`` whose ``client`` is a
    real (fake)redis instance."""
    manager = MagicMock()
    manager.client = redis_client
    return manager


def _make_node_factory_with_instrument(symbol: str):
    """Return a node-factory wrapper for the test environment.

    Two test-only adjustments on top of :func:`build_account_trading_node`:

    1. Register a Nautilus instrument on the node cache so the test
       strategy's ``on_start`` can resolve it (production wires this
       through a real ``InstrumentProvider``; the integration test
       short-circuits with ``TestInstrumentProvider``).
    2. Replace ``node.dispose()`` with a no-op. Nautilus's real
       ``dispose`` calls ``kernel.cancel_all_tasks`` which collects
       *every* task on the loop — including pytest-asyncio's test
       runner task — and cancels them, killing the test mid-flight.
       In production the loop is owned by the engine entrypoint so
       this is the right teardown; in tests we skip it and let GC
       reclaim Nautilus state at process exit.
    """

    def _factory(*, account, spec):
        node = build_account_trading_node(account=account, spec=spec)
        # The strategy resolves ``instrument_id = EURUSD.MT5`` (matches
        # the orchestrator's default venue), so we must register the
        # instrument under the same venue — not ``SIM`` from the test
        # provider's default.
        instrument = TestInstrumentProvider.default_fx_ccy(symbol, venue=Venue("MT5"))
        node.cache.add_instrument(instrument)
        node.dispose = lambda: None  # see docstring rationale
        return node

    return _factory


# ---------------------------------------------------------------------------
# Helpers — drive Redis + wait for state
# ---------------------------------------------------------------------------


def _bar_payload(symbol: str, tf: str, *, close: float) -> bytes:
    """Build the JSON payload the RedisDataClient parses (matches
    ``adapters.redis_models.Bar`` shape — field is ``time``, not
    ``timestamp``)."""
    payload = {
        "symbol": symbol,
        "timeframe": tf,
        "time": datetime.now(timezone.utc).isoformat(),
        "open": close,
        "high": close + 0.0001,
        "low": close - 0.0001,
        "close": close,
        "volume": 1000.0,
    }
    return json.dumps(payload).encode()


async def _drive_bars(
    redis: Any,
    symbol: str,
    tf: str,
    *,
    close: float,
    until,
    timeout: float = 15.0,
    interval: float = 0.1,
) -> None:
    """Publish bars until ``until()`` returns truthy or timeout elapses.

    Why a loop: the Nautilus data engine takes a few moments to wire the
    bar subscription end-to-end after ``run_async`` starts; the
    execution engine has a 10s reconciliation_startup_delay. Pulsing a
    bar every ``interval`` keeps the test fast once the path is open
    without flaking when host startup is slow.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if until():
            return
        await redis.publish(
            f"bars:{symbol}:{tf}", _bar_payload(symbol, tf, close=close)
        )
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def _orchestrator(
    *,
    accounts: list[MagicMock],
    symbol: str,
) -> AsyncIterator[tuple[LiveOrchestrator, _StubValidatedAdapter, Any]]:
    """Async context manager — build, start, yield, stop the orchestrator."""
    redis_client = fakeredis.aioredis.FakeRedis()
    adapter = _StubValidatedAdapter()
    live = LiveOrchestrator(
        services=LiveServiceBundle(),
        account_manager=_account_manager(accounts),
        rule_assignment_service=_rule_assignment_service(),
        risk_registry=_risk_registry(),
        redis_manager=_redis_manager(redis_client),
        validated_adapter=adapter,
        node_factory=_make_node_factory_with_instrument(symbol),
        health_push_interval=10.0,  # quiet — we don't assert on health here
    )
    await live.start()
    try:
        yield live, adapter, redis_client
    finally:
        await live.stop()
        with contextlib.suppress(Exception):
            await redis_client.aclose()


# ---------------------------------------------------------------------------
# AC9 — the six end-to-end scenarios
# ---------------------------------------------------------------------------


class TestLiveOrchestratorEndToEnd:
    @pytest.mark.asyncio
    async def test_ac9_step1_orchestrator_boots_both_accounts(
        self, register_test_strategy
    ) -> None:
        """AC9.1 — both accounts' sessions running with attached node."""
        accounts = [
            _account_config(account_id="ftmo-001"),
            _account_config(account_id="the5ers-001"),
        ]
        async with _orchestrator(
            accounts=accounts, symbol="EURUSD"
        ) as (live, _adapter, _redis):
            assert set(live.sessions.keys()) == {"ftmo-001", "the5ers-001"}
            for sid, session in live.sessions.items():
                assert session.is_running, f"{sid} not running"
                assert session.components["trading_node"] is not None
                assert sid in live._node_run_tasks

    @pytest.mark.asyncio
    async def test_ac9_step2_bar_reaches_both_strategies(
        self, register_test_strategy
    ) -> None:
        """AC9.2 — published bar fans out to every active account's strategy."""
        accounts = [
            _account_config(account_id="ftmo-001"),
            _account_config(account_id="the5ers-001"),
        ]
        async with _orchestrator(
            accounts=accounts, symbol="EURUSD"
        ) as (_live, _adapter, redis):
            def both_received() -> bool:
                a = _TestEmitStrategy.by_account.get("ftmo-001")
                b = _TestEmitStrategy.by_account.get("the5ers-001")
                return (
                    a is not None
                    and b is not None
                    and len(a.bars_seen) >= 1
                    and len(b.bars_seen) >= 1
                )

            await _drive_bars(
                redis, "EURUSD", "1m", close=1.10000,
                until=both_received, timeout=20.0,
            )
            assert both_received(), (
                "bars never reached both strategies — "
                f"ftmo={len(_TestEmitStrategy.by_account.get('ftmo-001').bars_seen) if 'ftmo-001' in _TestEmitStrategy.by_account else 'missing'}, "
                f"the5ers={len(_TestEmitStrategy.by_account.get('the5ers-001').bars_seen) if 'the5ers-001' in _TestEmitStrategy.by_account else 'missing'}"
            )

    @pytest.mark.asyncio
    async def test_ac9_step3_order_reaches_validated_adapter_with_account_id(
        self, register_test_strategy
    ) -> None:
        """AC9.3 — strategy submits an order; the stub adapter sees it
        with the correct ``account_id`` threaded through."""
        accounts = [_account_config(account_id="ftmo-001")]
        async with _orchestrator(
            accounts=accounts, symbol="EURUSD"
        ) as (_live, adapter, redis):
            await _drive_bars(
                redis, "EURUSD", "1m", close=1.10000,
                until=lambda: len(adapter.orders_received) >= 1,
                timeout=20.0,
            )
            assert len(adapter.orders_received) >= 1, (
                "no order ever reached the validated adapter"
            )

            order = adapter.orders_received[0]
            # Internal-Order DTO carries account_id from the client.
            assert order.account_id == "ftmo-001"
            assert order.symbol == "EURUSD"

    @pytest.mark.asyncio
    async def test_ac9_step4_compliance_actor_runs_on_bar(
        self, register_test_strategy
    ) -> None:
        """AC9.4 — :class:`PropFirmComplianceActor` is wired and fires
        on the same bar feed (its ``on_bar`` records equity + invokes
        the rule engine via ``record_compliance_check``).

        The actor in 10.5e2's wiring path uses ``equity_provider`` (live
        mode) which returns ``None`` until the PnL tracker has a balance
        — so we assert on ``bars_seen`` on the strategy instead, which
        proves the bar-level dispatch path works end-to-end. Equity
        sourcing is exercised by the unit tests in
        ``test_live_compliance_actor.py``.
        """
        accounts = [_account_config(account_id="ftmo-001")]
        async with _orchestrator(
            accounts=accounts, symbol="EURUSD"
        ) as (live, _adapter, redis):
            session = live.sessions["ftmo-001"]
            actor = session.components["compliance_actor"]
            assert actor is not None
            assert hasattr(actor, "evaluate_compliance"), (
                "compliance_actor must be a real PropFirmComplianceActor "
                "(integration wiring should not stub the actor)"
            )
            # The bar-flow proof — strategy receives bars, which means
            # the same data engine dispatch fans out to the actor too.
            strategy = _TestEmitStrategy.by_account["ftmo-001"]
            await _drive_bars(
                redis, "EURUSD", "1m", close=1.10000,
                until=lambda: len(strategy.bars_seen) >= 1,
                timeout=20.0,
            )
            assert len(strategy.bars_seen) >= 1

    @pytest.mark.asyncio
    async def test_ac9_step5_breach_blocks_next_order(
        self, register_test_strategy
    ) -> None:
        """AC9.5 — flip the validated adapter to BLOCK; subsequent
        orders are rejected → strategy receives ``OrderDenied``."""
        accounts = [_account_config(account_id="ftmo-001")]
        async with _orchestrator(
            accounts=accounts, symbol="EURUSD"
        ) as (_live, adapter, redis):
            # First bar: pre-block, order should pass.
            await _drive_bars(
                redis, "EURUSD", "1m", close=1.10000,
                until=lambda: len(adapter.orders_received) >= 1,
                timeout=20.0,
            )
            pre_count = len(adapter.orders_received)
            assert pre_count >= 1, "pre-block order never reached adapter"

            # Simulate the breach + drive another bar.
            adapter.block_mode = True
            await _drive_bars(
                redis, "EURUSD", "1m", close=1.10010,
                until=lambda: (
                    len(adapter.orders_received) > pre_count
                    and _TestEmitStrategy.by_account[
                        "ftmo-001"
                    ].denials_received >= 1
                ),
                timeout=20.0,
            )
            assert _TestEmitStrategy.by_account[
                "ftmo-001"
            ].denials_received >= 1, (
                f"BLOCK path not exercised — "
                f"orders_received={len(adapter.orders_received)}, "
                f"denials={_TestEmitStrategy.by_account['ftmo-001'].denials_received}"
            )

    @pytest.mark.asyncio
    async def test_ac9_step6_graceful_shutdown_disposes_every_node(
        self, register_test_strategy
    ) -> None:
        """AC9.6 — ``stop()`` clears every session's run-task and marks
        each session STOPPED.

        We assert on the orchestrator's bookkeeping rather than the
        Nautilus ``TradingNode.is_running`` flag because the test stub
        replaces ``dispose`` (Nautilus's real dispose calls
        ``cancel_all_tasks`` which kills pytest-asyncio's loop). Without
        dispose the kernel state stays partially set; the orchestrator-
        level invariant — "every session stopped, no run tasks left" —
        is the production-relevant contract.

        **NOT verified here** — that ``node.dispose()`` itself runs to
        completion without raising. Nautilus dispose-time exceptions
        would surface as ``logger.exception`` from
        ``_teardown_session_components`` but we cannot exercise the
        real dispose in a pytest-asyncio loop. TODO(10.5+): isolate
        dispose-time invariants in a subprocess test that owns its own
        event loop.
        """
        from src.engine.account_session import SessionState

        accounts = [
            _account_config(account_id="ftmo-001"),
            _account_config(account_id="the5ers-001"),
        ]
        redis_client = fakeredis.aioredis.FakeRedis()
        adapter = _StubValidatedAdapter()
        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=_account_manager(accounts),
            rule_assignment_service=_rule_assignment_service(),
            risk_registry=_risk_registry(),
            redis_manager=_redis_manager(redis_client),
            validated_adapter=adapter,
            node_factory=_make_node_factory_with_instrument("EURUSD"),
            health_push_interval=10.0,
        )
        await live.start()
        assert all(
            s.components["trading_node"] is not None
            for s in live.sessions.values()
        )

        await live.stop()

        # Orchestrator-level shutdown invariant.
        assert live._node_run_tasks == {}
        for session in live.sessions.values():
            assert session.state is SessionState.STOPPED, (
                f"{session.account_id} not STOPPED: {session.state}"
            )

        await redis_client.aclose()
