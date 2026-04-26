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
    """A product offered by a firm (e.g., FTMO Challenge, The5ers Bootstrap)."""

    product_id: str
    name: str
    rules: Sequence[BaseRule]
    phases: Sequence[AccountPhase]
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
    "ReportTemplate",
    "ResetAnchor",
    "ScalingPolicy",
    "SessionConfig",
    "SymbolPolicy",
]
