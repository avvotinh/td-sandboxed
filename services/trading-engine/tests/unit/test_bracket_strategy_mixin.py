"""Unit tests for BracketStrategyMixin (Story 8.9)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.strategies.bracket_strategy import BracketStrategyMixin


class _Host(BracketStrategyMixin):
    """Minimal host that stubs the Nautilus attributes the mixin reads."""

    def __init__(self, *, cache=None, portfolio=None, bar_type=None):
        self.cache = cache
        self.portfolio = portfolio
        self.config = MagicMock(bar_type=bar_type)


@pytest.mark.unit
class TestLastBar:
    def test_returns_cached_bar(self) -> None:
        cache = MagicMock()
        bar = object()
        cache.bar.return_value = bar
        host = _Host(cache=cache, bar_type="bt")
        assert host._last_bar() is bar

    def test_none_when_cache_reports_empty(self) -> None:
        """Nautilus cache raises ``KeyError`` / ``IndexError`` / ``LookupError``
        when the requested bar isn't populated yet. Programming errors
        (``RuntimeError``, etc.) must propagate so misconfiguration surfaces
        loudly instead of silently producing zero signals.
        """
        for exc_cls in (KeyError, IndexError, LookupError):
            cache = MagicMock()
            cache.bar.side_effect = exc_cls("empty")
            host = _Host(cache=cache, bar_type="bt")
            assert host._last_bar() is None

    def test_programmer_errors_propagate(self) -> None:
        cache = MagicMock()
        cache.bar.side_effect = RuntimeError("broken cache")
        host = _Host(cache=cache, bar_type="bt")
        with pytest.raises(RuntimeError):
            host._last_bar()


@pytest.mark.unit
class TestReadAccountBalance:
    def _bar_type(self):
        bar_type = MagicMock()
        bar_type.instrument_id.venue = "SIM"
        return bar_type

    def test_zero_when_portfolio_missing_account(self) -> None:
        portfolio = MagicMock()
        portfolio.account.return_value = None
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        assert host._read_account_balance() == Decimal("0")

    def test_zero_when_portfolio_raises(self) -> None:
        portfolio = MagicMock()
        portfolio.account.side_effect = RuntimeError("boom")
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        assert host._read_account_balance() == Decimal("0")

    def test_reads_balance_when_available(self) -> None:
        portfolio = MagicMock()
        account = MagicMock()
        money = MagicMock()
        money.as_double.return_value = 120_500.50
        account.balance_total.return_value = money
        portfolio.account.return_value = account
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        # Decimal(str(float)) is a controlled conversion; this proves the
        # mixin plumbs the money all the way through.
        assert host._read_account_balance() == Decimal("120500.5")

    def test_zero_when_balance_is_none(self) -> None:
        portfolio = MagicMock()
        account = MagicMock()
        account.balance_total.return_value = None
        portfolio.account.return_value = account
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        assert host._read_account_balance() == Decimal("0")
