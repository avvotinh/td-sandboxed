"""Consistency rule (Epic 9 Phase 0, task P0.7).

FTMO-style "best-day concentration" guard. The rule fires when a single
profitable day accounts for too large a share of the account's total
historical profits, e.g.::

    today_pnl / (today_pnl + sum(positive prior days)) > block_at

Real-time variant: the rule is evaluated on every order so traders see a
warning before the violation crystallises at payout time. Loss days
short-circuit to ``ALLOW`` — the rule is meaningful only when today is
profitable.

Context keys (caller / context builder must populate):
- ``current_day_pnl``: today's realised + unrealised P&L (Decimal or float)
- ``daily_profits_history``: ``dict`` keyed by date returning each PRIOR
  day's pnl. Today MUST NOT be included in this dict — it lives in
  ``current_day_pnl`` so the rule has unambiguous semantics. Negative
  and zero entries are ignored.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, ClassVar

from ..base_rule import RuleAction, RuleResult

logger = logging.getLogger(__name__)


class ConsistencyRule:
    """Per-account best-day concentration guard."""

    rule_type: ClassVar[str] = "consistency"
    # Evaluated after critical loss/drawdown rules but before informational ones.
    priority: ClassVar[int] = 5

    def __init__(
        self,
        warn_at: list[float] | None = None,
        block_at: float = 50.0,
        action: str = "block_trading",  # YAML compatibility
        **kwargs: Any,
    ) -> None:
        """Initialize ConsistencyRule.

        Args:
            warn_at: Warn thresholds (percent ratios). Defaults to
                ``[40, 45, 48]`` per FTMO playbook.
            block_at: Block threshold (percent ratio). Defaults to
                ``50.0`` (FTMO consistency rule).
            action: YAML-compatibility no-op (always blocks at threshold).
            **kwargs: Additional YAML fields ignored for forward-compat.

        Raises:
            ValueError: If ``block_at`` is not in ``(0, 100]`` or any
                ``warn_at`` value is greater than or equal to ``block_at``.
        """
        block = float(block_at)
        if not 0 < block <= 100:
            raise ValueError(
                f"ConsistencyRule.block_at must be in (0, 100], got {block}"
            )

        if warn_at is None:
            # Default warn ladder, auto-truncated to entries strictly below
            # block_at so a custom block doesn't force a custom warn list.
            warn = sorted(w for w in (40.0, 45.0, 48.0) if w < block)
            if not warn:
                logger.warning(
                    "ConsistencyRule: block_at=%.1f leaves the default warn "
                    "ladder empty. Pass an explicit warn_at to silence this.",
                    block,
                )
        else:
            warn = sorted(float(w) for w in warn_at)
            for w in warn:
                if w >= block:
                    raise ValueError(
                        f"ConsistencyRule.warn_at threshold {w} must be < block_at {block}"
                    )
        self.block_at = block
        self.warn_at = warn

    @property
    def name(self) -> str:
        return f"Consistency {self.block_at}%"

    @staticmethod
    def _coerce(value: Any) -> float:
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def _compute_ratio_percent(self, context: dict[str, Any]) -> float:
        """Return today's share of total positive profits as a percentage.

        Returns ``0.0`` for loss/zero days, for empty contexts, and for
        the **first profitable day** (no prior positive history) — FTMO
        consistency only applies once at least one prior profitable day
        exists, so blocking on day 1 would be a spurious breach.
        """
        current_day_pnl_raw = context.get("current_day_pnl", 0.0)
        try:
            current_day_pnl = self._coerce(current_day_pnl_raw)
        except (TypeError, ValueError):
            return 0.0
        if current_day_pnl <= 0:
            return 0.0

        history = context.get("daily_profits_history", {}) or {}
        sum_positive_prior = 0.0
        for value in history.values():
            try:
                v = self._coerce(value)
            except (TypeError, ValueError):
                continue
            if v > 0:
                sum_positive_prior += v

        # First profitable day → rule does not apply yet.
        if sum_positive_prior <= 0:
            return 0.0

        total = current_day_pnl + sum_positive_prior
        if total <= 0:
            return 0.0
        return (current_day_pnl / total) * 100.0

    def validate(self, context: dict[str, Any]) -> RuleResult:
        ratio_percent = self._compute_ratio_percent(context)

        # Loss day or empty data → rule does not apply
        if ratio_percent <= 0:
            return RuleResult(
                action=RuleAction.ALLOW,
                current_value=0.0,
                threshold_value=self.block_at,
            )

        if ratio_percent >= self.block_at:
            logger.warning(
                "Consistency BLOCKED: today is %.2f%% of total profits "
                "(threshold %.2f%%)",
                ratio_percent, self.block_at,
            )
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"Today contributes {ratio_percent:.2f}% of total "
                    f"profits, exceeding the {self.block_at}% consistency limit"
                ),
                current_value=ratio_percent,
                threshold_value=self.block_at,
                metadata={
                    "rule_type": self.rule_type,
                    "ratio_percent": ratio_percent,
                    "block_at": self.block_at,
                },
            )

        for warn_threshold in sorted(self.warn_at, reverse=True):
            if ratio_percent >= warn_threshold:
                logger.warning(
                    "Consistency WARNING: today is %.2f%% (warn at %.1f%%, "
                    "block at %.1f%%)",
                    ratio_percent, warn_threshold, self.block_at,
                )
                return RuleResult(
                    action=RuleAction.WARN,
                    message=(
                        f"Today contributes {ratio_percent:.2f}% of total "
                        f"profits — approaching {self.block_at}% consistency limit"
                    ),
                    current_value=ratio_percent,
                    threshold_value=self.block_at,
                    metadata={
                        "rule_type": self.rule_type,
                        "ratio_percent": ratio_percent,
                        "warn_threshold": warn_threshold,
                        "block_at": self.block_at,
                    },
                )

        return RuleResult(
            action=RuleAction.ALLOW,
            current_value=ratio_percent,
            threshold_value=self.block_at,
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        return self._compute_ratio_percent(context)

    def get_threshold(self) -> float:
        return self.block_at

    def get_warning_thresholds(self) -> list[float]:
        return list(self.warn_at)

    def __repr__(self) -> str:
        return (
            f"ConsistencyRule(block_at={self.block_at}%, "
            f"warn_at={self.warn_at})"
        )
