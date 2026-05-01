"""Story 10.5e2 — per-account ``TradingNode`` factory tests.

Covers :func:`build_account_trading_node` shape contract:

- Builds a Nautilus ``TradingNode`` with the per-account
  ``RedisDataClient`` + ``ZmqExecutionClient`` factories registered
  under a stable client name.
- Resolves the strategy via the backtest registry, threads the account
  id, and registers it on the trader.
- Attaches the pre-built compliance actor when supplied.
- Refuses to build with empty ``bar_subscriptions`` (the strategy
  cannot subscribe to a feed otherwise).

The Cython :class:`TradingNode` is replaced with a recording stub so
the test does not require a running event loop / Nautilus kernel — the
factory is a pure orchestration step. End-to-end node-runtime
exercise is deferred to story 10.5f.
"""
from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from nautilus_trader.live.factories import (
    LiveDataClientFactory,
    LiveExecClientFactory,
)
from nautilus_trader.model.identifiers import Venue

from src.engine.node_factory import (
    AccountNodeSpec,
    DEFAULT_VENUE_NAME,
    build_account_trading_node,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test stub for ``TradingNode``
# ---------------------------------------------------------------------------


class _RecordingTradingNode:
    """Stand-in for :class:`TradingNode` that records calls for assertions.

    The real Cython base requires a kernel + event loop just to
    construct. We only care that the factory makes the right calls in
    the right order — exercising the actual Nautilus runtime is the
    job of story 10.5f.
    """

    instances: ClassVar[list["_RecordingTradingNode"]] = []

    def __init__(self, config: Any = None, loop: Any = None) -> None:
        self.config = config
        self.loop = loop
        self.data_factories: dict[str, type[LiveDataClientFactory]] = {}
        self.exec_factories: dict[str, type[LiveExecClientFactory]] = {}
        self.built = False
        self.strategies: list[Any] = []
        self.actors: list[Any] = []
        self.run_called = False
        self.stop_called = False
        self.disposed = False
        # Nautilus exposes a ``trader`` attribute with ``add_strategy``
        # + ``add_actor``; mirror that surface here.
        self.trader = MagicMock()
        self.trader.add_strategy = self.strategies.append
        self.trader.add_actor = self.actors.append
        _RecordingTradingNode.instances.append(self)

    def add_data_client_factory(
        self, name: str, factory: type[LiveDataClientFactory]
    ) -> None:
        self.data_factories[name] = factory

    def add_exec_client_factory(
        self, name: str, factory: type[LiveExecClientFactory]
    ) -> None:
        self.exec_factories[name] = factory

    def build(self) -> None:
        self.built = True

    async def run_async(self) -> None:
        self.run_called = True

    async def stop_async(self) -> None:
        self.stop_called = True

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture(autouse=True)
def _reset_recording_node() -> None:
    _RecordingTradingNode.instances.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _account(
    account_id: str = "acct-1",
    strategy: str = "ma_crossover",
    strategy_params: dict[str, Any] | None = None,
) -> MagicMock:
    cfg = MagicMock()
    cfg.id = account_id
    cfg.strategy = strategy
    cfg.strategy_params = strategy_params or {}
    return cfg


def _spec(
    account_id: str = "acct-1",
    *,
    bar_subscriptions: tuple[tuple[str, str], ...] = (("EURUSD", "1m"),),
    strategy: str = "ma_crossover",
    strategy_params: dict[str, Any] | None = None,
    compliance_actor: Any = None,
) -> AccountNodeSpec:
    return AccountNodeSpec(
        account_id=account_id,
        venue=Venue(DEFAULT_VENUE_NAME),
        bar_subscriptions=bar_subscriptions,
        redis_client=MagicMock(),
        validated_adapter=MagicMock(),
        strategy_name=strategy,
        strategy_params=strategy_params or {},
        compliance_actor=compliance_actor,
    )


# ---------------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------------


class TestNodeBuild:
    def test_builds_node_with_per_account_client_factories(self) -> None:
        account = _account("ftmo-007")
        spec = _spec("ftmo-007")

        node = build_account_trading_node(
            account=account,
            spec=spec,
            trading_node_cls=_RecordingTradingNode,
        )

        assert isinstance(node, _RecordingTradingNode)
        assert node.built is True
        # Factory registered under the sanitised client name (uppercase).
        assert "FTMO-007" in node.data_factories
        assert "FTMO-007" in node.exec_factories
        # The factories are subclasses of the expected Nautilus base
        # classes (closure-built classes preserve the inheritance).
        data_factory = node.data_factories["FTMO-007"]
        exec_factory = node.exec_factories["FTMO-007"]
        assert issubclass(data_factory, LiveDataClientFactory)
        assert issubclass(exec_factory, LiveExecClientFactory)

    def test_strategy_added_with_account_id_threaded_through(self) -> None:
        account = _account(
            "acct-1",
            strategy="ma_crossover",
            strategy_params={"fast_period": 5, "slow_period": 20},
        )
        spec = _spec(
            "acct-1",
            strategy="ma_crossover",
            strategy_params={"fast_period": 5, "slow_period": 20},
        )

        node = build_account_trading_node(
            account=account,
            spec=spec,
            trading_node_cls=_RecordingTradingNode,
        )

        assert len(node.strategies) == 1
        strategy = node.strategies[0]
        # The strategy stamps account_id from spec.account_id; reading
        # it back through the strategy's config proves the param flow.
        assert getattr(strategy.config, "account_id", "") == "acct-1"
        # Strategy params survived the pass-through.
        assert getattr(strategy.config, "fast_period", None) == 5
        assert getattr(strategy.config, "slow_period", None) == 20

    def test_compliance_actor_attached_when_supplied(self) -> None:
        actor = MagicMock(name="PropFirmComplianceActor")
        node = build_account_trading_node(
            account=_account(),
            spec=_spec(compliance_actor=actor),
            trading_node_cls=_RecordingTradingNode,
        )
        assert actor in node.actors

    def test_no_actor_attached_when_compliance_actor_none(self) -> None:
        node = build_account_trading_node(
            account=_account(),
            spec=_spec(compliance_actor=None),
            trading_node_cls=_RecordingTradingNode,
        )
        assert node.actors == []

    def test_empty_bar_subscriptions_raises(self) -> None:
        with pytest.raises(ValueError, match="bar_subscriptions is empty"):
            build_account_trading_node(
                account=_account(),
                spec=_spec(bar_subscriptions=()),
                trading_node_cls=_RecordingTradingNode,
            )

    def test_unknown_strategy_propagates_registry_error(self) -> None:
        account = _account(strategy="not_a_real_strategy")
        spec = _spec(strategy="not_a_real_strategy")
        from src.backtesting.strategy_registry import UnknownStrategyError

        with pytest.raises(UnknownStrategyError):
            build_account_trading_node(
                account=account,
                spec=spec,
                trading_node_cls=_RecordingTradingNode,
            )


# ---------------------------------------------------------------------------
# Per-account isolation — closure correctness
# ---------------------------------------------------------------------------


class TestPerAccountIsolation:
    """Two accounts → two independent factory closures (no cross-talk)."""

    def test_data_factories_close_over_their_own_account_id(self) -> None:
        node_a = build_account_trading_node(
            account=_account("acct-a"),
            spec=_spec("acct-a"),
            trading_node_cls=_RecordingTradingNode,
        )
        node_b = build_account_trading_node(
            account=_account("acct-b"),
            spec=_spec("acct-b"),
            trading_node_cls=_RecordingTradingNode,
        )

        factory_a = node_a.data_factories["ACCT-A"]
        factory_b = node_b.data_factories["ACCT-B"]
        # Distinct factory classes (each built per call).
        assert factory_a is not factory_b
        # The factories' ``create`` methods are distinct closures.
        assert factory_a.create is not factory_b.create

    def test_exec_factories_close_over_their_own_validated_adapter(
        self,
    ) -> None:
        adapter_a = MagicMock(name="adapter-a")
        adapter_b = MagicMock(name="adapter-b")

        spec_a = AccountNodeSpec(
            account_id="acct-a",
            venue=Venue(DEFAULT_VENUE_NAME),
            bar_subscriptions=(("XAUUSD", "1m"),),
            redis_client=MagicMock(),
            validated_adapter=adapter_a,
            strategy_name="ma_crossover",
            strategy_params={},
        )
        spec_b = AccountNodeSpec(
            account_id="acct-b",
            venue=Venue(DEFAULT_VENUE_NAME),
            bar_subscriptions=(("XAUUSD", "1m"),),
            redis_client=MagicMock(),
            validated_adapter=adapter_b,
            strategy_name="ma_crossover",
            strategy_params={},
        )

        node_a = build_account_trading_node(
            account=_account("acct-a"),
            spec=spec_a,
            trading_node_cls=_RecordingTradingNode,
        )
        node_b = build_account_trading_node(
            account=_account("acct-b"),
            spec=spec_b,
            trading_node_cls=_RecordingTradingNode,
        )

        # Sanity — different factory classes per call.
        assert (
            node_a.exec_factories["ACCT-A"]
            is not node_b.exec_factories["ACCT-B"]
        )


# ---------------------------------------------------------------------------
# Build order
# ---------------------------------------------------------------------------


class TestBuildOrder:
    """``build()`` must run before strategies/actors are added.

    Otherwise Nautilus refuses ``trader.add_strategy`` because the
    trader is not yet wired. The factory enforces this ordering — a
    regression here would be a P0 in production.
    """

    def test_build_called_before_strategies_added(self) -> None:
        events: list[str] = []

        class _OrderedNode(_RecordingTradingNode):
            def build(self) -> None:
                events.append("build")
                super().build()

            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                self.trader = MagicMock()
                self.trader.add_strategy = (
                    lambda s: events.append("add_strategy")
                )
                self.trader.add_actor = lambda a: events.append("add_actor")

        build_account_trading_node(
            account=_account(),
            spec=_spec(compliance_actor=MagicMock()),
            trading_node_cls=_OrderedNode,
        )

        # build must precede the trader-touching ops.
        build_idx = events.index("build")
        strategy_idx = events.index("add_strategy")
        actor_idx = events.index("add_actor")
        assert build_idx < strategy_idx
        assert build_idx < actor_idx
