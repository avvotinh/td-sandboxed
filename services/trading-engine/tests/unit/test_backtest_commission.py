"""Unit tests for per-firm backtest commission wiring (Epic 9 P0.13).

Three layers under test:

1. ``resolve_commission_profile`` — picks product override over firm default.
2. ``commission_profile_to_fee_model`` — converts the dataclass into a
   Nautilus :class:`PerContractFeeModel`, returns ``None`` for the
   zero-fee path.
3. ``run_backtest`` — passes ``fee_model`` to ``add_venue`` only when
   ``VenueSpec.commission_per_lot_usd`` > 0, preserving prior behaviour
   for legacy callers.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nautilus_trader.backtest.models import PerContractFeeModel
from nautilus_trader.model.currencies import EUR, USD

from src.backtesting.commission import (
    commission_per_lot_to_fee_model,
    commission_profile_to_fee_model,
    resolve_commission_profile,
)
from src.backtesting.job_config import (
    BacktestJobConfig,
    SyntheticDataSpec,
    VenueSpec,
)
from src.config.firm_profile import (
    AccountPhase,
    AccountProduct,
    CommissionProfile,
    DrawdownMethod,
    FirmProfile,
    SessionConfig,
)
from src.config.firm_registry import FirmRegistry
from src.rules.types.drawdown import DailyLossLimitRule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_phase() -> AccountPhase:
    return AccountPhase(phase_id="funded", name="Funded")


def _make_product(
    *,
    product_id: str = "default",
    commission_overrides: CommissionProfile | None = None,
) -> AccountProduct:
    return AccountProduct(
        product_id=product_id,
        name=product_id.title(),
        rules=(DailyLossLimitRule(threshold_percent=5.0),),
        phases=(_make_phase(),),
        drawdown_method=DrawdownMethod.BALANCE_BASED,
        commission_overrides=commission_overrides,
    )


def _make_firm(
    *,
    firm_commission: CommissionProfile | None = None,
    product: AccountProduct | None = None,
) -> FirmProfile:
    prod = product or _make_product()
    return FirmProfile(
        firm_id="testfirm",
        name="Test Firm",
        version="1.0",
        session=SessionConfig(timezone="UTC", reset_time="00:00"),
        products={prod.product_id: prod},
        commission=firm_commission,
    )


# ---------------------------------------------------------------------------
# resolve_commission_profile
# ---------------------------------------------------------------------------


class TestResolveCommissionProfile:
    def test_returns_firm_level_when_no_product_override(self) -> None:
        firm_comm = CommissionProfile(per_lot_usd=7.0)
        firm = _make_firm(firm_commission=firm_comm)
        assert resolve_commission_profile(firm, "default") is firm_comm

    def test_product_override_wins_over_firm_level(self) -> None:
        firm_comm = CommissionProfile(per_lot_usd=7.0)
        product_comm = CommissionProfile(per_lot_usd=3.5)
        product = _make_product(commission_overrides=product_comm)
        firm = _make_firm(firm_commission=firm_comm, product=product)
        assert resolve_commission_profile(firm, "default") is product_comm

    def test_returns_none_when_neither_set(self) -> None:
        firm = _make_firm()  # both None
        assert resolve_commission_profile(firm, "default") is None

    def test_unknown_product_raises_keyerror(self) -> None:
        firm = _make_firm()
        with pytest.raises(KeyError):
            resolve_commission_profile(firm, "missing")


# ---------------------------------------------------------------------------
# commission_profile_to_fee_model
# ---------------------------------------------------------------------------


class TestCommissionProfileToFeeModel:
    def test_none_profile_returns_none(self) -> None:
        assert commission_profile_to_fee_model(None, USD) is None

    def test_zero_per_lot_returns_none(self) -> None:
        profile = CommissionProfile(per_lot_usd=0.0)
        assert commission_profile_to_fee_model(profile, USD) is None

    def test_positive_per_lot_returns_per_contract_fee_model(self) -> None:
        profile = CommissionProfile(per_lot_usd=5.0)
        fee = commission_profile_to_fee_model(profile, USD)
        assert isinstance(fee, PerContractFeeModel)

    def test_non_usd_currency_rejected(self) -> None:
        profile = CommissionProfile(per_lot_usd=5.0)
        with pytest.raises(ValueError, match="USD-denominated"):
            commission_profile_to_fee_model(profile, EUR)


# ---------------------------------------------------------------------------
# commission_per_lot_to_fee_model
# ---------------------------------------------------------------------------


class TestCommissionPerLotToFeeModel:
    def test_zero_returns_none(self) -> None:
        assert commission_per_lot_to_fee_model(0, USD) is None
        assert commission_per_lot_to_fee_model(Decimal("0"), USD) is None

    def test_positive_returns_per_contract_fee_model(self) -> None:
        fee = commission_per_lot_to_fee_model(Decimal("4.5"), USD)
        assert isinstance(fee, PerContractFeeModel)

    def test_negative_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must be >= 0"):
            commission_per_lot_to_fee_model(Decimal("-1"), USD)

    def test_non_usd_currency_rejected(self) -> None:
        with pytest.raises(ValueError, match="USD-denominated"):
            commission_per_lot_to_fee_model(Decimal("5"), EUR)


# ---------------------------------------------------------------------------
# VenueSpec carries commission and run_backtest threads it to add_venue
# ---------------------------------------------------------------------------


class TestVenueSpecCommissionField:
    def test_default_is_zero(self) -> None:
        spec = VenueSpec(starting_balance=Decimal("100000"))
        assert spec.commission_per_lot_usd == Decimal("0")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            VenueSpec(
                starting_balance=Decimal("100000"),
                commission_per_lot_usd=Decimal("-1"),
            )

    def test_carries_explicit_value(self) -> None:
        spec = VenueSpec(
            starting_balance=Decimal("100000"),
            commission_per_lot_usd=Decimal("7"),
        )
        assert spec.commission_per_lot_usd == Decimal("7")


def _job_with_commission(value: Decimal) -> BacktestJobConfig:
    return BacktestJobConfig(
        strategy="ma_crossover",
        strategy_params={
            "fast_period": 5,
            "slow_period": 20,
            "trade_size": "10000",
        },
        venue=VenueSpec(
            starting_balance=Decimal("100000"),
            commission_per_lot_usd=value,
        ),
        instrument_symbol="EUR/USD",
        bar_type_suffix="1-MINUTE-BID-EXTERNAL",
        data=SyntheticDataSpec(
            pattern="trending", count=100, start_price=1.10, seed=7
        ),
    )


class TestRunnerFacadeWiresFeeModel:
    """run_backtest must pass fee_model to add_venue iff commission > 0."""

    def _patch_runner_and_run(self, job: BacktestJobConfig) -> MagicMock:
        from src.backtesting import runner_facade
        from src.backtesting.result import BacktestResult

        with (
            patch.object(runner_facade, "BacktestRunner") as runner_cls,
            patch.object(runner_facade, "_build_instrument") as build_instr,
            patch.object(runner_facade, "_build_bars") as build_bars,
            patch.object(
                runner_facade,
                "_read_final_balance",
                return_value=Decimal("100000"),
            ),
        ):
            mock_runner = MagicMock()
            mock_runner.get_result.return_value = BacktestResult(
                strategy_name="ma_crossover",
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 2),
                initial_balance=Decimal("100000"),
                final_balance=Decimal("100000"),
            )
            runner_cls.return_value = mock_runner
            build_instr.return_value = (MagicMock(id=MagicMock()), "EUR/USD.SIM")
            build_bars.return_value = [MagicMock(), MagicMock()]

            runner_facade.run_backtest(job)
            return mock_runner

    def test_zero_commission_passes_fee_model_none(self) -> None:
        runner = self._patch_runner_and_run(_job_with_commission(Decimal("0")))
        add_venue_calls = [c for c in runner.method_calls if c[0] == "add_venue"]
        assert len(add_venue_calls) == 1
        # Nautilus accepts fee_model=None (default no-fee path).
        assert add_venue_calls[0][2]["fee_model"] is None

    def test_positive_commission_passes_per_contract_fee_model(self) -> None:
        runner = self._patch_runner_and_run(_job_with_commission(Decimal("7")))
        add_venue_calls = [c for c in runner.method_calls if c[0] == "add_venue"]
        assert len(add_venue_calls) == 1
        assert isinstance(add_venue_calls[0][2]["fee_model"], PerContractFeeModel)


# ---------------------------------------------------------------------------
# Real YAML — protects configs/firms/ftmo.yaml against silent drift
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def firms_dir(pytestconfig: pytest.Config) -> Path:
    d = pytestconfig.rootpath.parents[1] / "configs" / "firms"
    assert d.is_dir(), f"firms dir missing: {d}"
    return d


class TestRealFtmoYamlCommission:
    """Loads ``configs/firms/ftmo.yaml`` end-to-end — value parity guard."""

    def test_ftmo_resolves_to_per_contract_fee_of_7_usd(
        self, firms_dir: Path
    ) -> None:
        registry = FirmRegistry(firms_dir)
        registry.load()
        ftmo = registry.get("ftmo")

        profile = resolve_commission_profile(ftmo, "challenge")
        assert profile is not None
        assert profile.per_lot_usd == 7.0

        fee = commission_profile_to_fee_model(profile, USD)
        assert isinstance(fee, PerContractFeeModel)
