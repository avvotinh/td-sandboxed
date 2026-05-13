"""Unit tests for FirmRegistry YAML loader (Epic 9 P0.2)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from types import MappingProxyType

import pytest

from src.config.firm_profile import (
    DrawdownMethod,
    InstrumentClass,
    RegimeThresholds,
    ResetAnchor,
)
from src.config.firm_registry import (
    FirmNotFoundError,
    FirmProfileLoadError,
    FirmRegistry,
    FirmRegistryError,
    PhaseNotFoundError,
    ProductNotFoundError,
)


FTMO_YAML = dedent(
    """
    firm_id: ftmo
    name: "FTMO"
    version: "2025.1"
    instrument_class: forex_cfd
    session:
      timezone: "CET"
      reset_time: "00:00"
      reset_anchor: midnight
    commission:
      per_lot_usd: 7.0
      spread_pips:
        EURUSD: 0.8
    products:
      challenge:
        product_id: challenge
        name: "FTMO Challenge"
        drawdown_method: balance_based
        rules:
          - type: daily_loss_limit
            threshold_percent: 5.0
            reset_time: "00:00"
            timezone: "CET"
          - type: max_drawdown
            threshold_percent: 10.0
        phases:
          - phase_id: evaluation
            name: Evaluation
            rule_overrides:
              profit_target:
                threshold_percent: 10.0
            allowed_transitions: [verification]
          - phase_id: verification
            name: Verification
            allowed_transitions: [funded]
          - phase_id: funded
            name: Funded
    report_template:
      template_id: ftmo_daily
    """
).strip()


THE5ERS_YAML = dedent(
    """
    firm_id: the5ers
    name: "The5ers"
    version: "2026.1"
    session:
      timezone: "UTC"
      reset_time: "00:00"
    products:
      bootstrap:
        product_id: bootstrap
        name: "Bootstrap"
        drawdown_method: equity_peak
        rules:
          - type: daily_loss_limit
            threshold_percent: 5.0
            timezone: "UTC"
          - type: max_drawdown
            threshold_percent: 4.0
        phases:
          - phase_id: funded
            name: Funded
        symbol_overrides:
          allowed_symbols: [EURUSD, GBPUSD]
          max_leverage: 30.0
        scaling_policy:
          policy_id: the5ers_bootstrap
          params: {step_up_percent: 10.0}
    """
).strip()


@pytest.fixture
def firms_dir(tmp_path: Path) -> Path:
    d = tmp_path / "firms"
    d.mkdir()
    (d / "ftmo.yaml").write_text(FTMO_YAML)
    (d / "the5ers.yaml").write_text(THE5ERS_YAML)
    return d


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestLoadSuccess:
    def test_load_registers_both_firms(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        assert registry.list_firms() == ["ftmo", "the5ers"]

    def test_ftmo_profile_fields(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        ftmo = registry.get("ftmo")
        assert ftmo.firm_id == "ftmo"
        assert ftmo.name == "FTMO"
        assert ftmo.version == "2025.1"
        assert ftmo.instrument_class is InstrumentClass.FOREX_CFD
        assert ftmo.session.timezone == "CET"
        assert ftmo.session.reset_anchor is ResetAnchor.MIDNIGHT
        assert ftmo.commission is not None
        assert ftmo.commission.per_lot_usd == 7.0
        assert ftmo.commission.spread_pips["EURUSD"] == 0.8

    def test_ftmo_challenge_product(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        product = registry.get("ftmo").get_product("challenge")
        assert product.product_id == "challenge"
        assert product.drawdown_method is DrawdownMethod.BALANCE_BASED
        assert len(product.rules) == 2
        assert [r.rule_type for r in product.rules] == [
            "daily_loss_limit",
            "max_drawdown",
        ]
        assert [p.phase_id for p in product.phases] == [
            "evaluation",
            "verification",
            "funded",
        ]

    def test_phase_overrides_and_transitions(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        phase = registry.get("ftmo").get_product("challenge").get_phase("evaluation")
        assert phase.allowed_transitions == ("verification",)
        assert phase.rule_overrides["profit_target"]["threshold_percent"] == 10.0

    def test_the5ers_equity_peak_and_symbol_policy(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        product = registry.get("the5ers").get_product("bootstrap")
        assert product.drawdown_method is DrawdownMethod.EQUITY_PEAK
        assert product.symbol_overrides is not None
        assert product.symbol_overrides.allowed_symbols == ("EURUSD", "GBPUSD")
        assert product.symbol_overrides.max_leverage == 30.0
        assert product.scaling_policy is not None
        assert product.scaling_policy.policy_id == "the5ers_bootstrap"
        assert product.scaling_policy.params["step_up_percent"] == 10.0

    def test_resolve_returns_firm_product_phase(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        firm, product, phase = registry.resolve("ftmo", "challenge", "verification")
        assert firm.firm_id == "ftmo"
        assert product.product_id == "challenge"
        assert phase.phase_id == "verification"


# ---------------------------------------------------------------------------
# Story 13.8 — Phase 1 strategy_overrides per-firm wiring
# ---------------------------------------------------------------------------


_STRATEGY_OVERRIDES_YAML = dedent(
    """
    firm_id: with_overrides
    name: "WithOverrides"
    version: "2026.5"
    session:
      timezone: "UTC"
      reset_time: "00:00"
    products:
      challenge:
        product_id: challenge
        name: "Challenge"
        rules:
          - type: daily_loss_limit
            threshold_percent: 5.0
            timezone: "UTC"
        phases:
          - phase_id: evaluation
            name: Evaluation
    strategies:
      supertrend:
        scale_out_enabled: true
        scale_out_r_trigger: 1.0
        scale_out_close_fraction: 0.5
        breakeven_at_r: 1.0
        trailing_enabled: true
        trailing_method: supertrend
        trailing_atr_period: 7
        trailing_atr_multiplier: 2.1
        safety_tp_atr_mult: 6.0
      donchian_breakout:
        scale_out_enabled: false
    """
).strip()


class TestStrategyOverrides:
    """Story 13.8 — strategies block on firm YAML loads into FirmProfile."""

    def test_default_empty_when_strategies_absent(
        self, firms_dir: Path
    ) -> None:
        # The fixture FTMO_YAML doesn't declare a strategies block — the
        # profile must still load and expose strategy_overrides as an
        # empty mapping (legacy ftmo.yaml callers must keep working).
        registry = FirmRegistry(firms_dir)
        registry.load()
        ftmo = registry.get("ftmo")
        assert dict(ftmo.strategy_overrides) == {}

    def test_strategies_block_loaded(self, tmp_path: Path) -> None:
        d = tmp_path / "firms"
        d.mkdir()
        (d / "with_overrides.yaml").write_text(_STRATEGY_OVERRIDES_YAML)

        registry = FirmRegistry(d)
        registry.load()
        firm = registry.get("with_overrides")

        assert "supertrend" in firm.strategy_overrides
        assert "donchian_breakout" in firm.strategy_overrides

        st_overrides = firm.strategy_overrides["supertrend"]
        assert st_overrides["scale_out_enabled"] is True
        assert st_overrides["scale_out_r_trigger"] == 1.0
        assert st_overrides["trailing_atr_multiplier"] == 2.1
        assert st_overrides["safety_tp_atr_mult"] == 6.0

        dc_overrides = firm.strategy_overrides["donchian_breakout"]
        assert dc_overrides["scale_out_enabled"] is False

    def test_strategy_overrides_immutable(self, tmp_path: Path) -> None:
        # Profile-side overrides must be read-only — a caller can't
        # mutate the registry's view by mutating the dict reference.
        d = tmp_path / "firms"
        d.mkdir()
        (d / "with_overrides.yaml").write_text(_STRATEGY_OVERRIDES_YAML)

        registry = FirmRegistry(d)
        registry.load()
        firm = registry.get("with_overrides")

        with pytest.raises(TypeError):
            firm.strategy_overrides["new_strategy"] = {}  # type: ignore[index]
        with pytest.raises(TypeError):
            firm.strategy_overrides["supertrend"]["scale_out_enabled"] = False  # type: ignore[index]

    def test_real_ftmo_yaml_strategies_block_loads(self) -> None:
        # Smoke: the real configs/firms/ftmo.yaml carries a strategies
        # block (supertrend / donchian_breakout / ma_crossover, all
        # default-OFF). Verify the registry parses it without crashing
        # and the entries are present with expected default values.
        # __file__ → services/trading-engine/tests/unit/test_firm_registry.py
        # parents[2] = services/trading-engine/, parents[4] = repo root.
        repo_root = Path(__file__).resolve().parents[4]
        firms_dir_real = repo_root / "configs" / "firms"
        registry = FirmRegistry(firms_dir_real)
        registry.load()
        ftmo = registry.get("ftmo")

        for strategy_id in ("supertrend", "donchian_breakout", "ma_crossover"):
            assert strategy_id in ftmo.strategy_overrides, (
                f"Phase 1 entry missing for {strategy_id}"
            )
            overrides = ftmo.strategy_overrides[strategy_id]
            # Default-OFF safety: never ship the YAML with the feature
            # flipped on before story 13.9 backtest validation passes.
            assert overrides["scale_out_enabled"] is False
            assert overrides["trailing_enabled"] is False


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestLoadErrors:
    def test_missing_firms_dir(self, tmp_path: Path):
        registry = FirmRegistry(tmp_path / "missing")
        with pytest.raises(FirmProfileLoadError, match="does not exist"):
            registry.load()

    def test_firms_dir_is_file_not_directory(self, tmp_path: Path):
        target = tmp_path / "firms_not_a_dir"
        target.write_text("oops")
        registry = FirmRegistry(target)
        with pytest.raises(FirmProfileLoadError, match="not a directory"):
            registry.load()

    def test_empty_firms_dir(self, tmp_path: Path):
        empty = tmp_path / "firms"
        empty.mkdir()
        registry = FirmRegistry(empty)
        with pytest.raises(FirmProfileLoadError, match="no firm YAMLs"):
            registry.load()

    def test_invalid_yaml_syntax(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        (d / "bad.yaml").write_text("firm_id: [unclosed")
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="YAML syntax"):
            registry.load()

    def test_empty_yaml_file(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        (d / "empty.yaml").write_text("")
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="empty"):
            registry.load()

    def test_schema_missing_required_field(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        (d / "broken.yaml").write_text("firm_id: x\nname: x\nversion: '1'\n")
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="schema"):
            registry.load()

    def test_schema_unknown_field_rejected(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        bad = FTMO_YAML + "\nunknown_key: oops\n"
        (d / "ftmo.yaml").write_text(bad)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="schema"):
            registry.load()

    def test_unknown_rule_type_surfaces(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        broken = FTMO_YAML.replace("daily_loss_limit", "not_a_rule")
        (d / "ftmo.yaml").write_text(broken)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="not_a_rule"):
            registry.load()

    def test_product_id_mismatch_in_dict_key(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        (d / "ftmo.yaml").write_text(
            FTMO_YAML.replace("challenge:", "wrong_key:", 1)
        )
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="mismatches dict key"):
            registry.load()

    def test_duplicate_firm_id_across_files(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        (d / "a.yaml").write_text(FTMO_YAML)
        (d / "b.yaml").write_text(FTMO_YAML)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="duplicate firm_id"):
            registry.load()

    def test_timezone_invalid_zone(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        broken = FTMO_YAML.replace('timezone: "CET"', 'timezone: "Not/Real"', 1)
        (d / "ftmo.yaml").write_text(broken)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="IANA zone"):
            registry.load()

    def test_invalid_reset_time_format(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        broken = FTMO_YAML.replace('reset_time: "00:00"', 'reset_time: "noon"', 1)
        (d / "ftmo.yaml").write_text(broken)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="reset_time"):
            registry.load()


# ---------------------------------------------------------------------------
# Lookup / lifecycle
# ---------------------------------------------------------------------------


class TestLookup:
    def test_get_before_load_raises(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        with pytest.raises(FirmRegistryError, match="not loaded"):
            registry.get("ftmo")

    def test_list_firms_before_load_raises(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        with pytest.raises(FirmRegistryError, match="not loaded"):
            registry.list_firms()

    def test_unknown_firm_raises_firm_not_found(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        with pytest.raises(FirmNotFoundError, match="apex"):
            registry.get("apex")

    def test_resolve_unknown_product_raises_typed_error(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        with pytest.raises(ProductNotFoundError, match="no product"):
            registry.resolve("ftmo", "nonexistent", "funded")

    def test_resolve_unknown_phase_raises_typed_error(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        with pytest.raises(PhaseNotFoundError, match="no phase"):
            registry.resolve("ftmo", "challenge", "nonexistent")

    def test_resolve_errors_all_inherit_from_firm_registry_error(
        self, firms_dir: Path
    ):
        registry = FirmRegistry(firms_dir)
        registry.load()
        for call, _ in [
            (("apex", "challenge", "funded"), FirmNotFoundError),
            (("ftmo", "apex", "funded"), ProductNotFoundError),
            (("ftmo", "challenge", "mars"), PhaseNotFoundError),
        ]:
            with pytest.raises(FirmRegistryError):
                registry.resolve(*call)

    def test_load_is_idempotent(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        registry.load()
        assert registry.list_firms() == ["ftmo", "the5ers"]


# ---------------------------------------------------------------------------
# Regime classifier block (Epic 11 story 11.2)
# ---------------------------------------------------------------------------


_REGIME_BLOCK = dedent(
    """
    regime_classifier:
      enabled: false
      confirmation_bars: 2
      warmup_bars: 50
      feature_window: 200
      instruments:
        XAUUSD:
          timeframe: M5
          adx_period: 14
          bb_period: 20
          bb_stddev: 2.0
          bb_baseline_window: 100
          realized_vol_window: 20
          ema_slope_period: 20
          ema_slope_lookback: 5
          thresholds:
            adx_trend_min: 25.0
            adx_strong_trend: 40.0
            bb_width_low_pct: 0.30
            bb_width_high_pct: 0.80
            realized_vol_high: 0.025
            ema_slope_trend_threshold: 0.0005
    """
).strip()


def _ftmo_yaml_with_regime_block(block: str = _REGIME_BLOCK) -> str:
    return f"{FTMO_YAML}\n{block}"


class TestRegimeClassifierLoading:
    def test_block_absent_loads_with_none(self, firms_dir: Path):
        registry = FirmRegistry(firms_dir)
        registry.load()
        assert registry.get("ftmo").regime_classifier is None

    def test_block_present_round_trips(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        (d / "ftmo.yaml").write_text(_ftmo_yaml_with_regime_block())
        registry = FirmRegistry(d)
        registry.load()
        rc = registry.get("ftmo").regime_classifier
        assert rc is not None
        assert rc.enabled is False
        assert rc.confirmation_bars == 2
        assert rc.warmup_bars == 50
        assert rc.feature_window == 200
        assert isinstance(rc.instruments, MappingProxyType)
        assert "XAUUSD" in rc.instruments
        xau = rc.get_instrument("XAUUSD")
        assert xau.timeframe == "M5"
        assert xau.bb_period == 20
        assert isinstance(xau.thresholds, RegimeThresholds)
        assert xau.thresholds.adx_trend_min == pytest.approx(25.0)
        assert xau.thresholds.bb_width_high_pct == pytest.approx(0.80)

    def test_invalid_threshold_surfaces_load_error(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        broken = _ftmo_yaml_with_regime_block(
            _REGIME_BLOCK.replace("adx_trend_min: 25.0", "adx_trend_min: -1.0")
        )
        (d / "ftmo.yaml").write_text(broken)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="adx_trend_min"):
            registry.load()

    def test_unknown_field_in_regime_block_rejected(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        broken = _ftmo_yaml_with_regime_block(
            _REGIME_BLOCK.replace("enabled: false", "enabled: false\n  unknown_field: 7")
        )
        (d / "ftmo.yaml").write_text(broken)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="unknown_field"):
            registry.load()

    def test_enabled_with_empty_instruments_rejected(self, tmp_path: Path):
        d = tmp_path / "firms"
        d.mkdir()
        broken = _ftmo_yaml_with_regime_block(
            dedent(
                """
                regime_classifier:
                  enabled: true
                  confirmation_bars: 2
                  warmup_bars: 50
                  feature_window: 200
                  instruments: {}
                """
            ).strip()
        )
        (d / "ftmo.yaml").write_text(broken)
        registry = FirmRegistry(d)
        with pytest.raises(FirmProfileLoadError, match="instruments"):
            registry.load()
