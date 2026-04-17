"""Unit tests for FtmoMetricsSchema Pydantic model."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.backtesting.metrics.schema import (
    DrawdownMetrics,
    FtmoComplianceMetrics,
    FtmoMetricsSchema,
    PnlMetrics,
    RiskMetrics,
    TradeMetrics,
)


pytestmark = pytest.mark.unit


def _sample_schema() -> FtmoMetricsSchema:
    return FtmoMetricsSchema(
        strategy_name="ma_crossover",
        pnl=PnlMetrics(
            gross_pnl=1000.0,
            net_pnl=950.0,
            return_pct=9.5,
            profit_factor=2.0,
            expectancy=5.0,
            avg_r_multiple=1.5,
        ),
        drawdown=DrawdownMetrics(
            max_overall_dd_pct=3.2,
            max_overall_dd_abs=3200.0,
            max_daily_dd_pct=1.8,
            avg_daily_dd_pct=0.5,
            recovery_factor=0.3,
        ),
        risk=RiskMetrics(
            sharpe_ratio=1.5,
            sortino_ratio=2.0,
            calmar_ratio=2.9,
            max_consecutive_losses=3,
        ),
        trades=TradeMetrics(
            total_trades=50,
            winning_trades=30,
            losing_trades=20,
            win_rate=0.6,
            avg_win=50.0,
            avg_loss=-25.0,
        ),
        ftmo_compliance=FtmoComplianceMetrics(
            daily_loss_breaches=0,
            max_dd_breach=False,
            profit_target_hit=False,
            min_trading_days_met=True,
        ),
    )


class TestFtmoMetricsSchemaHappyPath:
    def test_valid_schema_constructs(self) -> None:
        schema = _sample_schema()
        assert schema.strategy_name == "ma_crossover"
        assert schema.pnl.net_pnl == 950.0
        assert schema.ftmo_compliance.profit_target_hit is False

    def test_json_round_trip(self) -> None:
        schema = _sample_schema()
        payload = schema.model_dump()
        as_json = json.dumps(payload, default=str)
        parsed = json.loads(as_json)
        schema2 = FtmoMetricsSchema.model_validate(parsed)
        assert schema2 == schema


class TestFtmoMetricsSchemaValidation:
    def test_win_rate_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TradeMetrics(
                total_trades=10,
                winning_trades=5,
                losing_trades=5,
                win_rate=1.5,  # must be 0..1
                avg_win=1.0,
                avg_loss=-1.0,
            )

    def test_negative_trades_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TradeMetrics(
                total_trades=-1,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                avg_win=0.0,
                avg_loss=0.0,
            )

    def test_drawdown_pct_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            DrawdownMetrics(
                max_overall_dd_pct=-1.0,
                max_overall_dd_abs=-100,
                max_daily_dd_pct=0,
                avg_daily_dd_pct=0,
                recovery_factor=0,
            )


class TestFtmoComplianceMetrics:
    def test_daily_loss_breaches_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            FtmoComplianceMetrics(
                daily_loss_breaches=-1,
                max_dd_breach=False,
                profit_target_hit=False,
                min_trading_days_met=True,
            )
