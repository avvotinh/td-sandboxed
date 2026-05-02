"""Unit tests for FirmProfile data model (Epic 9 P0.1).

Covers frozen dataclasses: SessionConfig, CommissionProfile, SymbolPolicy,
ScalingPolicy, AccountPhase, ReportTemplate, AccountProduct, FirmProfile, and
their enums (ResetAnchor, InstrumentClass, DrawdownMethod).

Pure data-model tests — no loader, no YAML, no rule parser.
"""

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from src.config.firm_profile import (
    AccountPhase,
    AccountProduct,
    CommissionProfile,
    DrawdownMethod,
    FirmProfile,
    InstrumentClass,
    InstrumentRegimeConfig,
    RegimeConfig,
    RegimeThresholds,
    ReportTemplate,
    ResetAnchor,
    ScalingPolicy,
    SessionConfig,
    SymbolPolicy,
)
from tests.conftest import FakeRule


# ---------------------------------------------------------------------------
# SessionConfig
# ---------------------------------------------------------------------------


class TestSessionConfig:
    def test_defaults_reset_anchor_to_midnight(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        assert session.reset_anchor is ResetAnchor.MIDNIGHT

    def test_accepts_market_close_anchor(self):
        session = SessionConfig(
            timezone="America/New_York",
            reset_time="17:00",
            reset_anchor=ResetAnchor.MARKET_CLOSE,
        )
        assert session.reset_anchor is ResetAnchor.MARKET_CLOSE

    def test_is_frozen(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        with pytest.raises(FrozenInstanceError):
            session.timezone = "CET"  # type: ignore[misc]

    def test_rejects_invalid_reset_time_format(self):
        with pytest.raises(ValueError, match="reset_time"):
            SessionConfig(timezone="UTC", reset_time="noon")

    def test_rejects_out_of_range_hours(self):
        with pytest.raises(ValueError, match="reset_time"):
            SessionConfig(timezone="UTC", reset_time="25:00")

    def test_rejects_empty_timezone(self):
        with pytest.raises(ValueError, match="timezone"):
            SessionConfig(timezone="", reset_time="00:00")

    def test_rejects_non_iana_timezone(self):
        with pytest.raises(ValueError, match="IANA zone"):
            SessionConfig(timezone="Middle-Earth/Shire", reset_time="00:00")

    def test_accepts_cet_and_america_ny(self):
        SessionConfig(timezone="CET", reset_time="00:00")
        SessionConfig(
            timezone="America/New_York",
            reset_time="17:00",
            reset_anchor=ResetAnchor.MARKET_CLOSE,
        )


# ---------------------------------------------------------------------------
# CommissionProfile
# ---------------------------------------------------------------------------


class TestCommissionProfile:
    def test_defaults_are_empty(self):
        profile = CommissionProfile()
        assert profile.per_lot_usd == 0.0
        assert profile.spread_pips == {}
        assert profile.swap_long_pips == {}
        assert profile.swap_short_pips == {}

    def test_accepts_per_symbol_overrides(self):
        profile = CommissionProfile(
            per_lot_usd=7.0,
            spread_pips={"EURUSD": 0.8, "XAUUSD": 2.5},
        )
        assert profile.per_lot_usd == 7.0
        assert profile.spread_pips["EURUSD"] == 0.8

    def test_rejects_negative_per_lot_usd(self):
        with pytest.raises(ValueError, match="per_lot_usd"):
            CommissionProfile(per_lot_usd=-1.0)

    def test_is_frozen(self):
        profile = CommissionProfile()
        with pytest.raises(FrozenInstanceError):
            profile.per_lot_usd = 10.0  # type: ignore[misc]

    def test_spread_pips_is_read_only(self):
        src = {"EURUSD": 0.8}
        profile = CommissionProfile(spread_pips=src)
        with pytest.raises(TypeError):
            profile.spread_pips["EURUSD"] = 99.0  # type: ignore[index]
        src["EURUSD"] = 123.0
        assert profile.spread_pips["EURUSD"] == 0.8


# ---------------------------------------------------------------------------
# SymbolPolicy
# ---------------------------------------------------------------------------


class TestSymbolPolicy:
    def test_defaults_allow_all(self):
        policy = SymbolPolicy()
        assert policy.allowed_symbols == ()
        assert policy.disallowed_symbols == ()
        assert policy.max_leverage is None

    def test_captures_allowed_and_max_leverage(self):
        policy = SymbolPolicy(
            allowed_symbols=("EURUSD", "GBPUSD"),
            max_leverage=30.0,
        )
        assert policy.allowed_symbols == ("EURUSD", "GBPUSD")
        assert policy.max_leverage == 30.0

    def test_rejects_overlap_between_allow_and_disallow(self):
        with pytest.raises(ValueError, match="overlap"):
            SymbolPolicy(
                allowed_symbols=("EURUSD",),
                disallowed_symbols=("EURUSD",),
            )

    def test_rejects_non_positive_leverage(self):
        with pytest.raises(ValueError, match="max_leverage"):
            SymbolPolicy(max_leverage=0.0)


# ---------------------------------------------------------------------------
# ScalingPolicy
# ---------------------------------------------------------------------------


class TestScalingPolicy:
    def test_opaque_params_accepted(self):
        policy = ScalingPolicy(
            policy_id="the5ers_hyper_growth",
            params={"step_up_percent": 10.0, "cap": 4.0},
        )
        assert policy.policy_id == "the5ers_hyper_growth"
        assert policy.params["cap"] == 4.0

    def test_rejects_empty_policy_id(self):
        with pytest.raises(ValueError, match="policy_id"):
            ScalingPolicy(policy_id="")


# ---------------------------------------------------------------------------
# AccountPhase
# ---------------------------------------------------------------------------


class TestAccountPhase:
    def test_minimal_phase(self):
        phase = AccountPhase(phase_id="evaluation", name="Evaluation")
        assert phase.phase_id == "evaluation"
        assert phase.allowed_transitions == ()
        assert phase.rule_overrides == {}

    def test_with_transitions_and_overrides(self):
        phase = AccountPhase(
            phase_id="evaluation",
            name="Evaluation",
            rule_overrides={"profit_target": {"threshold_percent": 10.0}},
            allowed_transitions=("verification",),
        )
        assert phase.allowed_transitions == ("verification",)
        assert phase.rule_overrides["profit_target"]["threshold_percent"] == 10.0

    def test_rejects_empty_phase_id(self):
        with pytest.raises(ValueError, match="phase_id"):
            AccountPhase(phase_id="", name="x")

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError, match="name"):
            AccountPhase(phase_id="evaluation", name="")

    def test_rule_overrides_is_read_only(self):
        src = {"profit_target": {"threshold_percent": 10.0}}
        phase = AccountPhase(phase_id="eval", name="Eval", rule_overrides=src)
        with pytest.raises(TypeError):
            phase.rule_overrides["extra"] = {}  # type: ignore[index]
        src["profit_target"]["threshold_percent"] = 999.0
        # The outer mapping is detached from src — but nested dicts are shared by design.
        # This test guards the top-level immutability that the frozen dataclass promises.
        assert "extra" not in phase.rule_overrides


# ---------------------------------------------------------------------------
# AccountProduct
# ---------------------------------------------------------------------------


def _phase(pid: str, *transitions: str) -> AccountPhase:
    return AccountPhase(phase_id=pid, name=pid.title(), allowed_transitions=transitions)


class TestAccountProduct:
    def test_minimal_product(self):
        product = AccountProduct(
            product_id="challenge",
            name="FTMO Challenge",
            rules=(FakeRule(),),
            phases=(_phase("evaluation", "verification"), _phase("verification", "funded"), _phase("funded")),
        )
        assert product.drawdown_method is DrawdownMethod.BALANCE_BASED
        assert product.commission_overrides is None
        assert product.symbol_overrides is None
        assert product.scaling_policy is None
        assert len(product.phases) == 3

    def test_rejects_duplicate_phase_ids(self):
        with pytest.raises(ValueError, match="duplicate phase"):
            AccountProduct(
                product_id="challenge",
                name="FTMO Challenge",
                rules=(FakeRule(),),
                phases=(_phase("evaluation"), _phase("evaluation")),
            )

    def test_rejects_unknown_transition_target(self):
        with pytest.raises(ValueError, match="unknown phase"):
            AccountProduct(
                product_id="challenge",
                name="FTMO Challenge",
                rules=(FakeRule(),),
                phases=(_phase("evaluation", "nonexistent"),),
            )

    def test_rejects_empty_product_id(self):
        with pytest.raises(ValueError, match="product_id"):
            AccountProduct(
                product_id="",
                name="x",
                rules=(FakeRule(),),
                phases=(_phase("evaluation"),),
            )

    def test_rejects_empty_phases(self):
        with pytest.raises(ValueError, match="at least one phase"):
            AccountProduct(
                product_id="challenge",
                name="x",
                rules=(FakeRule(),),
                phases=(),
            )

    def test_rejects_empty_rules(self):
        with pytest.raises(ValueError, match="at least one rule"):
            AccountProduct(
                product_id="challenge",
                name="x",
                rules=(),
                phases=(_phase("funded"),),
            )

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError, match="AccountProduct.name"):
            AccountProduct(
                product_id="challenge",
                name="",
                rules=(FakeRule(),),
                phases=(_phase("funded"),),
            )

    def test_accepts_list_inputs_and_freezes_to_tuple(self):
        rules_list = [FakeRule()]
        phases_list = [_phase("funded")]
        product = AccountProduct(
            product_id="challenge",
            name="FTMO Challenge",
            rules=rules_list,
            phases=phases_list,
        )
        assert isinstance(product.rules, tuple)
        assert isinstance(product.phases, tuple)
        rules_list.append(FakeRule(rule_type="other"))
        assert len(product.rules) == 1

    def test_can_carry_equity_peak_drawdown_method(self):
        product = AccountProduct(
            product_id="high_stakes",
            name="The5ers High Stakes",
            rules=(FakeRule(),),
            phases=(_phase("funded"),),
            drawdown_method=DrawdownMethod.EQUITY_PEAK,
        )
        assert product.drawdown_method is DrawdownMethod.EQUITY_PEAK

    def test_get_phase_returns_by_id(self):
        product = AccountProduct(
            product_id="challenge",
            name="FTMO Challenge",
            rules=(FakeRule(),),
            phases=(_phase("evaluation", "verification"), _phase("verification")),
        )
        assert product.get_phase("verification").phase_id == "verification"

    def test_get_phase_raises_on_unknown(self):
        product = AccountProduct(
            product_id="challenge",
            name="FTMO Challenge",
            rules=(FakeRule(),),
            phases=(_phase("funded"),),
        )
        with pytest.raises(KeyError, match="no phase 'evaluation'"):
            product.get_phase("evaluation")


