"""Per-account / per-phase rule override merger (Epic 9 Phase 0, P0.16).

Resolves the final rule set for a firm-bound account by layering three sources::

    product baseline
        → phase overrides   (firm-controlled, trusted)
            → account overrides (ops-controlled, safety-guarded)

The architectural principle (see ``docs/epic-9-context.md`` §3) is::

    siết chặt được, không được nới lỏng

i.e. an account can only **tighten** thresholds relative to the
phase-resolved firm baseline. Phase overrides themselves are firm config
and are not guarded — phases legitimately relax informational rules
(e.g., FTMO's funded phase removes the profit target).

The merge happens on the parser-shaped dicts (``rule_specs``) so the result
can be re-parsed by :class:`~src.rules.parser.RuleParser` without reaching
into rule internals. Each rule type with a hard block threshold registers a
:class:`_GuardField` describing which key carries that threshold and which
direction means "tighter".

Rules without a guard (``profit_target``, ``min_trading_days``,
``weekly_target``) are informational and may be set freely at either layer
— there is no notion of "loosening" for an advisory rule.
"""

from __future__ import annotations

import logging
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RuleOverrideError(ValueError):
    """Raised when a rule override is malformed or would loosen a guarded rule."""


# ---------------------------------------------------------------------------
# Tightness registry
# ---------------------------------------------------------------------------


_Direction = Literal["lower_is_tighter", "higher_is_tighter"]


@dataclass(frozen=True)
class _GuardField:
    """One field on a rule whose value direction encodes "tighter"."""

    name: str
    direction: _Direction


