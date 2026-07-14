"""Unit tests for the shared portfolio balance/equity readers."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest

from src.backtesting.portfolio_equity import (
    read_account_balance,
    read_unrealized_pnl,
)

pytestmark = pytest.mark.unit


def _money(value: float) -> Mock:
    money = Mock()
    money.as_double = Mock(return_value=value)
    return money


class TestReadAccountBalance:
    def test_reads_balance_total_as_decimal(self) -> None:
        account = Mock()
        account.balance_total = Mock(return_value=_money(100500.25))
        portfolio = Mock()
        portfolio.account = Mock(return_value=account)
        balance = read_account_balance(
            portfolio, "SIM", "USD", Decimal("100000")
        )
        assert balance == Decimal("100500.25")

    def test_missing_account_falls_back(self) -> None:
        portfolio = Mock()
        portfolio.account = Mock(return_value=None)
        assert read_account_balance(
            portfolio, "SIM", "USD", Decimal("100000")
        ) == Decimal("100000")

    def test_missing_balance_total_falls_back(self) -> None:
        account = Mock()
        account.balance_total = Mock(return_value=None)
        portfolio = Mock()
        portfolio.account = Mock(return_value=account)
        assert read_account_balance(
            portfolio, "SIM", "USD", Decimal("100000")
        ) == Decimal("100000")


class TestReadUnrealizedPnl:
    def test_sums_currency_entry(self) -> None:
        portfolio = Mock()
        portfolio.unrealized_pnls = Mock(return_value={"USD": _money(-321.5)})
        assert read_unrealized_pnl(portfolio, "SIM", "USD") == Decimal(
            "-321.5"
        )

    def test_missing_currency_entry_is_zero(self) -> None:
        portfolio = Mock()
        portfolio.unrealized_pnls = Mock(return_value={})
        assert read_unrealized_pnl(portfolio, "SIM", "USD") == Decimal("0")

    def test_lookup_failure_degrades_to_zero(self) -> None:
        portfolio = Mock()
        portfolio.unrealized_pnls = Mock(side_effect=RuntimeError("no venue"))
        assert read_unrealized_pnl(portfolio, "SIM", "USD") == Decimal("0")