# ---------------------------------------------------------------------------
# FirmProfile
# ---------------------------------------------------------------------------


def _product(pid: str) -> AccountProduct:
    return AccountProduct(
        product_id=pid,
        name=pid,
        rules=(FakeRule(),),
        phases=(_phase("funded"),),
    )


class TestFirmProfile:
    def test_minimal_firm(self):
        firm = FirmProfile(
            firm_id="ftmo",
            name="FTMO",
            version="2025.1",
            session=SessionConfig(timezone="CET", reset_time="00:00"),
            products={"challenge": _product("challenge")},
        )
        assert firm.instrument_class is InstrumentClass.FOREX_CFD
        assert firm.commission is None
        assert firm.report_template is None
        assert firm.notification_template == {}

    def test_get_product_returns_registered(self):
        firm = FirmProfile(
            firm_id="the5ers",
            name="The5ers",
            version="2026.1",
            session=SessionConfig(timezone="UTC", reset_time="00:00"),
            products={
                "bootstrap": _product("bootstrap"),
                "high_stakes": _product("high_stakes"),
            },
        )
        assert firm.get_product("bootstrap").product_id == "bootstrap"

    def test_get_product_raises_on_unknown(self):
        firm = FirmProfile(
            firm_id="the5ers",
            name="The5ers",
            version="2026.1",
            session=SessionConfig(timezone="UTC", reset_time="00:00"),
            products={"bootstrap": _product("bootstrap")},
        )
        with pytest.raises(KeyError, match="no product 'hyper_growth'"):
            firm.get_product("hyper_growth")

    def test_rejects_empty_products(self):
        with pytest.raises(ValueError, match="at least one product"):
            FirmProfile(
                firm_id="ftmo",
                name="FTMO",
                version="2025.1",
                session=SessionConfig(timezone="CET", reset_time="00:00"),
                products={},
            )

    def test_rejects_key_product_id_mismatch(self):
        with pytest.raises(ValueError, match="mismatches dict key"):
            FirmProfile(
                firm_id="ftmo",
                name="FTMO",
                version="2025.1",
                session=SessionConfig(timezone="CET", reset_time="00:00"),
                products={"wrong_key": _product("challenge")},
            )

    def test_rejects_empty_firm_id(self):
        with pytest.raises(ValueError, match="firm_id"):
            FirmProfile(
                firm_id="",
                name="x",
                version="1",
                session=SessionConfig(timezone="UTC", reset_time="00:00"),
                products={"p": _product("p")},
            )

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError, match="FirmProfile.name"):
            FirmProfile(
                firm_id="ftmo",
                name="",
                version="1",
                session=SessionConfig(timezone="CET", reset_time="00:00"),
                products={"p": _product("p")},
            )

    def test_products_are_read_only(self):
        firm = FirmProfile(
            firm_id="ftmo",
            name="FTMO",
            version="2025.1",
            session=SessionConfig(timezone="CET", reset_time="00:00"),
            products={"challenge": _product("challenge")},
        )
        with pytest.raises(TypeError):
            firm.products["hacked"] = _product("hacked")  # type: ignore[index]

    def test_rejects_empty_version(self):
        with pytest.raises(ValueError, match="version"):
            FirmProfile(
                firm_id="ftmo",
                name="FTMO",
                version="",
                session=SessionConfig(timezone="CET", reset_time="00:00"),
                products={"p": _product("p")},
            )

    def test_is_frozen(self):
        firm = FirmProfile(
            firm_id="ftmo",
            name="FTMO",
            version="2025.1",
            session=SessionConfig(timezone="CET", reset_time="00:00"),
            products={"p": _product("p")},
        )
        with pytest.raises(FrozenInstanceError):
            firm.firm_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ReportTemplate
