"""Firm profile data model (Epic 9 Phase 0, task P0.1).

Introduces the multi-firm abstraction that replaces the FTMO-only assumption
baked into the engine. ``FirmProfile`` is the first-class organizing unit:
each prop firm defines a session (timezone + reset), one or more products
(rule sets + phase lifecycles), commission model, and symbol policy.

This module contains pure data types only — no YAML loader, no rule parser,
no runtime coupling. The YAML-backed registry is built on top of these in
P0.2 (``FirmRegistry``).

See ``docs/epic-9-context.md`` for the broader architectural decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..rules.base_rule import BaseRule

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a read-only view over a defensive copy of ``value``.

    Prevents both external mutation of the original dict and mutation
    through the frozen dataclass's field.
    """
    return MappingProxyType(dict(value))


class ResetAnchor(str, Enum):
    """Reference point a session uses for daily reset."""

    MIDNIGHT = "midnight"
    MARKET_CLOSE = "market_close"


class InstrumentClass(str, Enum):
    """Top-level instrument category a firm operates on."""

    FOREX_CFD = "forex_cfd"
    FUTURES = "futures"


class DrawdownMethod(str, Enum):
    """How max drawdown is measured for a product."""

    BALANCE_BASED = "balance_based"
    EQUITY_PEAK = "equity_peak"


@dataclass(frozen=True)
class SessionConfig:
    """Trading session timing used for daily reset."""

    timezone: str
    reset_time: str
    reset_anchor: ResetAnchor = ResetAnchor.MIDNIGHT

    def __post_init__(self) -> None:
        if not self.timezone:
            raise ValueError("SessionConfig.timezone must be non-empty")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"SessionConfig.timezone {self.timezone!r} is not a recognised IANA zone"
            ) from exc
        if not _TIME_RE.match(self.reset_time):
            raise ValueError(
                f"SessionConfig.reset_time must be HH:MM (00:00–23:59), got {self.reset_time!r}"
            )


@dataclass(frozen=True)
class CommissionProfile:
    """Per-firm commission and cost model (used by backtest for parity)."""

    per_lot_usd: float = 0.0
    spread_pips: Mapping[str, float] = field(default_factory=dict)
    swap_long_pips: Mapping[str, float] = field(default_factory=dict)
    swap_short_pips: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.per_lot_usd < 0:
            raise ValueError(
                f"CommissionProfile.per_lot_usd must be >= 0, got {self.per_lot_usd}"
            )
        object.__setattr__(self, "spread_pips", _freeze_mapping(self.spread_pips))
        object.__setattr__(self, "swap_long_pips", _freeze_mapping(self.swap_long_pips))
        object.__setattr__(self, "swap_short_pips", _freeze_mapping(self.swap_short_pips))


@dataclass(frozen=True)
class SymbolPolicy:
    """Symbol allow/disallow policy for a product."""

    allowed_symbols: tuple[str, ...] = ()
    disallowed_symbols: tuple[str, ...] = ()
    max_leverage: float | None = None

    def __post_init__(self) -> None:
        overlap = set(self.allowed_symbols) & set(self.disallowed_symbols)
        if overlap:
            raise ValueError(
                f"SymbolPolicy: symbols overlap between allowed and disallowed: {sorted(overlap)}"
            )
        if self.max_leverage is not None and self.max_leverage <= 0:
            raise ValueError(
                f"SymbolPolicy.max_leverage must be > 0 or None, got {self.max_leverage}"
            )


@dataclass(frozen=True)
class ScalingPolicy:
    """Opaque scaling plan (YAML-only; logic deferred)."""

    policy_id: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("ScalingPolicy.policy_id must be non-empty")
        object.__setattr__(self, "params", _freeze_mapping(self.params))


@dataclass(frozen=True)
class AccountPhase:
    """One phase in a product's lifecycle (e.g., Evaluation → Funded)."""

    phase_id: str
    name: str
    rule_overrides: Mapping[str, Any] = field(default_factory=dict)
    allowed_transitions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.phase_id:
            raise ValueError("AccountPhase.phase_id must be non-empty")
        if not self.name:
            raise ValueError("AccountPhase.name must be non-empty")
        object.__setattr__(self, "rule_overrides", _freeze_mapping(self.rule_overrides))


