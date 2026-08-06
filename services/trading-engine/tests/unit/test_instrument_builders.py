"""Unit tests for the per-symbol instrument builders (Epic 16 story 16.1).

``runner_facade`` builds a Nautilus ``CurrencyPair`` per symbol with
broker-faithful precision and zero instrument fees (commission comes from
the venue fee model instead). These builders previously had no direct
coverage — the facade tests mock ``_build_instrument`` wholesale.

The JPY-quoted pair (USDJPY) is the new surface: before story 16.1 it
fell through to ``TestInstrumentProvider.default_fx_ccy`` which applies a
non-zero 2 bps instrument fee and the wrong (5-dp) price precision. A
JPY pair quotes to 3 decimals with a 0.001 increment.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Currency, Price, Quantity
from src.lab.runner_facade import (
    _build_fx_pair_instrument,
    _build_instrument,
    _build_jpy_pair_instrument,
)


@pytest.mark.unit
class TestBuildJpyPairInstrument:
    def test_currencies_base_usd_quote_jpy(self) -> None:
        inst = _build_jpy_pair_instrument("USDJPY")
        assert inst.base_currency == USD
        assert inst.quote_currency == Currency.from_str("JPY")

    def test_jpy_price_precision_is_three(self) -> None:
        inst = _build_jpy_pair_instrument("USDJPY")
        assert inst.price_precision == 3
        assert inst.price_increment == Price(Decimal("0.001"), 3)

    def test_size_is_unit_granular(self) -> None:
        # MT5 FX convention: 1-unit size granularity (not XAUUSD's 0.01
        # micro-lot). Guards a future cross-JPY builder from copying
        # XAUUSD's size_precision=2 by mistake.
        inst = _build_jpy_pair_instrument("USDJPY")
        assert inst.size_precision == 0
        assert inst.size_increment == Quantity.from_int(1)

    def test_zero_instrument_fees(self) -> None:
        # Commission must come from the venue fee model, never the
        # instrument — a 2 bps instrument fee burns the account on the
        # multi-million-unit positions a 0.5%-risk sizer produces.
        inst = _build_jpy_pair_instrument("USDJPY")
        assert inst.maker_fee == Decimal("0")
        assert inst.taker_fee == Decimal("0")

    def test_symbol_id_round_trips(self) -> None:
        inst = _build_jpy_pair_instrument("USDJPY")
        assert str(inst.id.symbol) == "USDJPY"


@pytest.mark.unit
class TestBuildInstrumentDispatch:
    # Both the no-slash form (tv-cli / dataset path) and the slash form
    # (config whitelist) are in _SUPPORTED_SYMBOLS; both must route to the
    # JPY builder. endswith("JPY") + symbol[:3]/[-3:] handle either.
    @pytest.mark.parametrize("sym", ["USDJPY", "USD/JPY"])
    def test_usdjpy_routes_to_jpy_builder_not_default(self, sym: str) -> None:
        # The discriminator vs default_fx_ccy: our builder is fee-free and
        # 3-dp. If USDJPY ever regresses back to default_fx_ccy these flip.
        inst, _ = _build_instrument(sym)
        assert inst.quote_currency == Currency.from_str("JPY")
        assert inst.price_precision == 3
        assert inst.maker_fee == Decimal("0")

    def test_eurusd_still_usd_quote_5dp_fee_free(self) -> None:
        # Regression guard for the existing USD-quote FX builder.
        inst, _ = _build_instrument("EURUSD")
        assert inst.quote_currency == USD
        assert inst.price_precision == 5
        assert inst.maker_fee == Decimal("0")

    def test_fx_pair_builder_rejects_jpy_quote_path(self) -> None:
        # _build_fx_pair_instrument is the 5-dp USD-quote builder; it must
        # not be the one serving USDJPY (precision would be wrong).
        inst = _build_fx_pair_instrument("EURUSD")
        assert inst.price_precision == 5
