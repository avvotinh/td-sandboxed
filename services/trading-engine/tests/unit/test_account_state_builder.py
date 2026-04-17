"""Unit tests for account state builder (Portfolio → rule-engine context)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.backtesting.account_state_builder import build_account_state


pytestmark = pytest.mark.unit


def _snapshot(
    *,
    balance: float = 100000.0,
    equity: float = 99500.0,
    open_positions: int = 0,
    total_exposure: float = 0.0,
) -> dict:
    return {
        "balance": balance,
        "equity": equity,
        "open_positions": open_positions,
        "total_exposure": total_exposure,
    }


class TestBuildAccountState:
    def test_basic_mapping(self) -> None:
        state = build_account_state(
            portfolio_snapshot=_snapshot(balance=100000, equity=99500),
            initial_balance=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_pnl=Decimal("-500"),
        )
        assert state["balance"] == Decimal("100000")
        assert state["equity"] == Decimal("99500")
        assert state["initial_balance"] == Decimal("100000")
        assert state["peak_balance"] == Decimal("100000")
        assert state["daily_pnl"] == Decimal("-500")

    def test_daily_pnl_percent_computed(self) -> None:
        # daily_pnl=-1000 / initial=100000 = -1.0%
        state = build_account_state(
            portfolio_snapshot=_snapshot(),
            initial_balance=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_pnl=Decimal("-1000"),
        )
        assert state["daily_pnl_percent"] == pytest.approx(-1.0)

    def test_daily_pnl_percent_zero_balance_returns_zero(self) -> None:
        state = build_account_state(
            portfolio_snapshot=_snapshot(balance=0, equity=0),
            initial_balance=Decimal("0"),
            peak_balance=Decimal("0"),
            daily_pnl=Decimal("100"),
        )
        assert state["daily_pnl_percent"] == 0.0

    def test_total_drawdown_percent_from_peak(self) -> None:
        # peak=110000, equity=104500 → DD = (110000-104500)/110000 = 5.0%
        state = build_account_state(
            portfolio_snapshot=_snapshot(balance=104500, equity=104500),
            initial_balance=Decimal("100000"),
            peak_balance=Decimal("110000"),
            daily_pnl=Decimal("0"),
        )
        assert state["total_drawdown_percent"] == pytest.approx(5.0)

    def test_total_drawdown_zero_when_at_peak(self) -> None:
        state = build_account_state(
            portfolio_snapshot=_snapshot(balance=110000, equity=110000),
            initial_balance=Decimal("100000"),
            peak_balance=Decimal("110000"),
            daily_pnl=Decimal("0"),
        )
        assert state["total_drawdown_percent"] == 0.0

    def test_includes_positions_and_exposure(self) -> None:
        state = build_account_state(
            portfolio_snapshot=_snapshot(open_positions=2, total_exposure=5000),
            initial_balance=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert state["open_positions_count"] == 2
        assert state["total_exposure"] == 5000

    def test_contains_all_rule_engine_keys(self) -> None:
        state = build_account_state(
            portfolio_snapshot=_snapshot(),
            initial_balance=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        required = {
            "balance",
            "equity",
            "initial_balance",
            "peak_balance",
            "daily_pnl",
            "daily_pnl_percent",
            "total_drawdown_percent",
            "open_positions_count",
            "total_exposure",
        }
        assert required.issubset(state.keys())
