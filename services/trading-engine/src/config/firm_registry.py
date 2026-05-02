"""Firm registry — YAML-backed loader for :class:`FirmProfile` (Epic 9 P0.2).

Loads every ``*.yaml`` under a firms directory, validates the schema with
pydantic, and constructs the frozen :class:`FirmProfile` domain objects from
P0.1. Rule lists inside each product are parsed via the existing
:class:`RuleParser` so every rule type already supported by the engine keeps
working without code changes.

The registry is lazy: call :meth:`FirmRegistry.load` once at startup; after
that, :meth:`FirmRegistry.get` and :meth:`FirmRegistry.resolve` are cheap.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..rules.parser import RuleParseError, RuleParser
from .firm_profile import (
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FirmRegistryError(Exception):
    """Base class for registry errors."""


class FirmProfileLoadError(FirmRegistryError):
    """Raised when a firm YAML cannot be parsed or validated."""


class FirmNotFoundError(FirmRegistryError, KeyError):
    """Raised when ``get`` / ``resolve`` is called with an unknown ``firm_id``."""

    def __init__(self, message: str):
        Exception.__init__(self, message)


class ProductNotFoundError(FirmRegistryError, KeyError):
    """Raised by :meth:`FirmRegistry.resolve` for an unknown ``product_id``."""

    def __init__(self, message: str):
        Exception.__init__(self, message)


class PhaseNotFoundError(FirmRegistryError, KeyError):
    """Raised by :meth:`FirmRegistry.resolve` for an unknown ``phase_id``."""

    def __init__(self, message: str):
        Exception.__init__(self, message)


class FirmRegistryNotConfiguredError(FirmRegistryError):
    """Raised when a firm-bound account is processed but no registry was wired up."""


# ---------------------------------------------------------------------------
# YAML schema (pydantic v2)
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SessionSchema(_StrictModel):
    timezone: str
    reset_time: str
    reset_anchor: ResetAnchor = ResetAnchor.MIDNIGHT


class _CommissionSchema(_StrictModel):
    per_lot_usd: float = 0.0
    spread_pips: dict[str, float] = Field(default_factory=dict)
    swap_long_pips: dict[str, float] = Field(default_factory=dict)
    swap_short_pips: dict[str, float] = Field(default_factory=dict)


class _SymbolPolicySchema(_StrictModel):
    allowed_symbols: list[str] = Field(default_factory=list)
    disallowed_symbols: list[str] = Field(default_factory=list)
    max_leverage: float | None = None


class _ScalingPolicySchema(_StrictModel):
    policy_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class _ReportTemplateSchema(_StrictModel):
    template_id: str
    variables: dict[str, Any] = Field(default_factory=dict)


class _PhaseSchema(_StrictModel):
    phase_id: str
    name: str
    # rule_overrides keys are validated against the resolved product
    # baseline at account-binding time by ``rules.override_merger``.
    # Storing as raw dict here keeps the YAML schema layer simple and
    # delegates the cross-rule semantic check to merge time.
    rule_overrides: dict[str, Any] = Field(default_factory=dict)
    allowed_transitions: list[str] = Field(default_factory=list)


class _ProductSchema(_StrictModel):
    product_id: str
    name: str
    rules: list[dict[str, Any]]
    phases: list[_PhaseSchema]
    drawdown_method: DrawdownMethod = DrawdownMethod.BALANCE_BASED
    commission_overrides: _CommissionSchema | None = None
    symbol_overrides: _SymbolPolicySchema | None = None
    scaling_policy: _ScalingPolicySchema | None = None


class _RegimeThresholdsSchema(_StrictModel):
    adx_trend_min: float
    adx_strong_trend: float
    bb_width_low_pct: float
    bb_width_high_pct: float
    realized_vol_high: float
    ema_slope_trend_threshold: float


class _InstrumentRegimeConfigSchema(_StrictModel):
    timeframe: str
    thresholds: _RegimeThresholdsSchema
    adx_period: int
    bb_period: int
    bb_stddev: float
    bb_baseline_window: int
    realized_vol_window: int
    ema_slope_period: int
    ema_slope_lookback: int


class _RegimeConfigSchema(_StrictModel):
    enabled: bool = False
    confirmation_bars: int
    warmup_bars: int
    feature_window: int
    instruments: dict[str, _InstrumentRegimeConfigSchema] = Field(default_factory=dict)


class _FirmSchema(_StrictModel):
    firm_id: str
    name: str
    version: str
    session: _SessionSchema
    products: dict[str, _ProductSchema]
    instrument_class: InstrumentClass = InstrumentClass.FOREX_CFD
    commission: _CommissionSchema | None = None
    report_template: _ReportTemplateSchema | None = None
    notification_template: dict[str, Any] = Field(default_factory=dict)
    regime_classifier: _RegimeConfigSchema | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class FirmRegistry:
    """Loads and caches :class:`FirmProfile` instances from a firms directory."""

    def __init__(self, firms_dir: Path, rule_parser: RuleParser | None = None):
        self._firms_dir = Path(firms_dir)
        self._parser = rule_parser or RuleParser()
        self._firms: dict[str, FirmProfile] = {}
        self._loaded = False

    def load(self) -> None:
        """Scan ``firms_dir`` for ``*.yaml`` files and load every firm.

        Idempotent: repeated calls simply re-scan and replace the cache.

        Raises:
            FirmProfileLoadError: if the directory is missing, empty, or any
                YAML fails parsing / schema / conversion.
        """
        if not self._firms_dir.exists():
            raise FirmProfileLoadError(
                f"firms_dir does not exist: {self._firms_dir}"
            )
        if not self._firms_dir.is_dir():
            raise FirmProfileLoadError(
                f"firms_dir is not a directory: {self._firms_dir}"
            )

        yaml_files = sorted(self._firms_dir.glob("*.yaml"))
        if not yaml_files:
            raise FirmProfileLoadError(
                f"no firm YAMLs found in {self._firms_dir}"
            )

        firms: dict[str, FirmProfile] = {}
        for yaml_file in yaml_files:
            firm = self._load_one(yaml_file)
            if firm.firm_id in firms:
                raise FirmProfileLoadError(
                    f"duplicate firm_id {firm.firm_id!r} in {yaml_file} "
                    f"(already loaded from another file)"
                )
            firms[firm.firm_id] = firm

        self._firms = firms
        self._loaded = True
        logger.info(
            "FirmRegistry loaded %d firms from %s: %s",
            len(firms),
            self._firms_dir,
            ", ".join(sorted(firms)),
        )

    def get(self, firm_id: str) -> FirmProfile:
        """Return the profile for ``firm_id``.

        Raises:
            FirmRegistryError: if :meth:`load` has not been called yet.
            FirmNotFoundError: if ``firm_id`` is not registered.
        """
        self._ensure_loaded()
        if firm_id not in self._firms:
            raise FirmNotFoundError(
                f"firm_id {firm_id!r} not in registry. "
                f"Available: {sorted(self._firms)}"
            )
        return self._firms[firm_id]

    def list_firms(self) -> list[str]:
        """Return the list of registered ``firm_id`` values (sorted)."""
        self._ensure_loaded()
        return sorted(self._firms)

    def resolve(
        self, firm_id: str, product_id: str, phase_id: str
    ) -> tuple[FirmProfile, AccountProduct, AccountPhase]:
        """Look up ``(firm, product, phase)`` in one call.

        All three not-found cases surface as subclasses of
        :class:`FirmRegistryError` (they also inherit from :class:`KeyError`
        for backwards-compat), so callers only need one ``except`` clause.

        Raises:
            FirmNotFoundError: if ``firm_id`` is unknown.
            ProductNotFoundError: if ``product_id`` is unknown.
            PhaseNotFoundError: if ``phase_id`` is unknown.
        """
        firm = self.get(firm_id)
        try:
            product = firm.get_product(product_id)
        except KeyError as exc:
            raise ProductNotFoundError(str(exc).strip("'\"")) from exc
        try:
            phase = product.get_phase(phase_id)
        except KeyError as exc:
            raise PhaseNotFoundError(str(exc).strip("'\"")) from exc
        return firm, product, phase

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise FirmRegistryError(
                "FirmRegistry not loaded — call load() first"
            )

    def _load_one(self, yaml_file: Path) -> FirmProfile:
        try:
            raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise FirmProfileLoadError(
                f"{yaml_file}: YAML syntax error: {exc}"
            ) from exc

        if raw is None:
            raise FirmProfileLoadError(f"{yaml_file}: empty YAML file")

        try:
            schema = _FirmSchema.model_validate(raw)
        except ValidationError as exc:
            raise FirmProfileLoadError(
                f"{yaml_file}: schema validation failed\n{exc}"
            ) from exc

        try:
            return self._schema_to_profile(schema)
        except (ValueError, RuleParseError) as exc:
            raise FirmProfileLoadError(f"{yaml_file}: {exc}") from exc

    def _schema_to_profile(self, schema: _FirmSchema) -> FirmProfile:
        products = {
            pid: self._schema_to_product(p)
            for pid, p in schema.products.items()
        }
        return FirmProfile(
            firm_id=schema.firm_id,
            name=schema.name,
            version=schema.version,
            session=SessionConfig(
                timezone=schema.session.timezone,
                reset_time=schema.session.reset_time,
                reset_anchor=schema.session.reset_anchor,
            ),
            products=products,
            instrument_class=schema.instrument_class,
            commission=_commission(schema.commission),
            report_template=_report(schema.report_template),
            notification_template=schema.notification_template,
            regime_classifier=_regime_config(schema.regime_classifier),
        )

    def _schema_to_product(self, schema: _ProductSchema) -> AccountProduct:
        # Keep the raw spec dicts aligned with the instantiated rules so the
        # P0.16 override merger can operate on the YAML-shaped dicts and
        # re-parse the merged result, instead of reaching into rule internals.
        rule_specs = tuple(dict(spec) for spec in schema.rules)
        rules = self._parser.parse_rules({"rules": list(rule_specs)})
        phases = tuple(
            AccountPhase(
                phase_id=p.phase_id,
                name=p.name,
                rule_overrides=p.rule_overrides,
                allowed_transitions=tuple(p.allowed_transitions),
            )
            for p in schema.phases
        )
        return AccountProduct(
            product_id=schema.product_id,
            name=schema.name,
            rules=tuple(rules),
            phases=phases,
            rule_specs=rule_specs,
            drawdown_method=schema.drawdown_method,
            commission_overrides=_commission(schema.commission_overrides),
            symbol_overrides=_symbol_policy(schema.symbol_overrides),
            scaling_policy=_scaling(schema.scaling_policy),
        )


# ---------------------------------------------------------------------------
# Schema → dataclass converters (module-level for clarity / testability)
# ---------------------------------------------------------------------------


def _commission(s: _CommissionSchema | None) -> CommissionProfile | None:
    if s is None:
        return None
    return CommissionProfile(
        per_lot_usd=s.per_lot_usd,
        spread_pips=dict(s.spread_pips),
        swap_long_pips=dict(s.swap_long_pips),
        swap_short_pips=dict(s.swap_short_pips),
    )


def _symbol_policy(s: _SymbolPolicySchema | None) -> SymbolPolicy | None:
    if s is None:
        return None
    return SymbolPolicy(
        allowed_symbols=tuple(s.allowed_symbols),
        disallowed_symbols=tuple(s.disallowed_symbols),
        max_leverage=s.max_leverage,
    )


def _scaling(s: _ScalingPolicySchema | None) -> ScalingPolicy | None:
    if s is None:
        return None
    return ScalingPolicy(policy_id=s.policy_id, params=dict(s.params))


def _report(s: _ReportTemplateSchema | None) -> ReportTemplate | None:
    if s is None:
        return None
    return ReportTemplate(template_id=s.template_id, variables=dict(s.variables))


def _regime_config(s: _RegimeConfigSchema | None) -> RegimeConfig | None:
    if s is None:
        return None
    instruments = {
        symbol: InstrumentRegimeConfig(
            timeframe=instr.timeframe,
            thresholds=RegimeThresholds(
                adx_trend_min=instr.thresholds.adx_trend_min,
                adx_strong_trend=instr.thresholds.adx_strong_trend,
                bb_width_low_pct=instr.thresholds.bb_width_low_pct,
                bb_width_high_pct=instr.thresholds.bb_width_high_pct,
                realized_vol_high=instr.thresholds.realized_vol_high,
                ema_slope_trend_threshold=instr.thresholds.ema_slope_trend_threshold,
            ),
            adx_period=instr.adx_period,
            bb_period=instr.bb_period,
            bb_stddev=instr.bb_stddev,
            bb_baseline_window=instr.bb_baseline_window,
            realized_vol_window=instr.realized_vol_window,
            ema_slope_period=instr.ema_slope_period,
            ema_slope_lookback=instr.ema_slope_lookback,
        )
        for symbol, instr in s.instruments.items()
    }
    return RegimeConfig(
        enabled=s.enabled,
        confirmation_bars=s.confirmation_bars,
        warmup_bars=s.warmup_bars,
        feature_window=s.feature_window,
        instruments=instruments,
    )


__all__ = [
    "FirmNotFoundError",
    "FirmProfileLoadError",
    "FirmRegistry",
    "FirmRegistryError",
    "FirmRegistryNotConfiguredError",
    "PhaseNotFoundError",
    "ProductNotFoundError",
]
