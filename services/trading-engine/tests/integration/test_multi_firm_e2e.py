"""End-to-end test: FTMO + The5ers (3 products) running through one engine
(Epic 9 P0.14).

The whole point of the multi-firm refactor is that the engine core stops
being FTMO-specific. This test exercises the full path that was redesigned
across P0.1–P0.13:

    configs/firms/*.yaml
        ↓ FirmRegistry.load()                                (P0.2)
    FirmProfile / AccountProduct / AccountPhase               (P0.1)
        ↓ AccountConfig firm-bound (firm_id+product_id+phase) (P0.3, P0.4)
    RuleAssignmentService.get_rules_for_account(account)
        ↓ resolves rules per product                          (P0.7, P0.8)
    RuleEngine — one per account, isolated state              (Epic 4)

If any of the layers regress, this test trips. It's a single integration
test that proves the abstractions actually compose.

Coverage:

* Both firm YAMLs from ``configs/firms/`` are loaded.
* 4 firm-bound accounts (FTMO challenge, The5ers bootstrap / high_stakes /
  hyper_growth) each resolve to a distinct rule set.
* The signature rule for each product is present (consistency on FTMO and
  High Stakes; weekly_target on Bootstrap; no consistency on Bootstrap or
  Hyper Growth).
* Drawdown method differs by product (balance_based vs equity_peak).
* RuleEngine isolation: a loss that BLOCKS one account does not propagate
  to the others; threshold differences (FTMO 10% vs Bootstrap 4%) produce
  different verdicts on the same loss size.
* FTMO Challenge phase lifecycle (evaluation → verification → funded) is
  a linear chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.accounts.models import AccountConfig, AccountType, MT5Config
from src.config.firm_profile import DrawdownMethod
from src.config.firm_registry import FirmRegistry
from src.rules.assignment_service import RuleAssignmentService
from src.rules.base_rule import RuleAction
from src.rules.engine import RuleEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def firms_dir(pytestconfig: pytest.Config) -> Path:
    d = pytestconfig.rootpath.parents[1] / "configs" / "firms"
    assert d.is_dir(), f"firms dir missing: {d}"
    return d


@pytest.fixture(scope="module")
def firm_registry(firms_dir: Path) -> FirmRegistry:
    registry = FirmRegistry(firms_dir)
    registry.load()
    return registry


@pytest.fixture(scope="module")
def assignment_service(firm_registry: FirmRegistry) -> RuleAssignmentService:
    return RuleAssignmentService(firm_registry=firm_registry)


def _mt5() -> MT5Config:
    return MT5Config(server="Test", login=1, password_env="TEST_PASS")


def _firm_account(
    *,
    account_id: str,
    firm_id: str,
    product_id: str,
    phase: str,
) -> AccountConfig:
    return AccountConfig(
        id=account_id,
        name=f"E2E {account_id}",
        type=AccountType.PROP_FIRM,
        firm_id=firm_id,
        product_id=product_id,
        phase=phase,
        mt5=_mt5(),
        strategy="ma_crossover",
    )


@pytest.fixture(scope="module")
def accounts() -> dict[str, AccountConfig]:
    return {
        "ftmo": _firm_account(
            account_id="ftmo-e2e",
            firm_id="ftmo",
            product_id="challenge",
            phase="evaluation",
        ),
        "bootstrap": _firm_account(
            account_id="t5-bootstrap-e2e",
            firm_id="the5ers",
            product_id="bootstrap",
            phase="funded",
        ),
        "high_stakes": _firm_account(
            account_id="t5-hs-e2e",
            firm_id="the5ers",
            product_id="high_stakes",
            phase="evaluation",
        ),
        "hyper_growth": _firm_account(
            account_id="t5-hg-e2e",
            firm_id="the5ers",
            product_id="hyper_growth",
            phase="funded",
        ),
    }


@pytest.fixture(scope="module")
def engines(
    assignment_service: RuleAssignmentService,
    accounts: dict[str, AccountConfig],
) -> dict[str, RuleEngine]:
    """One RuleEngine per account, all sharing the same registry/service."""
    return {
        key: RuleEngine(
            account_id=acct.id,
            rules=assignment_service.get_rules_for_account(acct),
        )
        for key, acct in accounts.items()
    }


# ---------------------------------------------------------------------------
# Wiring + rule sets
# ---------------------------------------------------------------------------


class TestRegistryAndAccountsLoad:
    def test_registry_lists_both_firms(self, firm_registry: FirmRegistry) -> None:
        assert firm_registry.list_firms() == ["ftmo", "the5ers"]

    def test_every_account_resolves_through_registry(
        self,
        firm_registry: FirmRegistry,
        accounts: dict[str, AccountConfig],
    ) -> None:
        for acct in accounts.values():
            firm_registry.resolve(acct.firm_id, acct.product_id, acct.phase)


class TestEachProductHasItsSignatureRule:
    """Each product must declare the rule that distinguishes it from the rest."""

    def test_ftmo_challenge_has_consistency(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        rule_types = {r.rule_type for r in engines["ftmo"]._rules}
        assert "consistency" in rule_types
        assert "weekly_target" not in rule_types

    def test_bootstrap_has_weekly_target_no_consistency(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        rule_types = {r.rule_type for r in engines["bootstrap"]._rules}
        assert "weekly_target" in rule_types
        assert "consistency" not in rule_types

    def test_high_stakes_has_consistency_no_weekly_target(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        rule_types = {r.rule_type for r in engines["high_stakes"]._rules}
        assert "consistency" in rule_types
        assert "weekly_target" not in rule_types

    def test_hyper_growth_has_neither_consistency_nor_weekly_target(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        rule_types = {r.rule_type for r in engines["hyper_growth"]._rules}
        assert "consistency" not in rule_types
        assert "weekly_target" not in rule_types

    def test_all_four_engines_have_distinct_rule_signatures(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        sigs = {
            key: tuple(sorted(r.rule_type for r in eng.get_rules()))
            for key, eng in engines.items()
        }
        # Each rule signature must be unique — proves products do not collapse.
        assert len(set(sigs.values())) == 4, sigs


class TestDrawdownMethodPerProduct:
    @pytest.mark.parametrize(
        "key,expected_method",
        [
            ("ftmo", DrawdownMethod.BALANCE_BASED),
            ("bootstrap", DrawdownMethod.BALANCE_BASED),
            ("high_stakes", DrawdownMethod.EQUITY_PEAK),
            ("hyper_growth", DrawdownMethod.BALANCE_BASED),
        ],
    )
    def test_product_drawdown_method(
        self,
        firm_registry: FirmRegistry,
        accounts: dict[str, AccountConfig],
        key: str,
        expected_method: DrawdownMethod,
    ) -> None:
        acct = accounts[key]
        _firm, product, _phase = firm_registry.resolve(
            acct.firm_id, acct.product_id, acct.phase
        )
        assert product.drawdown_method is expected_method


# ---------------------------------------------------------------------------
# Engine isolation under shared adversarial input
# ---------------------------------------------------------------------------


def _ctx(*, daily_pnl_percent: float, total_drawdown_percent: float = 0.0) -> dict:
    """Build a validation context covering daily-loss + drawdown rules.

    The four balance/equity keys (`account_balance`, `balance`,
    `current_equity`, `daily_starting_balance`) are deliberately set to
    the same `initial_balance` so that position-size and balance-check
    rules stay inert. Tests that exercise those rules should override
    the relevant keys explicitly rather than relying on these defaults.
    """
    return {
        "daily_pnl_percent": daily_pnl_percent,
        "daily_pnl": daily_pnl_percent * 1000.0,
        "total_drawdown_percent": total_drawdown_percent,
        "current_equity": 100_000.0,
        "initial_balance": 100_000.0,
        "daily_starting_balance": 100_000.0,
        "peak_equity": 100_000.0,
        # Position-size rule context — pinned to keep that rule inert.
        "current_position_lots": 0.0,
        "order_lots": 0.0,
        "account_balance": 100_000.0,
        "balance": 100_000.0,
    }


class TestEngineIsolation:
    """Each account's RuleEngine has its own rule list — no shared state.

    Feeding the same context to all four engines should produce verdicts
    based on the products' own thresholds, not on each other's evaluation.
    """

    def test_six_percent_loss_blocks_every_account_independently(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        # 6% loss exceeds the 5% daily limit on every product. Each engine
        # blocks via its own rule instance — the test proves each engine
        # observes the loss without any cross-contamination.
        ctx = _ctx(daily_pnl_percent=-6.0)
        results = {key: eng.validate(ctx) for key, eng in engines.items()}
        for key, result in results.items():
            assert result.action is RuleAction.BLOCK, (
                f"{key} did not BLOCK on 6% daily loss: {result.action}"
            )
            assert result.blocked_by is not None
            assert result.blocked_by.rule_type == "daily_loss_limit", key

    def test_5_percent_drawdown_blocks_per_product_thresholds(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        # Same input, four different verdicts driven by the per-product
        # max_drawdown threshold:
        #   FTMO         (10%) → ALLOW
        #   Bootstrap     (4%) → BLOCK on max_drawdown (balance_based)
        #   High Stakes   (4%) → BLOCK on max_drawdown (equity_peak)
        #   Hyper Growth  (5%) → BLOCK on max_drawdown (>= threshold)
        ctx = _ctx(
            daily_pnl_percent=-1.0,  # well below daily-loss threshold
            total_drawdown_percent=5.0,
        )
        # equity 95k → 5% balance-based drawdown.
        ctx["current_equity"] = 95_000.0

        results = {key: eng.validate(ctx) for key, eng in engines.items()}

        # FTMO 10% limit not breached at 5% — must not BLOCK. WARN is
        # expected because FTMO's max_drawdown has `warning_at: [50, 70,
        # 85]` and 5% is exactly 50% of the 10% limit; any BLOCK here
        # would mean a different rule fired and is a real regression.
        assert results["ftmo"].action is not RuleAction.BLOCK
        assert results["ftmo"].blocked_by is None

        for key in ("bootstrap", "high_stakes", "hyper_growth"):
            assert results[key].action is RuleAction.BLOCK, (
                f"{key} expected BLOCK on max_drawdown, got {results[key].action}"
            )
            assert results[key].blocked_by is not None
            assert results[key].blocked_by.rule_type == "max_drawdown", key

    def test_engines_are_distinct_instances(
        self, engines: dict[str, RuleEngine]
    ) -> None:
        # Sanity: object identity — guards against a future refactor that
        # accidentally shares a single engine across accounts.
        ids = {id(eng) for eng in engines.values()}
        assert len(ids) == 4

    def test_engine_account_ids_match_their_owners(
        self,
        accounts: dict[str, AccountConfig],
        engines: dict[str, RuleEngine],
    ) -> None:
        for key in accounts:
            assert engines[key].account_id == accounts[key].id


# ---------------------------------------------------------------------------
# FTMO phase lifecycle is a single product with a linear chain
# ---------------------------------------------------------------------------


class TestFtmoChallengePhaseChain:
    def test_challenge_has_three_phases(
        self, firm_registry: FirmRegistry
    ) -> None:
        challenge = firm_registry.get("ftmo").get_product("challenge")
        ids = [p.phase_id for p in challenge.phases]
        assert ids == ["evaluation", "verification", "funded"]

    def test_evaluation_transitions_to_verification(
        self, firm_registry: FirmRegistry
    ) -> None:
        evaluation = (
            firm_registry.get("ftmo")
            .get_product("challenge")
            .get_phase("evaluation")
        )
        assert evaluation.allowed_transitions == ("verification",)

    def test_verification_transitions_to_funded(
        self, firm_registry: FirmRegistry
    ) -> None:
        verification = (
            firm_registry.get("ftmo")
            .get_product("challenge")
            .get_phase("verification")
        )
        assert verification.allowed_transitions == ("funded",)

    def test_funded_is_terminal(self, firm_registry: FirmRegistry) -> None:
        funded = (
            firm_registry.get("ftmo")
            .get_product("challenge")
            .get_phase("funded")
        )
        assert funded.allowed_transitions == ()


# ---------------------------------------------------------------------------
# The5ers phase structures — three products, three different lifecycles
# ---------------------------------------------------------------------------


class TestThe5ersPhaseStructures:
    """Bootstrap (single funded), High Stakes (eval→funded), Hyper Growth
    (single funded). A misconfigured ``allowed_transitions`` in
    ``the5ers.yaml`` should surface here.
    """

    def test_bootstrap_has_single_terminal_funded_phase(
        self, firm_registry: FirmRegistry
    ) -> None:
        bootstrap = firm_registry.get("the5ers").get_product("bootstrap")
        ids = [p.phase_id for p in bootstrap.phases]
        assert ids == ["funded"]
        assert bootstrap.get_phase("funded").allowed_transitions == ()

    def test_high_stakes_has_evaluation_to_funded_chain(
        self, firm_registry: FirmRegistry
    ) -> None:
        hs = firm_registry.get("the5ers").get_product("high_stakes")
        ids = [p.phase_id for p in hs.phases]
        assert ids == ["evaluation", "funded"]
        assert hs.get_phase("evaluation").allowed_transitions == ("funded",)
        assert hs.get_phase("funded").allowed_transitions == ()

    def test_hyper_growth_has_single_terminal_funded_phase(
        self, firm_registry: FirmRegistry
    ) -> None:
        hyper = firm_registry.get("the5ers").get_product("hyper_growth")
        ids = [p.phase_id for p in hyper.phases]
        assert ids == ["funded"]
        assert hyper.get_phase("funded").allowed_transitions == ()
