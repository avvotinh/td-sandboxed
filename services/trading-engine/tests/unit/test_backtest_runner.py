"""Unit tests for BacktestRunner (delegation to Nautilus BacktestEngine).

The runner is a thin façade: tests verify that calls are forwarded in the
right order and that the runner exposes a ``get_result`` that assembles
a ``BacktestResult`` from the engine + attached ``PropFirmComplianceActor``.

End-to-end integration is covered by ``tests/integration/test_backtest_smoke.py``.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
from src.backtesting.prop_firm_preset import PropFirmPreset
from src.backtesting.result import BacktestResult
from src.config.firm_profile import (
    InstrumentRegimeConfig,
    RegimeConfig,
    RegimeThresholds,
)
from src.kernel.regime.state_store import RegimeStateStore


pytestmark = pytest.mark.unit


def _enabled_regime_config() -> RegimeConfig:
    """A minimal enabled RegimeConfig (real, for fidelity in delegation)."""
    thresholds = RegimeThresholds(
        adx_trend_min=25.0,
        adx_strong_trend=40.0,
        bb_width_low_pct=0.30,
        bb_width_high_pct=0.80,
        realized_vol_high=0.025,
        ema_slope_trend_threshold=0.0005,
    )
    instrument = InstrumentRegimeConfig(
        timeframe="M5",
        thresholds=thresholds,
        adx_period=14,
        bb_period=20,
        bb_stddev=2.0,
        bb_baseline_window=200,
        realized_vol_window=20,
        ema_slope_period=20,
        ema_slope_lookback=5,
    )
    return RegimeConfig(
        enabled=True,
        confirmation_bars=2,
        warmup_bars=50,
        feature_window=200,
        instruments={"XAUUSD": instrument},
    )


@pytest.fixture
def runner_config() -> BacktestRunnerConfig:
    return BacktestRunnerConfig(
        strategy_name="ma_crossover",
        initial_balance=Decimal("100000"),
        currency="USD",
    )


class TestFromPreset:
    """BacktestRunnerConfig.from_preset wires FTMO thresholds from YAML."""

    def test_threshold_fields_populated_from_preset(self) -> None:
        preset = PropFirmPreset(
            name="Custom",
            daily_loss_pct=3.5,
            max_drawdown_pct=7.5,
            profit_target_pct=8.0,
            min_trading_days=2,
            max_position_lots=50.0,
        )
        cfg = BacktestRunnerConfig.from_preset(
            strategy_name="s", initial_balance=Decimal("50000"), preset=preset,
        )
        assert cfg.max_dd_pct == 7.5
        assert cfg.profit_target_pct == 8.0
        assert cfg.min_trading_days == 2


class TestBacktestRunnerInit:
    def test_stores_config(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        assert runner.config.strategy_name == "ma_crossover"
        assert runner.config.initial_balance == Decimal("100000")

    def test_engine_created_on_demand(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        # Engine is accessible
        assert runner.engine is not None


class TestBacktestRunnerDelegation:
    def test_add_venue_delegates(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        runner.add_venue(
            venue="SIM",
            oms_type="NETTING",
            account_type="MARGIN",
            base_currency="USD",
            starting_balances=[],
        )
        mock_engine.add_venue.assert_called_once()

    def test_add_instrument_delegates(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        instrument = Mock()
        runner.add_instrument(instrument)
        mock_engine.add_instrument.assert_called_once_with(instrument)

    def test_add_data_delegates(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        bars = [Mock(), Mock(), Mock()]
        runner.add_data(bars)
        mock_engine.add_data.assert_called_once_with(bars)

    def test_add_strategy_delegates(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        strategy = Mock()
        runner.add_strategy(strategy)
        mock_engine.add_strategy.assert_called_once_with(strategy)


class TestAttachPropFirmCompliance:
    def test_attaches_actor_to_engine(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        mock_rule_engine = Mock()
        actor = runner.attach_prop_firm_compliance(
            rule_engine=mock_rule_engine, account_id="ftmo-test"
        )
        mock_engine.add_actor.assert_called_once_with(actor)
        assert runner.prop_firm_actor is actor

    def test_without_attach_actor_is_none(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        assert runner.prop_firm_actor is None


class TestAttachRegime:
    """Story 15.8: attach_regime mirrors attach_prop_firm_compliance.

    Delegates to ``build_regime_actor`` so backtest + live construct the
    actor identically; ``enabled=False`` yields ``None`` (no actor added).
    """

    def test_attaches_actor_when_enabled(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        store = RegimeStateStore()
        sentinel = Mock()
        with patch(
            "src.engine.actors.build_regime_actor", return_value=sentinel
        ) as build:
            actor = runner.attach_regime(
                regime_config=_enabled_regime_config(),
                bar_type="XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL",
                regime_state=store,
            )
        assert actor is sentinel
        mock_engine.add_actor.assert_called_once_with(sentinel)
        assert runner.regime_actor is sentinel
        # R-E: backtest passes NO audit hook → build derives audit_to_db=False
        # → zero rows to the live audit_logs hypertable.
        _, kwargs = build.call_args
        assert kwargs["audit_hook"] is None
        # The caller's store is passed straight through (same object the
        # strategy is injected with, so publish == read).
        assert kwargs["regime_state"] is store

    def test_no_actor_when_disabled(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        # build_regime_actor returns None for a disabled config.
        with patch("src.engine.actors.build_regime_actor", return_value=None):
            actor = runner.attach_regime(
                regime_config=Mock(enabled=False),
                bar_type="XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL",
                regime_state=RegimeStateStore(),
            )
        assert actor is None
        mock_engine.add_actor.assert_not_called()
        assert runner.regime_actor is None

    def test_regime_actor_defaults_none(self, runner_config) -> None:
        assert BacktestRunner(config=runner_config).regime_actor is None

    def test_regime_config_is_not_picklable(self) -> None:
        """Pins the constraint that forces ``regime_config`` to be a
        ``run_backtest`` call-time kwarg instead of a (serializable)
        ``BacktestJobConfig`` field: ``RegimeConfig.instruments`` is a frozen
        ``MappingProxyType`` which pickle cannot handle. If this ever stops
        raising, revisit the wiring in ``runner_facade.run_backtest``.
        """
        import pickle

        with pytest.raises((TypeError, pickle.PicklingError)):
            pickle.dumps(_enabled_regime_config())


class TestRun:
    def test_run_calls_engine_run(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        runner.run()
        mock_engine.run.assert_called_once()


class TestGetResult:
    def test_returns_backtest_result(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        mock_engine.cache.positions_closed = Mock(return_value=[])
        runner._engine = mock_engine

        mock_actor = Mock()
        mock_actor.equity_curve = []
        mock_actor.breaches = []
        runner._prop_firm_actor = mock_actor

        with patch(
            "src.backtesting.engine.calculate_metrics"
        ) as calc:
            calc.return_value = Mock()
            result = runner.get_result(final_balance=Decimal("100500"))
            assert isinstance(result, BacktestResult)
            calc.assert_called_once()

    def test_without_actor_uses_empty_curve(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        mock_engine.cache.positions_closed = Mock(return_value=[])
        runner._engine = mock_engine
        with patch("src.backtesting.engine.calculate_metrics") as calc:
            calc.return_value = Mock()
            result = runner.get_result(final_balance=Decimal("100000"))
            assert result.equity_curve == []
            assert result.breaches == []


def _mock_closed_position(position_id: str = "P-001") -> Mock:
    """A minimal closed-position stand-in for cache.positions_closed().

    Mirrors the real cache shape: a CLOSED position reports
    ``side == PositionSide.FLAT``; the entry direction survives only on
    ``entry`` (the entry order's ``OrderSide``).
    """
    from nautilus_trader.model.enums import OrderSide, PositionSide

    pos = Mock()
    pos.id = position_id
    pos.side = PositionSide.FLAT
    pos.entry = OrderSide.BUY
    pos.instrument_id = "XAUUSD.SIM"
    pos.ts_opened = 1_700_000_000_000_000_000
    pos.ts_closed = 1_700_000_600_000_000_000
    pos.ts_last = pos.ts_closed
    pos.avg_px_open = 2000.0
    pos.avg_px_close = 2010.0
    pos.quantity = "1.00"
    pos.realized_pnl = None
    return pos


def _mock_sl_order(
    *,
    initial_trigger: str = "1990.000",
    final_trigger: str = "1990.000",
    update_triggers: tuple[tuple[int, str], ...] = (),
) -> Mock:
    """STOP_MARKET SL leg with an OrderInitialized + OrderUpdated history."""
    from nautilus_trader.model.enums import OrderType
    from nautilus_trader.model.events import OrderInitialized, OrderUpdated

    init_event = Mock(spec=OrderInitialized)
    init_event.options = {"trigger_price": initial_trigger}
    updates = []
    for ts_event, trigger in update_triggers:
        ev = Mock(spec=OrderUpdated)
        ev.trigger_price = trigger
        ev.ts_event = ts_event
        updates.append(ev)
    order = Mock()
    order.order_type = OrderType.STOP_MARKET
    order.ts_init = 1
    order.events = [init_event, *updates]
    order.trigger_price = final_trigger
    return order


def _mock_tp_order(price: str = "2020.000") -> Mock:
    from nautilus_trader.model.enums import OrderType

    order = Mock()
    order.order_type = OrderType.LIMIT
    order.ts_init = 1
    order.events = []
    order.price = price
    return order


def _mock_entry_order() -> Mock:
    from nautilus_trader.model.enums import OrderType

    order = Mock()
    order.order_type = OrderType.MARKET
    order.ts_init = 0
    order.events = []
    return order


class TestExtractTradeBrackets:
    """_extract_trades enriches TradeRecord with bracket SL/TP levels."""

    def _runner_with_cache(
        self, runner_config, position, orders
    ) -> BacktestRunner:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        mock_engine.cache.positions_closed = Mock(return_value=[position])
        mock_engine.cache.orders_for_position = Mock(return_value=orders)
        runner._engine = mock_engine
        return runner

    def test_trade_record_defaults_have_no_bracket_levels(self) -> None:
        from datetime import UTC, datetime

        from src.backtesting.result import TradeRecord

        record = TradeRecord(
            trade_id="t",
            symbol="XAUUSD.SIM",
            side="BUY",
            entry_ts=datetime(2024, 1, 1, tzinfo=UTC),
            exit_ts=datetime(2024, 1, 2, tzinfo=UTC),
            entry_price=Decimal("2000"),
            exit_price=Decimal("2010"),
            quantity=Decimal("1"),
            pnl=Decimal("10"),
        )
        assert record.sl_price is None
        assert record.tp_price is None
        assert record.sl_updates == ()

    def test_extracts_initial_sl_and_tp_from_bracket_legs(
        self, runner_config
    ) -> None:
        pos = _mock_closed_position()
        orders = [
            _mock_entry_order(),
            _mock_sl_order(initial_trigger="1990.000"),
            _mock_tp_order(price="2020.000"),
        ]
        runner = self._runner_with_cache(runner_config, pos, orders)

        [trade] = runner._extract_trades()
        assert trade.sl_price == Decimal("1990.000")
        assert trade.tp_price == Decimal("2020.000")
        assert trade.sl_updates == ()

    def test_extracts_trailing_sl_update_history(self, runner_config) -> None:
        ts_ns = 1_700_000_300_000_000_000
        pos = _mock_closed_position()
        orders = [
            _mock_entry_order(),
            _mock_sl_order(
                initial_trigger="1990.000",
                final_trigger="2005.000",
                update_triggers=(
                    (ts_ns, "2000.000"),
                    (ts_ns + 300_000_000_000, "2005.000"),
                ),
            ),
            _mock_tp_order(),
        ]
        runner = self._runner_with_cache(runner_config, pos, orders)

        [trade] = runner._extract_trades()
        assert trade.sl_price == Decimal("1990.000")
        assert [u.price for u in trade.sl_updates] == [
            Decimal("2000.000"),
            Decimal("2005.000"),
        ]
        assert all(u.ts.tzinfo is not None for u in trade.sl_updates)

    def test_no_bracket_orders_leaves_levels_none(self, runner_config) -> None:
        pos = _mock_closed_position()
        runner = self._runner_with_cache(
            runner_config, pos, [_mock_entry_order()]
        )
        [trade] = runner._extract_trades()
        assert trade.sl_price is None
        assert trade.tp_price is None

    def test_orders_lookup_failure_degrades_gracefully(
        self, runner_config
    ) -> None:
        pos = _mock_closed_position()
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        mock_engine.cache.positions_closed = Mock(return_value=[pos])
        mock_engine.cache.orders_for_position = Mock(
            side_effect=RuntimeError("cache gone")
        )
        runner._engine = mock_engine

        [trade] = runner._extract_trades()
        assert trade.sl_price is None
        assert trade.tp_price is None
        assert trade.sl_updates == ()

    def test_closed_position_side_maps_from_entry_order_side(
        self, runner_config
    ) -> None:
        """Closed positions are FLAT — side must come from ``pos.entry``."""
        from nautilus_trader.model.enums import OrderSide

        long_pos = _mock_closed_position("P-LONG")
        short_pos = _mock_closed_position("P-SHORT")
        short_pos.entry = OrderSide.SELL

        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        mock_engine.cache.positions_closed = Mock(
            return_value=[long_pos, short_pos]
        )
        mock_engine.cache.orders_for_position = Mock(return_value=[])
        runner._engine = mock_engine

        buy, sell = runner._extract_trades()
        assert buy.side == "BUY"
        assert sell.side == "SELL"

    def test_closed_position_zero_quantity_falls_back_to_peak_qty(
        self, runner_config
    ) -> None:
        """CLOSED positions report remaining quantity 0 — the traded size
        must come from ``peak_qty`` (Contract v2 needs real lot sizes)."""
        pos = _mock_closed_position()
        pos.quantity = "0"
        pos.peak_qty = "50.00"
        runner = self._runner_with_cache(
            runner_config, pos, [_mock_entry_order()]
        )
        [trade] = runner._extract_trades()
        assert trade.quantity == Decimal("50.00")

    def test_nonzero_quantity_is_kept_verbatim(self, runner_config) -> None:
        pos = _mock_closed_position()  # quantity = "1.00"
        runner = self._runner_with_cache(
            runner_config, pos, [_mock_entry_order()]
        )
        [trade] = runner._extract_trades()
        assert trade.quantity == Decimal("1.00")

    def test_missing_initialized_options_falls_back_to_order_trigger(
        self, runner_config
    ) -> None:
        from nautilus_trader.model.enums import OrderType

        order = Mock()
        order.order_type = OrderType.STOP_MARKET
        order.ts_init = 1
        order.events = []
        order.trigger_price = "1985.000"
        pos = _mock_closed_position()
        runner = self._runner_with_cache(runner_config, pos, [order])

        [trade] = runner._extract_trades()
        assert trade.sl_price == Decimal("1985.000")
