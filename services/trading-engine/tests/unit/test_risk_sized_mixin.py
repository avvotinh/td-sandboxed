"""Unit tests for RiskSizedMixin.

``size_from_risk`` is the single lot→engine-unit conversion point
(redesign plan Track 1.3): the sizer returns MT5 lots, the mixin
resolves the symbol's :class:`ContractSpec` from ``config.instrument_id``
and returns lots × contract_size.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)


pytestmark = pytest.mark.unit


class _Host(RiskSizedMixin):
    """Bare host class for testing the mixin in isolation.

    Provides the ``config.instrument_id`` surface the mixin needs to
    resolve the contract spec (same shape as a Nautilus StrategyConfig).
    """

    def __init__(self, symbol: str = "XAUUSD") -> None:
        self.config = SimpleNamespace(
            instrument_id=SimpleNamespace(symbol=symbol)
        )


class TestRiskSizedMixin:
    """Mixin must accept any PositionSizerProtocol implementation."""

    def test_set_and_use_sizer_returns_engine_units(self) -> None:
        host = _Host()
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        host.set_position_sizer(sizer)
        result = host.size_from_risk(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
        )
        # 1% of $100k = $1000; loss/lot = 10.00 × 100 oz = $1000 → 1.0 lot.
        # XAUUSD contract_size 100 → 100 engine units (oz), NOT 1.0.
        assert result == Decimal("100.00")

    def test_size_without_sizer_raises(self) -> None:
        host = _Host()
        with pytest.raises(RuntimeError, match="sizer"):
            host.size_from_risk(
                account_balance=Decimal("100000"),
                entry_price=Decimal("2400.00"),
                stop_price=Decimal("2390.00"),
            )

    def test_swap_sizer(self) -> None:
        host = _Host()
        host.set_position_sizer(
            RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        )
        host.set_position_sizer(
            RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("2.0")))
        )
        result = host.size_from_risk(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
        )
        # Now 2% risk → 2.0 lots → 200 oz.
        assert result == Decimal("200.00")

    def test_accepts_duck_typed_sizer(self) -> None:
        """Any object with calculate_lot_size method satisfies the protocol."""

        class FakeSizer:
            def calculate_lot_size(
                self,
                *,
                account_balance: Decimal,
                entry_price: Decimal,
                stop_price: Decimal,
                contract_size: Decimal,
                quote_to_account_rate: Decimal,
            ) -> Decimal:
                return Decimal("0.42")

        host = _Host()
        host.set_position_sizer(FakeSizer())
        result = host.size_from_risk(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
        )
        # 0.42 lots × 100 oz/lot = 42 engine units.
        assert result == Decimal("42.00")

    def test_jpy_symbol_sizes_via_quote_conversion(self) -> None:
        host = _Host(symbol="USDJPY")
        host.set_position_sizer(
            RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        )
        result = host.size_from_risk(
            account_balance=Decimal("100000"),
            entry_price=Decimal("150.00"),
            stop_price=Decimal("150.60"),
        )
        # loss/lot = 0.60 JPY × 100 000 × (1/150) = $400 → 2.5 lots
        # → 250 000 engine units of USD base.
        assert result == Decimal("250000.00")

    def test_unknown_symbol_fails_loudly(self) -> None:
        host = _Host(symbol="BTCUSDT")
        host.set_position_sizer(RiskBasedPositionSizer())
        with pytest.raises(ValueError, match="No contract spec"):
            host.size_from_risk(
                account_balance=Decimal("100000"),
                entry_price=Decimal("50000"),
                stop_price=Decimal("49000"),
            )
