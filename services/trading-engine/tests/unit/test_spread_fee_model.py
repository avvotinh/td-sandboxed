"""Tests for :class:`SpreadAwareFeeModel` and the dispatch in
:func:`commission_profile_to_fee_model` (story 10.9 / D8)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from nautilus_trader.backtest.models import PerContractFeeModel
from nautilus_trader.model.currencies import EUR, USD

from src.backtesting.commission import commission_profile_to_fee_model
from src.backtesting.spread_fee_model import (
    DEFAULT_PIP_VALUE_PER_LOT_USD,
    SpreadAwareFeeModel,
)
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

    def test_zero_pip_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="pip_value"):
            SpreadAwareFeeModel(
                spread_pips={"XAUUSD": 1.0}, pip_value_per_lot_usd=0
            )

    def test_negative_pip_value_in_mapping_rejected(self) -> None:
        with pytest.raises(ValueError, match="pip_value"):
            SpreadAwareFeeModel(
                spread_pips={"XAUUSD": 1.0},
                pip_value_per_lot_usd={"XAUUSD": -10.0},
            )


# -------------------------------------------------------------------------
# get_commission — happy path
# -------------------------------------------------------------------------


class TestGetCommission:
    def test_per_lot_only_when_no_spread(self) -> None:
        model = SpreadAwareFeeModel(per_lot_usd=7.0)
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=1.0,
            fill_px=MagicMock(),
            instrument=_instrument("XAUUSD"),
        )
        assert money.as_double() == pytest.approx(7.0)
        assert money.currency == USD

    def test_spread_only_when_no_per_lot(self) -> None:
        # XAUUSD: 5 pips × 10 USD/pip × 1 lot = $50
        model = SpreadAwareFeeModel(
            spread_pips={"XAUUSD": 5.0}, pip_value_per_lot_usd=10.0
        )
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=1.0,
            fill_px=MagicMock(),
            instrument=_instrument("XAUUSD"),
        )
        assert money.as_double() == pytest.approx(50.0)

    def test_combined_per_lot_plus_spread(self) -> None:
        # commission $7/lot + spread 1 pip × $10/pip = $17/lot
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0,
            spread_pips={"EURUSD": 1.0},
            pip_value_per_lot_usd=10.0,
        )
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=2.5,
            fill_px=MagicMock(),
            instrument=_instrument("EURUSD"),
        )
        # 17 × 2.5 lots
        assert money.as_double() == pytest.approx(42.5)

    def test_unknown_symbol_pays_only_per_lot(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0, spread_pips={"XAUUSD": 5.0}
        )
        money = model.get_commission(
            order=MagicMock(),
            fill_qty=1.0,
            fill_px=MagicMock(),
            instrument=_instrument("EURUSD"),
        )
        assert money.as_double() == pytest.approx(7.0)

    def test_per_symbol_pip_value_mapping(self) -> None:
        # XAUUSD: $1/pip/lot (metals); EURUSD: $10/pip/lot (forex major)
        model = SpreadAwareFeeModel(
            spread_pips={"XAUUSD": 30.0, "EURUSD": 1.0},
            pip_value_per_lot_usd={"XAUUSD": 1.0, "EURUSD": 10.0},
        )
        # XAUUSD: 30 × 1 = $30/lot
        gold = model.get_commission(
            order=MagicMock(), fill_qty=1.0, fill_px=MagicMock(),
            instrument=_instrument("XAUUSD"),
        )
        assert gold.as_double() == pytest.approx(30.0)
        # EURUSD: 1 × 10 = $10/lot
        forex = model.get_commission(
            order=MagicMock(), fill_qty=1.0, fill_px=MagicMock(),
            instrument=_instrument("EURUSD"),
        )
        assert forex.as_double() == pytest.approx(10.0)

    def test_per_symbol_pip_value_falls_back_to_default_for_unmapped(
        self,
    ) -> None:
        model = SpreadAwareFeeModel(
            spread_pips={"GBPUSD": 1.5, "EURUSD": 1.0},
            pip_value_per_lot_usd={"EURUSD": 10.0},  # GBPUSD not in mapping
        )
        # GBPUSD falls through to DEFAULT_PIP_VALUE_PER_LOT_USD = 10.0
        # 1.5 × 10 = $15/lot
        money = model.get_commission(
            order=MagicMock(), fill_qty=1.0, fill_px=MagicMock(),
            instrument=_instrument("GBPUSD"),
        )
        assert money.as_double() == pytest.approx(1.5 * DEFAULT_PIP_VALUE_PER_LOT_USD)

    def test_partial_fill_scales_linearly(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=10.0, spread_pips={"XAUUSD": 5.0},
            pip_value_per_lot_usd=10.0,
        )
        # 0.1 lot of (commission $10 + spread $50) = $6.0
        money = model.get_commission(
            order=MagicMock(), fill_qty=0.1, fill_px=MagicMock(),
            instrument=_instrument("XAUUSD"),
        )
        assert money.as_double() == pytest.approx(6.0)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


class TestCostPerLotFor:
    def test_returns_combined_per_lot_cost(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0,
            spread_pips={"EURUSD": 1.0},
            pip_value_per_lot_usd=10.0,
        )
        assert model.cost_per_lot_for("EURUSD") == pytest.approx(17.0)

    def test_returns_per_lot_only_for_unknown_symbol(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0, spread_pips={"XAUUSD": 5.0}
        )
        assert model.cost_per_lot_for("EURUSD") == pytest.approx(7.0)


# -------------------------------------------------------------------------
# Round-trip with CommissionProfile + dispatch
# -------------------------------------------------------------------------


class TestCommissionProfileDispatch:
    def test_empty_spread_returns_per_contract_fee_model(self) -> None:
        profile = CommissionProfile(per_lot_usd=7.0)
        model = commission_profile_to_fee_model(profile, USD)
        assert isinstance(model, PerContractFeeModel)

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

    def test_pip_value_override_propagates(self) -> None:
        profile = CommissionProfile(
            per_lot_usd=0.0, spread_pips={"XAUUSD": 5.0}
        )
        model = commission_profile_to_fee_model(
            profile, USD, pip_value_per_lot_usd=1.0
        )
        assert isinstance(model, SpreadAwareFeeModel)
        # 5 pips × 1 USD/pip = $5/lot
        assert model.cost_per_lot_for("XAUUSD") == pytest.approx(5.0)


# -------------------------------------------------------------------------
# Symbol extraction
# -------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_lowercase_symbol_normalised(self) -> None:
        model = SpreadAwareFeeModel(
            spread_pips={"XAUUSD": 5.0}, pip_value_per_lot_usd=10.0
        )
        # Symbol returned by the duck-typed instrument is lowercase
        money = model.get_commission(
            order=MagicMock(), fill_qty=1.0, fill_px=MagicMock(),
            instrument=_instrument("xauusd"),
        )
        assert money.as_double() == pytest.approx(50.0)

    def test_missing_symbol_id_pays_only_per_lot(self) -> None:
        model = SpreadAwareFeeModel(
            per_lot_usd=7.0, spread_pips={"XAUUSD": 5.0}
        )
        # Instrument with no id attribute
        bare_instrument = MagicMock(spec=[])
        money = model.get_commission(
            order=MagicMock(), fill_qty=1.0, fill_px=MagicMock(),
            instrument=bare_instrument,
        )
        assert money.as_double() == pytest.approx(7.0)