# ---------------------------------------------------------------------------


class TestReportTemplate:
    def test_minimal_template(self):
        template = ReportTemplate(template_id="ftmo_daily")
        assert template.variables == {}

    def test_rejects_empty_template_id(self):
        with pytest.raises(ValueError, match="template_id"):
            ReportTemplate(template_id="")


# ---------------------------------------------------------------------------
# RegimeThresholds (Epic 11 story 11.2)
# ---------------------------------------------------------------------------


def _thresholds(**overrides: float) -> RegimeThresholds:
    base: dict[str, float] = dict(
        adx_trend_min=25.0,
        adx_strong_trend=40.0,
        bb_width_low_pct=0.30,
        bb_width_high_pct=0.80,
        realized_vol_high=0.025,
        ema_slope_trend_threshold=0.0005,
    )
    base.update(overrides)
    return RegimeThresholds(**base)


class TestRegimeThresholds:
    def test_minimal_construction(self):
        t = _thresholds()
        assert t.adx_trend_min == pytest.approx(25.0)
        assert t.bb_width_high_pct == pytest.approx(0.80)

    def test_is_frozen(self):
        t = _thresholds()
        with pytest.raises(FrozenInstanceError):
            t.adx_trend_min = 99.0  # type: ignore[misc]

    @pytest.mark.parametrize(
        "field, bad_value, match",
        [
            ("adx_trend_min", 0.0, "adx_trend_min"),
            ("adx_trend_min", -1.0, "adx_trend_min"),
            ("adx_strong_trend", 0.0, "adx_strong_trend"),
            ("realized_vol_high", 0.0, "realized_vol_high"),
            ("ema_slope_trend_threshold", 0.0, "ema_slope_trend_threshold"),
            ("ema_slope_trend_threshold", -0.001, "ema_slope_trend_threshold"),
        ],
    )
    def test_rejects_non_positive_values(
        self, field: str, bad_value: float, match: str
    ):
        with pytest.raises(ValueError, match=match):
            _thresholds(**{field: bad_value})

    def test_rejects_strong_trend_below_trend_min(self):
        # adx_strong_trend < adx_trend_min would invert the rule semantics.
        with pytest.raises(ValueError, match="adx_strong_trend"):
            _thresholds(adx_trend_min=30.0, adx_strong_trend=20.0)

    def test_strong_trend_equal_to_trend_min_is_allowed(self):
        # The guard is `>=`, so equality is the documented boundary.
        t = _thresholds(adx_trend_min=25.0, adx_strong_trend=25.0)
        assert t.adx_strong_trend == pytest.approx(25.0)

    @pytest.mark.parametrize("field", ["bb_width_low_pct", "bb_width_high_pct"])
    @pytest.mark.parametrize("bad_value", [-0.01, 1.01, 1.5])
    def test_bb_width_pct_must_be_in_unit_interval(
        self, field: str, bad_value: float
    ):
        with pytest.raises(ValueError, match=field):
            _thresholds(**{field: bad_value})

    def test_rejects_high_pct_below_low_pct(self):
        with pytest.raises(ValueError, match="bb_width_high_pct"):
            _thresholds(bb_width_low_pct=0.7, bb_width_high_pct=0.3)


