"""Unit tests for BracketStrategyMixin (Story 8.9)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

from src.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
)


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


# ---------------------------------------------------------------------------
# BracketStrategyConfig — cross-cutting R:R guard (review 2026-05-02 priority 1)
# ---------------------------------------------------------------------------


def _bracket_config(**overrides):
    base = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
    )
    base.update(overrides)
    return BracketStrategyConfig(**base)


@pytest.mark.unit
class TestBracketStrategyConfigValidation:
    def test_defaults_pass(self) -> None:
        cfg = _bracket_config()
        assert cfg.sl_atr_mult == Decimal("1.5")
        assert cfg.tp_atr_mult == Decimal("3.0")

    @pytest.mark.parametrize("bad", [0, -1, -14])
    def test_atr_period_must_be_positive(self, bad: int) -> None:
        with pytest.raises(ValueError, match="atr_period"):
            _bracket_config(atr_period=bad)

    @pytest.mark.parametrize(
        "field, bad_value",
        [
            ("sl_atr_mult", Decimal("0")),
            ("sl_atr_mult", Decimal("-0.5")),
            ("tp_atr_mult", Decimal("0")),
            ("tp_atr_mult", Decimal("-1.0")),
            ("risk_percent", Decimal("0")),
            ("risk_percent", Decimal("-0.1")),
            ("pip_size", Decimal("0")),
            ("pip_value_per_lot", Decimal("0")),
        ],
    )
    def test_decimal_fields_must_be_positive(
        self, field: str, bad_value: Decimal
    ) -> None:
        with pytest.raises(ValueError, match=field):
            _bracket_config(**{field: bad_value})

    def test_sl_must_be_strictly_less_than_tp(self) -> None:
        # R:R below 1 is degenerate for ATR brackets — TP closer to entry
        # than SL implies the strategy expects to lose on average.
        with pytest.raises(ValueError, match="sl_atr_mult"):
            _bracket_config(
                sl_atr_mult=Decimal("3.0"),
                tp_atr_mult=Decimal("1.0"),
            )

    def test_sl_equal_to_tp_is_rejected(self) -> None:
        # 1:1 R:R is the boundary; reject it explicitly so backtest
        # operators can't ship a no-edge config by accident.
        with pytest.raises(ValueError, match="sl_atr_mult"):
            _bracket_config(
                sl_atr_mult=Decimal("2.0"),
                tp_atr_mult=Decimal("2.0"),
            )
