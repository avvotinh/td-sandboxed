"""Story 15.4 — actor-before-strategy ``on_bar`` ordering spike (risk R1).

The RegimeActor design (``docs/design/regime-actor-design.md`` §3.4) needs the
regime actor to publish the confirmed regime into the shared ``RegimeStateStore``
**before** the strategy reads it for the **same** bar. Whether Nautilus
dispatches ``Actor.on_bar`` ahead of ``Strategy.on_bar`` for one ``BarType`` is
risk R1 — it must be *proven*, not assumed, because it gates story 15.7
(the entry-only regime gate placed in ``BaseStrategy``).

This focused integration test runs the **real** ``BacktestEngine`` (no mocks)
with a minimal probe actor and probe strategy, both subscribed to the same
``BarType``. Each records the order in which its ``on_bar`` fires into a shared
log. The composition mirrors what story 15.8 will use: the actor is attached
(``add_actor``) **before** the strategy (``add_strategy``).

Result (2026-05-24, nautilus_trader 1.221.0 — see
``docs/sprint-artifacts/15-4-actor-ordering-spike.md``): the actor's ``on_bar``
precedes the strategy's for **every** bar, and does so **regardless of
add-order** (adding the strategy before the actor does not flip it). Story 15.7
therefore adopts the **same-bar** contract: the strategy reads the current
bar's confirmed regime, no one-bar-lag fallback needed.

The one-bar-lag fallback (strategy reads the regime confirmed as of the
*previous* bar — acceptable because the hysteresis filter already imposes
multi-bar confirmation latency) stays documented in the design as the
contingency if a future Nautilus version ever flips the order and these tests
start failing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.trading.strategy import Strategy

from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
from src.backtesting.synthetic_bars import generate_bars

pytestmark = pytest.mark.integration


# A single bar produces one entry per subscriber; the shared log records
# ``(role, ts_init)`` in the exact order Nautilus invoked the handlers.
DispatchLog = list[tuple[str, int]]


class _ProbeActorConfig(ActorConfig, frozen=True):
    bar_type: BarType


class _ProbeActor(Actor):
    """Minimal actor that timestamps each ``on_bar`` into a shared log.

    The ``log`` is injected via the constructor (not the frozen config),
    mirroring how ``PropFirmComplianceActor`` takes its ``rule_engine`` as a
    separate constructor argument.
    """

    def __init__(self, config: _ProbeActorConfig, log: DispatchLog) -> None:
        super().__init__(config=config)
        # Store only what we need as plain Python attributes. ``_bar_type``
        # and ``_dispatch_log`` are not Cython ``Component`` cdef slots so
        # they are writable; ``_log`` is NOT (it is the read-only Component
        # logger), which is why the dispatch log uses a distinct name.
        self._bar_type = config.bar_type
        self._dispatch_log = log

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        self._dispatch_log.append(("actor", bar.ts_init))


# ``kw_only=True`` mirrors the production ``BaseStrategyConfig`` convention
# (``src/strategies/config.py``); ``ActorConfig`` subclasses in this codebase
# do not use it, hence the asymmetry with ``_ProbeActorConfig`` above.
class _ProbeStrategyConfig(StrategyConfig, frozen=True, kw_only=True):
    bar_type: BarType


class _ProbeStrategy(Strategy):
    """Minimal strategy that timestamps each ``on_bar`` into the shared log."""

    def __init__(self, config: _ProbeStrategyConfig, log: DispatchLog) -> None:
        super().__init__(config=config)
        self._bar_type = config.bar_type
        self._dispatch_log = log

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        self._dispatch_log.append(("strategy", bar.ts_init))


def _run_probe(*, attach_actor_first: bool) -> tuple[DispatchLog, int]:
    """Run a real backtest with both probes; return the dispatch log + bar count.

    ``attach_actor_first`` controls add-order so the test can show whether the
    dispatch order depends on registration order.
    """
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-BID-EXTERNAL")

    bar_count = 50
    start_ts = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    bars = generate_bars(
        pattern="trending",
        count=bar_count,
        start_price=1.1000,
        seed=7,
        start_ts=start_ts,
        price_precision=instrument.price_precision,
        volume_precision=instrument.size_precision,
        bar_type=bar_type,
        drift_scale=0.0001,
        noise_scale=0.0005,
    )

    runner = BacktestRunner(
        config=BacktestRunnerConfig(
            strategy_name="ordering_probe",
            initial_balance=Decimal("100000"),
            currency="USD",
        )
    )

    # Fresh per run — intentional. Each _run_probe call gets its own engine,
    # probes, and log so the two tests (and the two parametrize variants) share
    # no mutable state. Do NOT hoist this to a module-level fixture.
    log: DispatchLog = []
    try:
        runner.add_venue(
            venue=instrument.id.venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(100000, USD)],
            base_currency=USD,
        )
        runner.add_instrument(instrument)
        runner.add_data(bars)

        actor = _ProbeActor(_ProbeActorConfig(bar_type=bar_type), log)
        strategy = _ProbeStrategy(_ProbeStrategyConfig(bar_type=bar_type), log)

        if attach_actor_first:
            runner.engine.add_actor(actor)
            runner.add_strategy(strategy)
        else:
            runner.add_strategy(strategy)
            runner.engine.add_actor(actor)

        runner.run()
    finally:
        runner.dispose()

    return log, bar_count


def test_actor_on_bar_precedes_strategy_same_bar() -> None:
    """R1: with the actor attached first, its ``on_bar`` fires before the strategy's.

    This is the configuration story 15.8 uses (add-order regime → strategy →
    compliance). The shared log must interleave strictly as
    ``actor@t0, strategy@t0, actor@t1, strategy@t1, ...`` — i.e. for every bar
    the actor entry precedes the strategy entry at the *same* timestamp.
    """
    log, bar_count = _run_probe(attach_actor_first=True)

    # Both subscribers saw every bar.
    actor_events = [ts for role, ts in log if role == "actor"]
    strategy_events = [ts for role, ts in log if role == "strategy"]
    assert len(actor_events) == bar_count, (
        f"actor saw {len(actor_events)} bars, expected {bar_count}"
    )
    assert len(strategy_events) == bar_count, (
        f"strategy saw {len(strategy_events)} bars, expected {bar_count}"
    )

    # Strict interleave: pair 2i = actor@t_i, pair 2i+1 = strategy@t_i.
    assert len(log) == 2 * bar_count
    for i in range(bar_count):
        actor_role, actor_ts = log[2 * i]
        strat_role, strat_ts = log[2 * i + 1]
        assert actor_role == "actor", f"bar {i}: expected actor first, got {log[2 * i]}"
        assert strat_role == "strategy", (
            f"bar {i}: expected strategy second, got {log[2 * i + 1]}"
        )
        assert actor_ts == strat_ts, (
            f"bar {i}: actor/strategy saw different timestamps "
            f"({actor_ts} vs {strat_ts})"
        )


@pytest.mark.parametrize("attach_actor_first", [True, False])
def test_actor_precedes_strategy_regardless_of_add_order(
    attach_actor_first: bool,
) -> None:
    """R1, stronger form: actor wins each timestamp even when added *after* the strategy.

    The spike's empirical finding (2026-05-24, nautilus_trader 1.221.0) is that
    Nautilus dispatches every actor's ``on_bar`` before every strategy's for the
    same bar **independent of registration order** — adding the strategy first
    does not flip the order. This is a *stronger* guarantee than design §3.4
    assumed ("relies on add-order"). Locking it in here means a future Nautilus
    upgrade that makes dispatch order add-order-sensitive (or strategy-first)
    fails this test and forces the 15.7 contract to be re-evaluated.
    """
    log, bar_count = _run_probe(attach_actor_first=attach_actor_first)

    # Guard against a vacuous pass: if a subscriber silently received zero
    # bars the dicts below would both be empty and the ordering loop would
    # never run. Assert both probes saw every bar first.
    assert sum(role == "actor" for role, _ in log) == bar_count, "actor missed bars"
    assert sum(role == "strategy" for role, _ in log) == bar_count, (
        "strategy missed bars"
    )

    first_actor_idx: dict[int, int] = {}
    first_strategy_idx: dict[int, int] = {}
    for idx, (role, ts) in enumerate(log):
        if role == "actor":
            first_actor_idx.setdefault(ts, idx)
        else:
            first_strategy_idx.setdefault(ts, idx)

    assert set(first_actor_idx) == set(first_strategy_idx)
    for ts in first_actor_idx:
        assert first_actor_idx[ts] < first_strategy_idx[ts], (
            f"attach_actor_first={attach_actor_first}, ts={ts}: strategy.on_bar "
            f"(idx {first_strategy_idx[ts]}) ran before actor.on_bar "
            f"(idx {first_actor_idx[ts]}) — R1 same-bar contract broken"
        )