# ---------------------------------------------------------------------------
# InstrumentRegimeConfig (Epic 11 story 11.2)
# ---------------------------------------------------------------------------


def _instrument_config(**overrides: object) -> InstrumentRegimeConfig:
    base: dict[str, object] = dict(
        timeframe="M5",
        thresholds=_thresholds(),
        adx_period=14,
        bb_period=20,
        bb_stddev=2.0,
        bb_baseline_window=100,
        realized_vol_window=20,
        ema_slope_period=20,
        ema_slope_lookback=5,
    )
    base.update(overrides)
    return InstrumentRegimeConfig(**base)  # type: ignore[arg-type]


class TestInstrumentRegimeConfig:
    def test_minimal_construction(self):
        cfg = _instrument_config()
        assert cfg.timeframe == "M5"
        assert cfg.adx_period == 14
        assert isinstance(cfg.thresholds, RegimeThresholds)

    def test_is_frozen(self):
        cfg = _instrument_config()
        with pytest.raises(FrozenInstanceError):
            cfg.adx_period = 99  # type: ignore[misc]

    @pytest.mark.parametrize("tf", ["M5", "M15"])
    def test_accepts_supported_timeframes(self, tf: str):
        cfg = _instrument_config(timeframe=tf)
        assert cfg.timeframe == tf

    @pytest.mark.parametrize("bad_tf", ["", "M1", "H1", "M30"])
    def test_rejects_unsupported_timeframes(self, bad_tf: str):
        with pytest.raises(ValueError, match="timeframe"):
            _instrument_config(timeframe=bad_tf)

    @pytest.mark.parametrize(
        "field",
        [
            "adx_period",
            "bb_period",
            "bb_baseline_window",
            "realized_vol_window",
            "ema_slope_period",
            "ema_slope_lookback",
        ],
    )
    def test_period_fields_must_be_positive_int(self, field: str):
        with pytest.raises(ValueError, match=field):
            _instrument_config(**{field: 0})
        with pytest.raises(ValueError, match=field):
            _instrument_config(**{field: -1})

    def test_bb_stddev_must_be_positive(self):
        with pytest.raises(ValueError, match="bb_stddev"):
            _instrument_config(bb_stddev=0.0)

    def test_baseline_window_must_be_at_least_period(self):
        # Percentile baseline shorter than the BB period itself is degenerate.
        with pytest.raises(ValueError, match="bb_baseline_window"):
            _instrument_config(bb_period=20, bb_baseline_window=10)


