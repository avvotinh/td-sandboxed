"""Tests for :class:`SpreadAwareFeeModel` and the dispatch in
:func:`commission_profile_to_fee_model` (story 10.9 / D8, reworked by
redesign plan Track 1.4).

Post-Track-1.4 semantics under test:

- ``get_commission`` receives ``fill_qty`` in ENGINE UNITS and converts
  to MT5 lots via the symbol's ``ContractSpec`` (XAUUSD: 100 units/lot,
  FX majors: 100 000 units/lot) before applying per-lot costs.
- The pip value per lot is derived from the spec
  (pip_size × contract_size, quote→USD converted at the fill price),
  not supplied by the caller.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from nautilus_trader.model.currencies import EUR, USD

from src.lab.commission import commission_profile_to_fee_model
from src.lab.spread_fee_model import SpreadAwareFeeModel
from src.config.firm_profile import CommissionProfile


def _instrument(symbol: str) -> MagicMock:
    """Duck-typed Nautilus ``Instrument`` — only ``id.symbol`` is read."""
    inst = MagicMock()
    inst.id.symbol = symbol
    return inst


# -------------------------------------------------------------------------
# Constructor validation
# -------------------------------------------------------------------------


class TestConstructor:
    def test_default_construction(self) -> None:
        model = SpreadAwareFeeModel()
        assert model.per_lot_usd == 0.0
        assert model.spread_pips == {}

    def test_negative_per_lot_rejected(self) -> None:
        with pytest.raises(ValueError, match="per_lot_usd"):
            SpreadAwareFeeModel(per_lot_usd=-1.0)

    def test_negative_spread_rejected(self) -> None:
        with pytest.raises(ValueError, match="spread_pips"):
            SpreadAwareFeeModel(spread_pips={"XAUUSD": -1.0})

    def test_zero_spread_dropped(self) -> None:
        model = SpreadAwareFeeModel(
            spread_pips={"XAUUSD": 0.0, "EURUSD": 1.5}
        )
        assert "XAUUSD" not in model.spread_pips
        assert model.spread_pips == {"EURUSD": 1.5}

    def test_symbol_uppercased(self) -> None:
        model = SpreadAwareFeeModel(spread_pips={"xauusd": 5.0})
        assert "XAUUSD" in model.spread_pips
        assert "xauusd" not in model.spread_pips


# -------------------------------------------------------------------------
# get_commission — happy path (fill_qty in ENGINE UNITS)
# -------------------------------------------------------------------------


class TestGetCommission:
    def test_per_lot_only_when_no_spread(self) -> None:
        model = SpreadAwareFeeModel(per_lot_usd=7.0)
        # XAUUSD: 100 engine units (oz) = 1.0 lot → $7.
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=100.0,
            fill_px=2400.0,
            instrument=_instrument("XAUUSD"),
        )
        assert money.as_double() == pytest.approx(7.0)
        assert money.currency == USD

    def test_spread_derived_from_contract_spec_xauusd(self) -> None:
        # XAUUSD pip value = 0.01 × 100 oz = $1/pip/lot.
        # 5 pips × $1 × 1 lot (100 oz) = $5.
        model = SpreadAwareFeeModel(spread_pips={"XAUUSD": 5.0})
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=100.0,
            fill_px=2400.0,
            instrument=_instrument("XAUUSD"),
        )
        assert money.as_double() == pytest.approx(5.0)

    def test_combined_per_lot_plus_spread_eurusd(self) -> None:
        # EURUSD pip value = 0.0001 × 100 000 = $10/pip/lot.
        # ($7 + 1 pip × $10) × 2.5 lots (250 000 units) = $42.50.
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0,
            spread_pips={"EURUSD": 1.0},
        )
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=250_000.0,
            fill_px=1.10,
            instrument=_instrument("EURUSD"),
        )
        assert money.as_double() == pytest.approx(42.5)

    def test_jpy_spread_converts_at_fill_price(self) -> None:
        # USDJPY pip value = 0.01 × 100 000 = 1000 JPY/pip/lot.
        # 2 pips × 1000 JPY / 150 = $13.33/lot; 1 lot = 100 000 units.
        model = SpreadAwareFeeModel(spread_pips={"USDJPY": 2.0})
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=100_000.0,
            fill_px=150.0,
            instrument=_instrument("USDJPY"),
        )
        # Money(USD) quantises to cents, so compare at cent precision.
        assert money.as_double() == pytest.approx(2000.0 / 150.0, abs=0.005)

    def test_symbol_absent_from_spread_map_pays_only_per_lot(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0, spread_pips={"XAUUSD": 5.0}
        )
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=100_000.0,
            fill_px=1.10,
            instrument=_instrument("EURUSD"),
        )
        assert money.as_double() == pytest.approx(7.0)

    def test_partial_fill_scales_linearly(self) -> None:
        # 10 oz = 0.1 lot of (commission $10 + spread 5 × $1) = $1.50.
        model = SpreadAwareFeeModel(
            per_lot_usd=10.0, spread_pips={"XAUUSD": 5.0}
        )
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=10.0,
            fill_px=2400.0,
            instrument=_instrument("XAUUSD"),
        )
        assert money.as_double() == pytest.approx(1.5)

    def test_unregistered_symbol_fails_loudly(self) -> None:
        # No ContractSpec → charging a guessed fee would hide a
        # mis-registered instrument; the model must refuse.
        model = SpreadAwareFeeModel(per_lot_usd=7.0)
        with pytest.raises(ValueError, match="No contract spec"):
            model.get_commission(
                order=MagicMock(),
                fill_qty=1.0,
                fill_px=50_000.0,
                instrument=_instrument("BTCUSDT"),
            )


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


class TestCostPerLotFor:
    def test_returns_combined_per_lot_cost(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0,
            spread_pips={"EURUSD": 1.0},
        )
        assert model.cost_per_lot_for("EURUSD") == pytest.approx(17.0)

    def test_returns_per_lot_only_for_symbol_without_spread(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0, spread_pips={"XAUUSD": 5.0}
        )
        assert model.cost_per_lot_for("EURUSD") == pytest.approx(7.0)

    def test_jpy_requires_price(self) -> None:
        model = SpreadAwareFeeModel(spread_pips={"USDJPY": 2.0})
        with pytest.raises(ValueError, match="fill price required"):
            model.cost_per_lot_for("USDJPY")
        assert model.cost_per_lot_for("USDJPY", price=150.0) == pytest.approx(
            2000.0 / 150.0
        )


# -------------------------------------------------------------------------
# Round-trip with CommissionProfile + dispatch
# -------------------------------------------------------------------------


class TestCommissionProfileDispatch:
    def test_per_lot_only_profile_returns_lot_aware_model(self) -> None:
        # Track 1.4: the per-lot-only path also returns the lot-aware
        # SpreadAwareFeeModel — Nautilus's PerContractFeeModel would
        # charge per engine UNIT (100–100 000× too much post-sizing-fix).
        profile = CommissionProfile(per_lot_usd=7.0)
        model = commission_profile_to_fee_model(profile, USD)
        assert isinstance(model, SpreadAwareFeeModel)
        assert model.per_lot_usd == 7.0
        assert model.spread_pips == {}

    def test_non_empty_spread_returns_spread_aware_model(self) -> None:
        profile = CommissionProfile(
            per_lot_usd=7.0, spread_pips={"XAUUSD": 5.0}
        )
        model = commission_profile_to_fee_model(profile, USD)
        assert isinstance(model, SpreadAwareFeeModel)
        assert model.per_lot_usd == 7.0
        assert model.spread_pips == {"XAUUSD": 5.0}

    def test_zero_per_lot_with_spread_still_returns_model(self) -> None:
        # Per-lot is zero but spread is non-zero — must not return None
        profile = CommissionProfile(
            per_lot_usd=0.0, spread_pips={"XAUUSD": 5.0}
        )
        model = commission_profile_to_fee_model(profile, USD)
        assert isinstance(model, SpreadAwareFeeModel)

    def test_zero_per_lot_and_no_spread_returns_none(self) -> None:
        profile = CommissionProfile(per_lot_usd=0.0)
        assert commission_profile_to_fee_model(profile, USD) is None

    def test_none_profile_returns_none(self) -> None:
        assert commission_profile_to_fee_model(None, USD) is None

    def test_non_usd_currency_rejected_when_spread_present(self) -> None:
        profile = CommissionProfile(
            per_lot_usd=7.0, spread_pips={"XAUUSD": 5.0}
        )
        with pytest.raises(ValueError, match="USD"):
            commission_profile_to_fee_model(profile, EUR)

    def test_non_usd_currency_rejected_when_only_per_lot(self) -> None:
        profile = CommissionProfile(per_lot_usd=7.0)
        with pytest.raises(ValueError, match="USD"):
            commission_profile_to_fee_model(profile, EUR)


# -------------------------------------------------------------------------
# Symbol extraction
# -------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_lowercase_symbol_normalised(self) -> None:
        model = SpreadAwareFeeModel(spread_pips={"XAUUSD": 5.0})
        # Symbol returned by the duck-typed instrument is lowercase
        money = model.get_commission(
            order=MagicMock(), fill_qty=100.0, fill_px=2400.0,
            instrument=_instrument("xauusd"),
        )
        assert money.as_double() == pytest.approx(5.0)

    def test_missing_symbol_id_fails_loudly(self) -> None:
        # Instrument with no id attribute → empty symbol → no contract
        # spec. Pre-1.4 this silently charged per-lot; now it refuses.
        model = SpreadAwareFeeModel(per_lot_usd=7.0)
        bare_instrument = MagicMock(spec=[])
        with pytest.raises(ValueError, match="No contract spec"):
            model.get_commission(
                order=MagicMock(), fill_qty=100.0, fill_px=2400.0,
                instrument=bare_instrument,
            )
