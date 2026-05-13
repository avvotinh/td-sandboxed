"""Prop-firm compliance harness — Epic 12 Story 12.4.

Provides the rule-engine builder and breach-assertion utilities that
the validation campaign uses to verify FTMO-style compliance under
backtest. Three concerns:

1. :class:`ComplianceProfile` — declarative wrapper over the
   prop-firm rule thresholds (daily-loss / max-DD / consistency) plus
   the session timezone needed for Epic 9.5 timezone-aware reset.
2. :func:`build_compliance_rule_engine` — constructs a rule engine
   matching the live wiring: ``DailyLossLimitRule`` with the firm's
   reset-time and timezone, ``MaxDrawdownRule`` with the configured
   method, and (when enabled) the Epic 9.7 :class:`ConsistencyRule`
   driven off ``DailyProfitHistory`` carried by the actor.
3. :func:`summarize_breaches` / :func:`assert_no_breaches` — collect
   per-result breach tallies and refuse any non-allowlisted result
   that breached any rule. 12.7's experiment uses these to enforce
   "0 breach" on every strategy that passes the in-sample filter.

This module does **not** address swap accrual (Risk R4 in
``docs/epic-12-context.md``); 10.9b is tracked separately and 12.11
calls out the caveat in the runbook.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from src.backtesting.metrics.schema import PropFirmComplianceMetrics
from src.backtesting.prop_firm_preset import PropFirmPreset
from src.backtesting.result import BacktestResult, BreachEvent
from src.rules.base_rule import BaseRule
from src.rules.engine import RuleEngine
from src.rules.types.consistency import ConsistencyRule
from src.rules.types.drawdown import DailyLossLimitRule, MaxDrawdownRule


_VALID_DD_METHODS: frozenset[str] = frozenset({"equity_peak", "balance_based"})


@dataclass(frozen=True, slots=True)
class ComplianceProfile:
    """Declarative compliance config for a backtest run.

    Defaults are conservative (UTC reset, no consistency rule). The
    canonical FTMO profile is :meth:`for_ftmo`; tests and 12.7's
    wiring construct directly from a firm YAML when richer configs
    are needed.
    """

    daily_loss_pct: float
    max_drawdown_pct: float
    max_drawdown_method: str = "equity_peak"
    session_timezone: str = "UTC"
    daily_reset_time: str = "00:00"
    consistency_block_at: float | None = None
    consistency_warn_at: tuple[float, ...] | None = None
    daily_loss_warn_at: tuple[float, ...] = (70.0, 80.0, 90.0)
    max_drawdown_warn_at: tuple[float, ...] = (50.0, 70.0, 85.0)

    def __post_init__(self) -> None:
        # Guard NaN / inf separately — both pass the simple ``<= 0``
        # comparison (NaN comparisons return False; inf is positive).
        # An infinite daily-loss threshold would silently disable the
        # gate; NaN propagates undefined behaviour into the rule engine.
        if not math.isfinite(self.daily_loss_pct) or self.daily_loss_pct <= 0:
            raise ValueError(
                f"daily_loss_pct must be a positive finite number, "
                f"got {self.daily_loss_pct}"
            )
        if not math.isfinite(self.max_drawdown_pct) or self.max_drawdown_pct <= 0:
            raise ValueError(
                f"max_drawdown_pct must be a positive finite number, "
                f"got {self.max_drawdown_pct}"
            )
        if self.max_drawdown_method not in _VALID_DD_METHODS:
            raise ValueError(
                f"max_drawdown_method must be one of {sorted(_VALID_DD_METHODS)}, "
                f"got {self.max_drawdown_method!r}"
            )
        if (
            self.consistency_block_at is not None
            and not 0 < self.consistency_block_at <= 100
        ):
            raise ValueError(
                "consistency_block_at must be in (0, 100], got "
                f"{self.consistency_block_at}"
            )

    @classmethod
    def for_ftmo(cls) -> ComplianceProfile:
        """Canonical FTMO Challenge profile — matches ``configs/firms/ftmo.yaml``.

        Daily loss 5% with CET reset, max drawdown 10% balance-based
        (FTMO Challenge maximum-loss semantics — Epic 9 P0.6), and
        consistency rule blocking at 50% best-day concentration
        (Epic 9 P0.7).
        """
        return cls(
            daily_loss_pct=5.0,
            max_drawdown_pct=10.0,
            max_drawdown_method="balance_based",
            session_timezone="CET",
            daily_reset_time="00:00",
            consistency_block_at=50.0,
            consistency_warn_at=(40.0, 45.0, 48.0),
        )

    @classmethod
    def from_preset(
        cls,
        preset: PropFirmPreset,
        *,
        session_timezone: str = "UTC",
        daily_reset_time: str = "00:00",
        max_drawdown_method: str = "equity_peak",
        consistency_block_at: float | None = None,
        consistency_warn_at: tuple[float, ...] | None = None,
    ) -> ComplianceProfile:
        """Adapt the legacy :class:`PropFirmPreset` into a profile.

        ``PropFirmPreset`` does not encode session timezone or
        consistency thresholds (it predates Epic 9.5/9.7), so the
        caller supplies those explicitly. 12.7's wiring reads them
        from ``configs/firms/<firm>.yaml``.
        """
        return cls(
            daily_loss_pct=preset.daily_loss_pct,
            max_drawdown_pct=preset.max_drawdown_pct,
            max_drawdown_method=max_drawdown_method,
            session_timezone=session_timezone,
            daily_reset_time=daily_reset_time,
            consistency_block_at=consistency_block_at,
            consistency_warn_at=consistency_warn_at,
        )


def build_compliance_rule_engine(
    profile: ComplianceProfile,
    *,
    account_id: str,
) -> RuleEngine:
    """Build a :class:`RuleEngine` matching the live FTMO wiring.

    ``DailyLossLimitRule`` is constructed with the profile's
    ``session_timezone`` + ``daily_reset_time`` (Epic 9.5 timezone-aware
    reset). ``MaxDrawdownRule`` uses the configured method (Epic 9.6).
    :class:`ConsistencyRule` (Epic 9.7) is appended only when
    ``consistency_block_at`` is set — None disables the rule entirely
    rather than silently using a default.
    """
    rules: list[BaseRule] = [
        DailyLossLimitRule(
            threshold_percent=profile.daily_loss_pct,
            reset_time=profile.daily_reset_time,
            timezone=profile.session_timezone,
            warning_at=list(profile.daily_loss_warn_at),
        ),
        MaxDrawdownRule(
            threshold_percent=profile.max_drawdown_pct,
            method=profile.max_drawdown_method,
            warning_at=list(profile.max_drawdown_warn_at),
        ),
    ]
    if profile.consistency_block_at is not None:
        rules.append(
            ConsistencyRule(
                block_at=profile.consistency_block_at,
                warn_at=(
                    list(profile.consistency_warn_at)
                    if profile.consistency_warn_at is not None
                    else None
                ),
            )
        )
    return RuleEngine(account_id=account_id, rules=rules, strict_mode=True)


# --- Breach assertions -------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreachSummary:
    """Per-result tally produced by :func:`summarize_breaches`."""

    label: str
    daily_loss_breaches: int
    max_dd_breach: bool
    breach_event_count: int

    @property
    def is_clean(self) -> bool:
        return (
            self.daily_loss_breaches == 0
            and not self.max_dd_breach
            and self.breach_event_count == 0
        )


class ComplianceBreachError(Exception):
    """Raised by :func:`assert_no_breaches` when at least one result breached.

    Inherits :class:`Exception` (not :class:`AssertionError`) so a broad
    ``except AssertionError:`` in an experiment harness can never eat a
    real compliance breach. 12.7 catches this explicitly.
    """

    def __init__(
        self,
        message: str,
        *,
        summaries: tuple[BreachSummary, ...],
    ) -> None:
        super().__init__(message)
        self.summaries = summaries


def summarize_breaches(
    results: Sequence[BacktestResult],
) -> tuple[BreachSummary, ...]:
    """Collapse each result into a :class:`BreachSummary`."""
    return tuple(_summary_for(r) for r in results)


def assert_no_breaches(
    results: Sequence[BacktestResult],
    *,
    allow: Iterable[str] = (),
) -> None:
    """Refuse any non-allowlisted result that breached.

    ``allow`` is a set of strategy labels exempt from the assertion —
    use it sparingly (e.g. for a deliberately-stressed strategy that
    is documented to breach as a control). Raises
    :class:`ComplianceBreachError` containing every offending summary.
    """
    allow_set = frozenset(allow)
    summaries = summarize_breaches(results)
    offenders = tuple(
        s for s in summaries
        if not s.is_clean and s.label not in allow_set
    )
    if not offenders:
        return
    rendered = ", ".join(_format_offender(s) for s in offenders)
    raise ComplianceBreachError(
        f"compliance breaches detected: {rendered}",
        summaries=offenders,
    )


# --- Internals --------------------------------------------------------


def _summary_for(result: BacktestResult) -> BreachSummary:
    metrics_compliance: PropFirmComplianceMetrics | None = (
        result.metrics.prop_firm_compliance if result.metrics is not None else None
    )
    daily = metrics_compliance.daily_loss_breaches if metrics_compliance else 0
    max_dd = metrics_compliance.max_dd_breach if metrics_compliance else False

    breach_events: list[BreachEvent] = result.breaches or []
    return BreachSummary(
        label=_label_for(result),
        daily_loss_breaches=int(daily),
        max_dd_breach=bool(max_dd),
        breach_event_count=len(breach_events),
    )


def _label_for(result: BacktestResult) -> str:
    snapshot: dict[str, Any] | None = result.config_snapshot
    if snapshot:
        strat = snapshot.get("strategy") or {}
        if (label := strat.get("label")):
            return str(label)
    return result.strategy_name


def _format_offender(summary: BreachSummary) -> str:
    parts: list[str] = []
    if summary.daily_loss_breaches:
        parts.append(f"daily_loss={summary.daily_loss_breaches}")
    if summary.max_dd_breach:
        parts.append("max_dd_breach")
    if summary.breach_event_count:
        parts.append(f"events={summary.breach_event_count}")
    return f"{summary.label}({', '.join(parts) or 'unknown'})"