# ---------------------------------------------------------------------------
# RegimeConfig (Epic 11 story 11.2)
# ---------------------------------------------------------------------------


def _regime_config(**overrides: object) -> RegimeConfig:
    base: dict[str, object] = dict(
        enabled=False,
        confirmation_bars=2,
        warmup_bars=50,
        feature_window=200,
        instruments={"XAUUSD": _instrument_config()},
    )
    base.update(overrides)
    return RegimeConfig(**base)  # type: ignore[arg-type]


class TestRegimeConfig:
    def test_minimal_disabled_construction(self):
        cfg = _regime_config()
        assert cfg.enabled is False
        assert cfg.confirmation_bars == 2
        assert "XAUUSD" in cfg.instruments

    def test_enabled_flag_round_trips(self):
        cfg = _regime_config(enabled=True)
        assert cfg.enabled is True

    def test_is_frozen(self):
        cfg = _regime_config()
        with pytest.raises(FrozenInstanceError):
            cfg.enabled = True  # type: ignore[misc]

    def test_instruments_mapping_is_immutable(self):
        cfg = _regime_config()
        assert isinstance(cfg.instruments, MappingProxyType)
        with pytest.raises(TypeError):
            cfg.instruments["EURUSD"] = _instrument_config()  # type: ignore[index]

    def test_instruments_mapping_detached_from_source(self):
        # Mutating the source dict after construction must not leak in —
        # _freeze_mapping makes a defensive copy first.
        source: dict[str, InstrumentRegimeConfig] = {"XAUUSD": _instrument_config()}
        cfg = _regime_config(instruments=source)
        source["EURUSD"] = _instrument_config()
        assert "EURUSD" not in cfg.instruments

    def test_rejects_non_positive_confirmation_bars(self):
        with pytest.raises(ValueError, match="confirmation_bars"):
            _regime_config(confirmation_bars=0)

    def test_rejects_non_positive_warmup_bars(self):
        with pytest.raises(ValueError, match="warmup_bars"):
            _regime_config(warmup_bars=0)

    def test_warmup_must_not_exceed_feature_window(self):
        with pytest.raises(ValueError, match="warmup_bars"):
            _regime_config(warmup_bars=300, feature_window=200)

    def test_feature_window_must_be_at_least_bb_baseline_window(self):
        # FeatureExtractor would otherwise read percentile from a baseline
        # bigger than its rolling buffer — silent semantic break.
        with pytest.raises(ValueError, match="feature_window"):
            _regime_config(
                feature_window=50,
                warmup_bars=20,
                instruments={"XAUUSD": _instrument_config(bb_baseline_window=100)},
            )

    def test_rejects_empty_instruments_when_enabled(self):
        with pytest.raises(ValueError, match="instruments"):
            _regime_config(enabled=True, instruments={})

    def test_allows_empty_instruments_when_disabled(self):
        # Operators staging the block with `enabled: false` and no instruments
        # populated yet is a legitimate intermediate state.
        cfg = _regime_config(enabled=False, instruments={})
        assert cfg.instruments == {}

    def test_get_instrument_returns_config(self):
        cfg = _regime_config()
        assert cfg.get_instrument("XAUUSD") is cfg.instruments["XAUUSD"]

    def test_get_instrument_raises_for_unknown_symbol(self):
        cfg = _regime_config()
        with pytest.raises(KeyError, match="EURUSD"):
            cfg.get_instrument("EURUSD")


