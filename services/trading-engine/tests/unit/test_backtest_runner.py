"""Unit tests for BacktestRunner (delegation to Nautilus BacktestEngine).

The runner is a thin façade: tests verify that calls are forwarded in the
right order and that the runner exposes a ``get_result`` that assembles
a ``BacktestResult`` from the engine + attached ``FtmoComplianceActor``.

End-to-end integration is covered by ``tests/integration/test_backtest_smoke.py``.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
from src.backtesting.ftmo_preset import FtmoPreset
from src.backtesting.result import BacktestResult


pytestmark = pytest.mark.unit


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
        preset = FtmoPreset(
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


class TestAttachFtmoCompliance:
    def test_attaches_actor_to_engine(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        mock_engine = Mock()
        runner._engine = mock_engine
        mock_rule_engine = Mock()
        actor = runner.attach_ftmo_compliance(
            rule_engine=mock_rule_engine, account_id="ftmo-test"
        )
        mock_engine.add_actor.assert_called_once_with(actor)
        assert runner.ftmo_actor is actor

    def test_without_attach_actor_is_none(self, runner_config) -> None:
        runner = BacktestRunner(config=runner_config)
        assert runner.ftmo_actor is None


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
        runner._ftmo_actor = mock_actor

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
