"""Unit tests for BacktestResult dataclass."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.backtesting.result import BacktestResult, BreachEvent, TradeRecord


pytestmark = pytest.mark.unit


class TestTradeRecord:
    def test_basic_construction(self) -> None:
        t = TradeRecord(
            trade_id="t-1",
            symbol="XAUUSD",
            side="BUY",
            entry_ts=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
            exit_ts=datetime(2026, 4, 17, 14, 0, tzinfo=UTC),
            entry_price=Decimal("2400"),
            exit_price=Decimal("2410"),
            quantity=Decimal("0.1"),
            pnl=Decimal("1.0"),
        )
        assert t.symbol == "XAUUSD"
        assert t.pnl == Decimal("1.0")

    def test_frozen(self) -> None:
        t = TradeRecord(
            trade_id="t-1",
            symbol="XAUUSD",
            side="BUY",
            entry_ts=datetime.now(UTC),
            exit_ts=datetime.now(UTC),
            entry_price=Decimal("2400"),
            exit_price=Decimal("2410"),
            quantity=Decimal("0.1"),
            pnl=Decimal("1.0"),
        )
        with pytest.raises(FrozenInstanceError):
            t.pnl = Decimal("999")  # type: ignore[misc]


class TestBreachEvent:
    def test_basic_construction(self) -> None:
        e = BreachEvent(
            ts=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
            rule_name="daily_loss_limit",
            current_value=5.2,
            threshold_value=5.0,
            message="Daily loss 5.2% exceeds 5% limit",
        )
        assert e.rule_name == "daily_loss_limit"

    def test_frozen(self) -> None:
        e = BreachEvent(
            ts=datetime.now(UTC),
            rule_name="r",
            current_value=1,
            threshold_value=2,
            message="m",
        )
        with pytest.raises(FrozenInstanceError):
            e.rule_name = "changed"  # type: ignore[misc]


class TestBacktestResult:
    def _minimal(self) -> BacktestResult:
        return BacktestResult(
            strategy_name="ma_crossover",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 4, 1, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=Decimal("105000"),
            equity_curve=[
                (datetime(2026, 1, 1, tzinfo=UTC), Decimal("100000")),
                (datetime(2026, 2, 1, tzinfo=UTC), Decimal("102000")),
                (datetime(2026, 4, 1, tzinfo=UTC), Decimal("105000")),
            ],
            trades=[],
            breaches=[],
            metrics=None,
        )

    def test_equity_curve_length_matches_snapshots(self) -> None:
        r = self._minimal()
        assert len(r.equity_curve) == 3

    def test_frozen(self) -> None:
        r = self._minimal()
        with pytest.raises(FrozenInstanceError):
            r.strategy_name = "changed"  # type: ignore[misc]

    def test_contains_trades_and_breaches_lists(self) -> None:
        r = self._minimal()
        assert r.trades == []
        assert r.breaches == []

    def test_metrics_optional(self) -> None:
        r = self._minimal()
        assert r.metrics is None

    def test_config_snapshot_defaults_to_none(self) -> None:
        r = self._minimal()
        assert r.config_snapshot is None

    def test_config_snapshot_carries_arbitrary_dict(self) -> None:
        snapshot = {
            "dataset": {"spec_name": "xauusd-validation", "fingerprint": "abc123"},
            "strategy_params": {"fast_period": 5, "slow_period": 20},
        }
        r = BacktestResult(
            strategy_name="ma_crossover",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 4, 1, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=Decimal("105000"),
            config_snapshot=snapshot,
        )
        assert r.config_snapshot == snapshot