# ---------------------------------------------------------------------------
# FirmProfile.regime_classifier (Epic 11 story 11.2)
# ---------------------------------------------------------------------------


class TestFirmProfileRegimeClassifier:
    def test_field_defaults_to_none(self):
        firm = FirmProfile(
            firm_id="ftmo",
            name="FTMO",
            version="2026.1",
            session=SessionConfig(timezone="CET", reset_time="00:00"),
            products={"p": _product("p")},
        )
        assert firm.regime_classifier is None

    def test_accepts_regime_classifier(self):
        rc = _regime_config(enabled=True)
        firm = FirmProfile(
            firm_id="ftmo",
            name="FTMO",
            version="2026.1",
            session=SessionConfig(timezone="CET", reset_time="00:00"),
            products={"p": _product("p")},
            regime_classifier=rc,
        )
        assert firm.regime_classifier is rc

    def test_remains_frozen_with_regime_classifier(self):
        firm = FirmProfile(
            firm_id="ftmo",
            name="FTMO",
            version="2026.1",
            session=SessionConfig(timezone="CET", reset_time="00:00"),
            products={"p": _product("p")},
            regime_classifier=_regime_config(),
        )
        with pytest.raises(FrozenInstanceError):
            firm.regime_classifier = None  # type: ignore[misc]
