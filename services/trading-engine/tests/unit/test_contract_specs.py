"""Unit tests for the per-symbol contract-spec registry.

The registry is the single source of truth for lot ↔ engine-unit
conversion (redesign plan Track 1.2). The cross-check test at the
bottom pins the specs against the actual backtest instrument builders
so the two can never drift apart silently.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.instruments.contract_specs import (
    ContractSpec,
    get_contract_spec,
    known_symbols,
)


class TestRegistry:
    def test_known_symbols_cover_trading_whitelist(self) -> None:
        assert known_symbols() == (
            "AUDUSD",
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "XAUUSD",
        )

    def test_xauusd_mt5_convention(self) -> None:
        spec = get_contract_spec("XAUUSD")
        assert spec.contract_size == Decimal("100")
        assert spec.pip_size == Decimal("0.01")
        assert spec.base_currency == "XAU"
        assert spec.quote_currency == "USD"

    def test_fx_major_convention(self) -> None:
        spec = get_contract_spec("EURUSD")
        assert spec.contract_size == Decimal("100000")
        assert spec.pip_size == Decimal("0.0001")
        assert spec.base_currency == "EUR"
        assert spec.quote_currency == "USD"

    def test_jpy_pair_pip_is_two_decimals(self) -> None:
        spec = get_contract_spec("USDJPY")
        assert spec.contract_size == Decimal("100000")
        assert spec.pip_size == Decimal("0.01")
        assert spec.quote_currency == "JPY"

    def test_venue_qualified_and_lowercase_ids_accepted(self) -> None:
        assert get_contract_spec("XAUUSD.SIM").symbol == "XAUUSD"
        assert get_contract_spec("eurusd").symbol == "EURUSD"

    def test_unknown_symbol_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="No contract spec.*BTCUSDT"):
            get_contract_spec("BTCUSDT")


class TestConversions:
    def test_lots_to_units_roundtrip(self) -> None:
        spec = get_contract_spec("XAUUSD")
        assert spec.lots_to_units(Decimal("0.5")) == Decimal("50")
        assert spec.units_to_lots(Decimal("50")) == Decimal("0.5")

    def test_usd_quote_rate_is_one(self) -> None:
        spec = get_contract_spec("EURUSD")
        assert spec.quote_to_account_rate(Decimal("1.10")) == Decimal("1")

    def test_jpy_quote_rate_inverts_price(self) -> None:
        spec = get_contract_spec("USDJPY")
        rate = spec.quote_to_account_rate(Decimal("150"))
        assert rate == Decimal("1") / Decimal("150")

    def test_non_positive_price_rejected(self) -> None:
        spec = get_contract_spec("USDJPY")
        with pytest.raises(ValueError, match="price must be positive"):
            spec.quote_to_account_rate(Decimal("0"))

    def test_cross_pair_refused(self) -> None:
        cross = ContractSpec(
            symbol="EURJPY",
            contract_size=Decimal("100000"),
            pip_size=Decimal("0.01"),
            base_currency="EUR",
            quote_currency="JPY",
        )
        with pytest.raises(ValueError, match="external rate"):
            cross.quote_to_account_rate(Decimal("160"))


class TestSpecMatchesBacktestInstruments:
    """Pin specs to the runner_facade instrument builders.

    ``pip_size == 10 × price_increment`` holds for every whitelisted
    symbol under MT5 conventions; base/quote currencies must agree with
    the instrument definition. If a builder changes precision or a new
    symbol is whitelisted without a spec, this fails loudly.
    """

    @pytest.mark.parametrize(
        "symbol", ["XAUUSD", "EURUSD", "GBPUSD", "AUDUSD", "USDJPY"]
    )
    def test_spec_consistent_with_instrument(self, symbol: str) -> None:
        from src.backtesting.runner_facade import _build_instrument

        instrument, _ = _build_instrument(symbol)
        spec = get_contract_spec(symbol)

        price_increment = Decimal(str(instrument.price_increment))
        assert spec.pip_size == price_increment * 10, (
            f"{symbol}: spec pip_size {spec.pip_size} != "
            f"10 × instrument price_increment {price_increment}"
        )
        assert spec.base_currency == instrument.base_currency.code
        assert spec.quote_currency == instrument.quote_currency.code