@dataclass(frozen=True)
class ReportTemplate:
    """Firm-specific report template reference."""

    template_id: str
    variables: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("ReportTemplate.template_id must be non-empty")
        object.__setattr__(self, "variables", _freeze_mapping(self.variables))


@dataclass(frozen=True)
class AccountProduct:
    """A product offered by a firm (e.g., FTMO Challenge, The5ers Bootstrap).

    ``rules`` carries the instantiated baseline used directly when an account
    has no overrides. ``rule_specs`` retains the parser-shaped dicts behind
    those rules so per-account / per-phase overrides can be merged at the
    spec level and re-parsed (see ``rules/override_merger.py``). The two are
    aligned by index.
    """

    product_id: str
    name: str
    rules: Sequence[BaseRule]
    phases: Sequence[AccountPhase]
    rule_specs: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    drawdown_method: DrawdownMethod = DrawdownMethod.BALANCE_BASED
    commission_overrides: CommissionProfile | None = None
    symbol_overrides: SymbolPolicy | None = None
    scaling_policy: ScalingPolicy | None = None

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("AccountProduct.product_id must be non-empty")
        if not self.name:
            raise ValueError("AccountProduct.name must be non-empty")
        if not self.phases:
            raise ValueError(
                f"AccountProduct {self.product_id!r} must declare at least one phase"
            )
        if not self.rules:
            raise ValueError(
                f"AccountProduct {self.product_id!r} must declare at least one rule"
            )

        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(self, "phases", tuple(self.phases))
        # rule_specs is optional for back-compat with hand-built test products;
        # FirmRegistry always populates it. When present, freeze each entry so
        # the override merger cannot accidentally mutate stored baselines.
        if self.rule_specs:
            object.__setattr__(
                self,
                "rule_specs",
                tuple(_freeze_mapping(spec) for spec in self.rule_specs),
            )
        else:
            object.__setattr__(self, "rule_specs", ())

        phase_ids = [p.phase_id for p in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError(
                f"AccountProduct {self.product_id!r} has duplicate phase_ids: {phase_ids}"
            )

        valid_phase_ids = set(phase_ids)
        for phase in self.phases:
            for target in phase.allowed_transitions:
                if target not in valid_phase_ids:
                    raise ValueError(
                        f"AccountProduct {self.product_id!r} phase {phase.phase_id!r}: "
                        f"allowed_transitions references unknown phase {target!r}"
                    )

    def get_phase(self, phase_id: str) -> AccountPhase:
        """Return the phase with the given id.

        Raises:
            KeyError: if no matching phase exists.
        """
        for phase in self.phases:
            if phase.phase_id == phase_id:
                return phase
        raise KeyError(
            f"AccountProduct {self.product_id!r} has no phase {phase_id!r}. "
            f"Available: {sorted(p.phase_id for p in self.phases)}"
        )


_REGIME_TIMEFRAMES: frozenset[str] = frozenset({"M5", "M15"})


@dataclass(frozen=True)
class RegimeThresholds:
    """Decision thresholds consumed by ``RuleBasedRegimeClassifier`` (Epic 11).

    Pure value type: same threshold values in → same classifier output. Lives
    on :class:`InstrumentRegimeConfig` so each instrument can be calibrated
    independently while sharing the upstream pipeline.
    """

    adx_trend_min: float
    adx_strong_trend: float
    bb_width_low_pct: float
    bb_width_high_pct: float
    realized_vol_high: float
    ema_slope_trend_threshold: float

    def __post_init__(self) -> None:
        if self.adx_trend_min <= 0:
            raise ValueError(
                f"RegimeThresholds.adx_trend_min must be > 0, got {self.adx_trend_min}"
            )
        if self.adx_strong_trend <= 0:
            raise ValueError(
                "RegimeThresholds.adx_strong_trend must be > 0, "
                f"got {self.adx_strong_trend}"
            )
        if self.adx_strong_trend < self.adx_trend_min:
            raise ValueError(
                "RegimeThresholds.adx_strong_trend must be >= adx_trend_min "
                f"({self.adx_strong_trend} < {self.adx_trend_min})"
            )
        if not 0.0 <= self.bb_width_low_pct <= 1.0:
            raise ValueError(
                "RegimeThresholds.bb_width_low_pct must be in [0, 1], "
                f"got {self.bb_width_low_pct}"
            )
        if not 0.0 <= self.bb_width_high_pct <= 1.0:
            raise ValueError(
                "RegimeThresholds.bb_width_high_pct must be in [0, 1], "
                f"got {self.bb_width_high_pct}"
            )
        if self.bb_width_high_pct <= self.bb_width_low_pct:
            raise ValueError(
                "RegimeThresholds.bb_width_high_pct must be > bb_width_low_pct "
                f"({self.bb_width_high_pct} <= {self.bb_width_low_pct})"
            )
        if self.realized_vol_high <= 0:
            raise ValueError(
                "RegimeThresholds.realized_vol_high must be > 0, "
                f"got {self.realized_vol_high}"
            )
        if self.ema_slope_trend_threshold <= 0:
            raise ValueError(
                "RegimeThresholds.ema_slope_trend_threshold must be > 0 "
                f"(applied to |slope|), got {self.ema_slope_trend_threshold}"
            )


@dataclass(frozen=True)
class InstrumentRegimeConfig:
    """Per-instrument regime-classifier wiring (Epic 11).

    Bundles the indicator parameters used to construct ``FeatureExtractor``
    plus the :class:`RegimeThresholds` consumed by the classifier. One
    instance per (firm, instrument) pair lives inside :class:`RegimeConfig`.
    """

    timeframe: str
    thresholds: RegimeThresholds
    adx_period: int
    bb_period: int
    bb_stddev: float
    bb_baseline_window: int
    realized_vol_window: int
    ema_slope_period: int
    ema_slope_lookback: int

    def __post_init__(self) -> None:
        if self.timeframe not in _REGIME_TIMEFRAMES:
            raise ValueError(
                "InstrumentRegimeConfig.timeframe must be one of "
                f"{sorted(_REGIME_TIMEFRAMES)}, got {self.timeframe!r}"
            )
        for field_name in (
            "adx_period",
            "bb_period",
            "bb_baseline_window",
            "realized_vol_window",
            "ema_slope_period",
            "ema_slope_lookback",
        ):
            value = getattr(self, field_name)
            if value <= 0:
                raise ValueError(
                    f"InstrumentRegimeConfig.{field_name} must be > 0, got {value}"
                )
        if self.bb_stddev <= 0:
            raise ValueError(
                f"InstrumentRegimeConfig.bb_stddev must be > 0, got {self.bb_stddev}"
            )
        if self.bb_baseline_window < self.bb_period:
            raise ValueError(
                "InstrumentRegimeConfig.bb_baseline_window must be >= bb_period "
                f"({self.bb_baseline_window} < {self.bb_period})"
            )


@dataclass(frozen=True)
class RegimeConfig:
    """Top-level regime-classifier block on a firm profile (Epic 11).

    Loaded from the optional ``regime_classifier:`` block in a firm YAML.
    ``enabled=False`` (the default) means the bootstrap returns the plain
    :class:`StrategyDataRouter` and no classifier overhead is incurred.
    """

    enabled: bool
    confirmation_bars: int
    warmup_bars: int
    feature_window: int
    instruments: Mapping[str, InstrumentRegimeConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confirmation_bars <= 0:
            raise ValueError(
                "RegimeConfig.confirmation_bars must be > 0, "
                f"got {self.confirmation_bars}"
            )
        if self.warmup_bars <= 0:
            raise ValueError(
                f"RegimeConfig.warmup_bars must be > 0, got {self.warmup_bars}"
            )
        if self.feature_window <= 0:
            raise ValueError(
                f"RegimeConfig.feature_window must be > 0, got {self.feature_window}"
            )
        if self.warmup_bars > self.feature_window:
            raise ValueError(
                "RegimeConfig.warmup_bars must be <= feature_window "
                f"({self.warmup_bars} > {self.feature_window})"
            )
        if self.enabled and not self.instruments:
            raise ValueError(
                "RegimeConfig.instruments must be non-empty when enabled=True"
            )
        for symbol, instr in self.instruments.items():
            if self.feature_window < instr.bb_baseline_window:
                raise ValueError(
                    f"RegimeConfig.feature_window must be >= "
                    f"instruments[{symbol!r}].bb_baseline_window "
                    f"({self.feature_window} < {instr.bb_baseline_window})"
                )
        object.__setattr__(self, "instruments", _freeze_mapping(self.instruments))

    def get_instrument(self, symbol: str) -> InstrumentRegimeConfig:
        """Return the per-instrument config for ``symbol``.

        Raises:
            KeyError: if ``symbol`` is not configured.
        """
        cfg = self.instruments.get(symbol)
        if cfg is None:
            raise KeyError(
                f"RegimeConfig has no instrument {symbol!r}. "
                f"Available: {sorted(self.instruments)}"
            )
        return cfg


@dataclass(frozen=True)
class FirmProfile:
    """Top-level profile of a prop firm.

    Engine core depends on this shape; concrete firms are produced by the
    YAML-backed registry (P0.2) or constructed directly for tests.
    """

    firm_id: str
    name: str
    version: str
    session: SessionConfig
    products: Mapping[str, AccountProduct]
    instrument_class: InstrumentClass = InstrumentClass.FOREX_CFD
    commission: CommissionProfile | None = None
    report_template: ReportTemplate | None = None
    notification_template: Mapping[str, Any] = field(default_factory=dict)
    regime_classifier: RegimeConfig | None = None
    # Epic 13 story 13.8 — per-strategy parameter overrides keyed by
    # strategy registry id (``supertrend``, ``donchian_breakout``, etc.).
    # Schema-free at this layer: each value is the raw kwargs dict the
    # operator wants merged into the strategy config at job-assembly
    # time. Strict-typed validation happens when the strategy config
    # itself runs ``__post_init__`` (story 13.2 invariants), so the
    # firm profile only carries the dict and lets the consumer merge.
    strategy_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.firm_id:
            raise ValueError("FirmProfile.firm_id must be non-empty")
        if not self.name:
            raise ValueError("FirmProfile.name must be non-empty")
        if not self.version:
            raise ValueError("FirmProfile.version must be non-empty")
        if not self.products:
            raise ValueError(
                f"FirmProfile {self.firm_id!r} must declare at least one product"
            )
        owned_products = dict(self.products)
        for key, product in owned_products.items():
            if product.product_id != key:
                raise ValueError(
                    f"FirmProfile {self.firm_id!r}: products[{key!r}].product_id "
                    f"= {product.product_id!r} mismatches dict key"
                )
        object.__setattr__(self, "products", MappingProxyType(owned_products))
        object.__setattr__(
            self, "notification_template", _freeze_mapping(self.notification_template)
        )
        # Freeze BOTH the outer dict (MappingProxyType) and each inner
        # value (_freeze_mapping makes a fresh copy then wraps it).
        # The dict(v) defensive copy inside _freeze_mapping matters:
        # Pydantic hands us mutable dicts and a future caller could
        # otherwise mutate cached kwargs (e.g. add a key before passing
        # to the strategy factory) and corrupt the registry's view.
        frozen_overrides = MappingProxyType(
            {k: _freeze_mapping(v) for k, v in dict(self.strategy_overrides).items()}
        )
        object.__setattr__(self, "strategy_overrides", frozen_overrides)

    def get_product(self, product_id: str) -> AccountProduct:
        """Return the product with the given id.

        Raises:
            KeyError: if no matching product exists.
        """
        product = self.products.get(product_id)
        if product is None:
            raise KeyError(
                f"FirmProfile {self.firm_id!r} has no product {product_id!r}. "
                f"Available: {sorted(self.products)}"
            )
        return product


__all__ = [
    "AccountPhase",
    "AccountProduct",
    "CommissionProfile",
    "DrawdownMethod",
    "FirmProfile",
    "InstrumentClass",
    "InstrumentRegimeConfig",
    "RegimeConfig",
    "RegimeThresholds",
    "ReportTemplate",
    "ResetAnchor",
    "ScalingPolicy",
    "SessionConfig",
    "SymbolPolicy",
]