# Per-rule-type guard fields. Only rules that BLOCK trading carry guards;
# informational rules (profit_target, min_trading_days, weekly_target)
# are intentionally absent so account overrides can adjust them freely.
_TIGHTNESS_GUARDS: dict[str, tuple[_GuardField, ...]] = {
    "daily_loss_limit": (_GuardField("threshold_percent", "lower_is_tighter"),),
    "max_drawdown": (_GuardField("threshold_percent", "lower_is_tighter"),),
    "max_position_size": (_GuardField("max_lots", "lower_is_tighter"),),
    "consistency": (_GuardField("block_at", "lower_is_tighter"),),
}


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_rule_overrides(
    product_rule_specs: Sequence[Mapping[str, Any]],
    phase_overrides: Mapping[str, Mapping[str, Any]],
    account_overrides: Mapping[str, Mapping[str, Any]],
    *,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    """Merge product baseline → phase overrides → account overrides.

    Args:
        product_rule_specs: Baseline rules from ``AccountProduct.rule_specs``,
            already validated by the YAML schema and the rule parser. Each
            entry must carry a ``"type"`` key.
        phase_overrides: ``{rule_type: {field: value, ...}}`` from
            ``AccountPhase.rule_overrides``. Applied without the
            tightness guard.
        account_overrides: ``{rule_type: {field: value, ...}}`` from
            ``RuleAssignment.rule_overrides`` /
            ``AccountConfig.rule_overrides``. Subject to the no-loosening
            guard for any ``rule_type`` registered in
            :data:`_TIGHTNESS_GUARDS`.
        account_id: Optional id used in error messages so a misconfigured
            account is identifiable in logs.

    Returns:
        A fresh list of merged spec dicts in the same order as
        ``product_rule_specs``. Suitable for ``RuleParser.parse_rules``.

    Raises:
        RuleOverrideError: if either override set names a ``rule_type``
            absent from the product baseline, references a field absent
            from the rule's baseline spec (typo guard), or — for
            ``account_overrides`` only — would loosen a guarded threshold
            relative to the phase-resolved baseline.
    """
    by_type: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for spec in product_rule_specs:
        rule_type = spec.get("type")
        if not isinstance(rule_type, str):
            raise RuleOverrideError(
                f"product rule spec missing string 'type' field: {spec!r}"
            )
        if rule_type in by_type:
            raise RuleOverrideError(
                f"product baseline declares rule_type {rule_type!r} more than once"
            )
        by_type[rule_type] = deepcopy(dict(spec))
        order.append(rule_type)

    # ----- phase layer (firm-controlled, no guard) ----------------------
    _apply_layer(
        by_type=by_type,
        overrides=phase_overrides,
        layer_label="phase",
        account_id=account_id,
        guarded=False,
    )

    # ----- account layer (guarded against loosening) --------------------
    _apply_layer(
        by_type=by_type,
        overrides=account_overrides,
        layer_label="account",
        account_id=account_id,
        guarded=True,
    )

    return [by_type[t] for t in order]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _apply_layer(
    *,
    by_type: dict[str, dict[str, Any]],
    overrides: Mapping[str, Mapping[str, Any]],
    layer_label: str,
    account_id: str | None,
    guarded: bool,
) -> None:
    """Apply one override layer in place on ``by_type``.

    ``guarded=True`` enables the no-loosening check for guarded rule types
    (used for the account layer); ``guarded=False`` skips it (used for the
    phase layer, which is firm config).
    """
    if not overrides:
        return

    account_prefix = f"account {account_id!r}: " if account_id else ""

    for rule_type, fields in overrides.items():
        if rule_type not in by_type:
            available = sorted(by_type)
            raise RuleOverrideError(
                f"{account_prefix}{layer_label} override targets unknown "
                f"rule_type {rule_type!r}. Product declares: {available}"
            )
        if not isinstance(fields, Mapping):
            raise RuleOverrideError(
                f"{account_prefix}{layer_label} override for {rule_type!r} "
                f"must be a mapping of field→value, got {type(fields).__name__}"
            )

        baseline_spec = by_type[rule_type]
        for field_name, new_value in fields.items():
            if field_name == "type":
                raise RuleOverrideError(
                    f"{account_prefix}{layer_label} override for {rule_type!r} "
                    "may not change the 'type' field"
                )
            if field_name not in baseline_spec:
                known_fields = sorted(k for k in baseline_spec if k != "type")
                raise RuleOverrideError(
                    f"{account_prefix}{layer_label} override for {rule_type!r} "
                    f"sets unknown field {field_name!r}. Known fields: "
                    f"{known_fields}"
                )

            if guarded:
                _enforce_no_loosening(
                    rule_type=rule_type,
                    field_name=field_name,
                    baseline_value=baseline_spec[field_name],
                    new_value=new_value,
                    account_prefix=account_prefix,
                )

            baseline_spec[field_name] = new_value

        logger.info(
            "%srule override applied (%s layer) on %s: %s",
            account_prefix,
            layer_label,
            rule_type,
            sorted(fields.keys()),
        )


def _enforce_no_loosening(
    *,
    rule_type: str,
    field_name: str,
    baseline_value: Any,
    new_value: Any,
    account_prefix: str,
) -> None:
    """Reject overrides on guarded fields that would loosen the rule.

    Rule types not in :data:`_TIGHTNESS_GUARDS` and fields not listed for
    a guarded type are informational from the guard's perspective and pass
    through unchecked. This is intentional: warn ladders, reset times, and
    similar dials are not block thresholds.
    """
    guards = _TIGHTNESS_GUARDS.get(rule_type)
    if not guards:
        return
    guard = next((g for g in guards if g.name == field_name), None)
    if guard is None:
        return

    try:
        baseline_num = float(baseline_value)
        new_num = float(new_value)
    except (TypeError, ValueError) as exc:
        raise RuleOverrideError(
            f"{account_prefix}override for {rule_type}.{field_name} "
            f"could not coerce baseline={baseline_value!r} or "
            f"new={new_value!r} to float for tightness comparison: {exc}"
        ) from exc

    # NaN compares False against everything, so a sneaky NaN would silently
    # pass the > / < tests and effectively bypass the guard. Reject loudly.
    if math.isnan(new_num) or math.isnan(baseline_num):
        raise RuleOverrideError(
            f"{account_prefix}override for {rule_type}.{field_name} contains "
            f"NaN (baseline={baseline_value!r}, new={new_value!r}); "
            "rule thresholds must be finite numbers"
        )

    if guard.direction == "lower_is_tighter":
        loosened = new_num > baseline_num
    else:  # higher_is_tighter
        loosened = new_num < baseline_num

    if loosened:
        raise RuleOverrideError(
            f"{account_prefix}override for {rule_type}.{field_name} would "
            f"loosen the rule: baseline={baseline_value} (after phase "
            f"merge), requested={new_value}, direction={guard.direction}. "
            "Account overrides may only tighten or maintain guarded thresholds."
        )


__all__ = [
    "RuleOverrideError",
    "merge_rule_overrides",
]
