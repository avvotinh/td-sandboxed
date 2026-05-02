"""Integration test: load shipped firm YAMLs from configs/firms/ (Epic 9 P0.11).

These tests load the actual YAML files committed under ``configs/firms/`` (not
inline fixtures) so any drift between the schema and the operator-facing
configs is caught on every CI run. Pure unit tests for the loader live in
``tests/unit/test_firm_registry.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.firm_profile import DrawdownMethod, InstrumentClass, ResetAnchor
from src.config.firm_registry import FirmRegistry


@pytest.fixture(scope="module")
def firms_dir(pytestconfig: pytest.Config) -> Path:
    # pytest rootdir is services/trading-engine; the repo root (and configs/)
    # sits two directories above. Anchoring on rootpath beats counting
    # __file__.parents — moving the test file deeper does not break it.
    d = pytestconfig.rootpath.parents[1] / "configs" / "firms"
    assert d.is_dir(), f"firms dir missing: {d}"
    return d


@pytest.fixture(scope="module")
def registry(firms_dir: Path) -> FirmRegistry:
    r = FirmRegistry(firms_dir)
    r.load()
    return r


class TestShippedFirmYamls:
    """Smoke tests over every YAML in configs/firms/."""

    def test_registry_loads_both_firms(self, registry: FirmRegistry) -> None:
        assert registry.list_firms() == ["ftmo", "the5ers"]

    def test_every_firm_uses_forex_cfd_class(self, registry: FirmRegistry) -> None:
        for firm_id in registry.list_firms():
            firm = registry.get(firm_id)
            assert firm.instrument_class is InstrumentClass.FOREX_CFD

    def test_max_drawdown_rule_method_matches_product_drawdown_method(
        self, registry: FirmRegistry
    ) -> None:
        # Catches drift between the product-level `drawdown_method` (used by
        # the snapshot service to pick the right Redis key) and the inline
        # `method` field on each `max_drawdown` rule (used by the rule's own
        # threshold check). Diverging values would silently disagree.
        for firm_id in registry.list_firms():
            firm = registry.get(firm_id)
            for product in firm.products.values():
                max_dd = next(
                    (r for r in product.rules if r.rule_type == "max_drawdown"),
                    None,
                )
                if max_dd is None:
                    continue
                assert max_dd.method == product.drawdown_method.value, (
                    f"{firm_id}/{product.product_id}: max_drawdown.method"
                    f"={max_dd.method!r} != product.drawdown_method"
                    f"={product.drawdown_method.value!r}"
                )


class TestFtmoProfile:
    """FTMO must keep parity with the legacy preset thresholds."""

    def test_session_is_cet_midnight(self, registry: FirmRegistry) -> None:
        firm = registry.get("ftmo")
        assert firm.session.timezone == "CET"
        assert firm.session.reset_time == "00:00"
        assert firm.session.reset_anchor is ResetAnchor.MIDNIGHT

    def test_single_challenge_product_with_three_phases(
        self, registry: FirmRegistry
    ) -> None:
        firm = registry.get("ftmo")
        assert list(firm.products) == ["challenge"]
        challenge = firm.get_product("challenge")
        assert [p.phase_id for p in challenge.phases] == [
            "evaluation",
            "verification",
            "funded",
        ]

    def test_phase_lifecycle_transitions(self, registry: FirmRegistry) -> None:
        challenge = registry.get("ftmo").get_product("challenge")
        evaluation = challenge.get_phase("evaluation")
        verification = challenge.get_phase("verification")
        funded = challenge.get_phase("funded")
        assert evaluation.allowed_transitions == ("verification",)
        assert verification.allowed_transitions == ("funded",)
        assert funded.allowed_transitions == ()  # terminal

    def test_drawdown_method_balance_based(self, registry: FirmRegistry) -> None:
        challenge = registry.get("ftmo").get_product("challenge")
        assert challenge.drawdown_method is DrawdownMethod.BALANCE_BASED

    def test_baseline_rule_set_matches_legacy_preset(
        self, registry: FirmRegistry
    ) -> None:
        challenge = registry.get("ftmo").get_product("challenge")
        rule_types = [r.rule_type for r in challenge.rules]
        # Five legacy rules + consistency added in P0.7.
        assert set(rule_types) == {
            "daily_loss_limit",
            "max_drawdown",
            "max_position_size",
            "profit_target",
            "min_trading_days",
            "consistency",
        }

    def test_daily_loss_threshold_is_5_percent(
        self, registry: FirmRegistry
    ) -> None:
        challenge = registry.get("ftmo").get_product("challenge")
        daily_loss = next(
            r for r in challenge.rules if r.rule_type == "daily_loss_limit"
        )
        assert daily_loss.threshold_percent == pytest.approx(5.0)

    def test_max_drawdown_threshold_is_10_percent(
        self, registry: FirmRegistry
    ) -> None:
        challenge = registry.get("ftmo").get_product("challenge")
        max_dd = next(r for r in challenge.rules if r.rule_type == "max_drawdown")
        assert max_dd.threshold_percent == pytest.approx(10.0)

    def test_evaluation_overrides_profit_target_to_10(
        self, registry: FirmRegistry
    ) -> None:
        evaluation = (
            registry.get("ftmo").get_product("challenge").get_phase("evaluation")
        )
        assert evaluation.rule_overrides == {
            "profit_target": {"threshold_percent": 10.0},
        }

    def test_verification_overrides_profit_target_to_5(
        self, registry: FirmRegistry
    ) -> None:
        verification = (
            registry.get("ftmo").get_product("challenge").get_phase("verification")
        )
        assert verification.rule_overrides == {
            "profit_target": {"threshold_percent": 5.0},
        }

    def test_commission_per_lot_set(self, registry: FirmRegistry) -> None:
        firm = registry.get("ftmo")
        assert firm.commission is not None
        assert firm.commission.per_lot_usd > 0

    def test_consistency_thresholds(self, registry: FirmRegistry) -> None:
        challenge = registry.get("ftmo").get_product("challenge")
        consistency = next(r for r in challenge.rules if r.rule_type == "consistency")
        assert consistency.block_at == pytest.approx(50.0)
        assert tuple(consistency.warn_at) == (40.0, 45.0, 48.0)

    def test_regime_classifier_block_present_and_disabled(
        self, registry: FirmRegistry
    ) -> None:
        # Story 11.2: ship the block disabled so production behavior is
        # unchanged until an operator flips `enabled: true`.
        rc = registry.get("ftmo").regime_classifier
        assert rc is not None
        assert rc.enabled is False
        xau = rc.get_instrument("XAUUSD")
        assert xau.timeframe == "M5"
        assert xau.thresholds.adx_trend_min == pytest.approx(25.0)
        assert xau.thresholds.bb_width_high_pct == pytest.approx(0.80)
        assert xau.bb_baseline_window >= xau.bb_period


class TestThe5ersRegimeClassifier:
    """The5ers does not enable the regime block in Phase 1."""

    def test_regime_classifier_absent(self, registry: FirmRegistry) -> None:
        # Phase 1 ships FTMO-only; the5ers stays on the legacy bar pipeline
        # until volatility-targeted strategies clear validation.
        assert registry.get("the5ers").regime_classifier is None


class TestThe5ersProfile:
    """The5ers must declare three distinct products with the expected rules."""

    def test_session_is_utc(self, registry: FirmRegistry) -> None:
        firm = registry.get("the5ers")
        assert firm.session.timezone == "UTC"
        assert firm.session.reset_time == "00:00"

    def test_three_products(self, registry: FirmRegistry) -> None:
        firm = registry.get("the5ers")
        assert sorted(firm.products) == ["bootstrap", "high_stakes", "hyper_growth"]

    def test_bootstrap_uses_balance_based_dd_and_weekly_target(
        self, registry: FirmRegistry
    ) -> None:
        bootstrap = registry.get("the5ers").get_product("bootstrap")
        assert bootstrap.drawdown_method is DrawdownMethod.BALANCE_BASED
        rule_types = {r.rule_type for r in bootstrap.rules}
        assert "weekly_target" in rule_types
        assert "consistency" not in rule_types

        weekly = next(r for r in bootstrap.rules if r.rule_type == "weekly_target")
        assert weekly.threshold_percent == pytest.approx(1.25)

    def test_high_stakes_uses_equity_peak_dd_and_consistency(
        self, registry: FirmRegistry
    ) -> None:
        high_stakes = registry.get("the5ers").get_product("high_stakes")
        assert high_stakes.drawdown_method is DrawdownMethod.EQUITY_PEAK
        rule_types = {r.rule_type for r in high_stakes.rules}
        assert "consistency" in rule_types
        assert "weekly_target" not in rule_types

    def test_hyper_growth_carries_scaling_policy(
        self, registry: FirmRegistry
    ) -> None:
        hyper = registry.get("the5ers").get_product("hyper_growth")
        assert hyper.scaling_policy is not None
        assert hyper.scaling_policy.policy_id == "the5ers_hyper_growth"
        # Engine treats params as opaque; just verify they round-trip.
        assert hyper.scaling_policy.params  # non-empty dict

    def test_three_products_have_distinct_rule_sets(
        self, registry: FirmRegistry
    ) -> None:
        firm = registry.get("the5ers")
        rule_signatures = {
            pid: tuple(sorted(r.rule_type for r in p.rules))
            for pid, p in firm.products.items()
        }
        assert len({rule_signatures[pid] for pid in rule_signatures}) == 3

    def test_bootstrap_thresholds(self, registry: FirmRegistry) -> None:
        bootstrap = registry.get("the5ers").get_product("bootstrap")
        daily_loss = next(
            r for r in bootstrap.rules if r.rule_type == "daily_loss_limit"
        )
        max_dd = next(r for r in bootstrap.rules if r.rule_type == "max_drawdown")
        assert daily_loss.threshold_percent == pytest.approx(5.0)
        assert max_dd.threshold_percent == pytest.approx(4.0)

    def test_high_stakes_thresholds(self, registry: FirmRegistry) -> None:
        hs = registry.get("the5ers").get_product("high_stakes")
        max_dd = next(r for r in hs.rules if r.rule_type == "max_drawdown")
        consistency = next(r for r in hs.rules if r.rule_type == "consistency")
        assert max_dd.threshold_percent == pytest.approx(4.0)
        assert consistency.block_at == pytest.approx(50.0)

    def test_hyper_growth_thresholds(self, registry: FirmRegistry) -> None:
        hyper = registry.get("the5ers").get_product("hyper_growth")
        daily_loss = next(
            r for r in hyper.rules if r.rule_type == "daily_loss_limit"
        )
        max_dd = next(r for r in hyper.rules if r.rule_type == "max_drawdown")
        assert daily_loss.threshold_percent == pytest.approx(5.0)
        assert max_dd.threshold_percent == pytest.approx(5.0)


class TestResolveTuples:
    """End-to-end resolve() lookups for representative (firm, product, phase)."""

    @pytest.mark.parametrize(
        "firm_id,product_id,phase_id",
        [
            ("ftmo", "challenge", "evaluation"),
            ("ftmo", "challenge", "verification"),
            ("ftmo", "challenge", "funded"),
            ("the5ers", "bootstrap", "funded"),
            ("the5ers", "high_stakes", "evaluation"),
            ("the5ers", "high_stakes", "funded"),
            ("the5ers", "hyper_growth", "funded"),
        ],
    )
    def test_resolve_succeeds(
        self,
        registry: FirmRegistry,
        firm_id: str,
        product_id: str,
        phase_id: str,
    ) -> None:
        firm, product, phase = registry.resolve(firm_id, product_id, phase_id)
        assert firm.firm_id == firm_id
        assert product.product_id == product_id
        assert phase.phase_id == phase_id
