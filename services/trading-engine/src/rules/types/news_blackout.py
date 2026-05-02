"""News-blackout rule (story 10.8 / D7#5).

FTMO and most prop firms forbid trading inside a tight window around
high-impact news (NFP, FOMC, CPI). The rule is configured per firm
via YAML — typical FTMO setting is ±5 minutes around High events
across all symbols. Lower-impact events are ignored by default.

Context keys consulted:

- ``now``: tz-aware ``datetime`` of the validation moment. The rule
  falls back to ``datetime.now(timezone.utc)`` when the caller omits
  it (production hot path), which keeps the surface tolerant for
  ad-hoc calls but loses test reproducibility unless ``now`` is
  injected explicitly.
- ``symbol``: trading symbol of the order. Used both for the rule's
  optional ``symbols_filter`` (account-level scope) and to match
  events that carry an explicit symbol set.

The :class:`EventIndex` itself is **not** in the context. It comes
from the :class:`EconomicCalendarService` snapshot; the rule
constructor accepts a ``snapshot_provider`` callable so a single
service refresh atomically swaps in the new index for every account's
rule instance without rebuilding rule objects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar

from ...calendar.calendar_models import HIGH_IMPACT, EventIndex
from ..base_rule import RuleAction, RuleResult

logger = logging.getLogger(__name__)


SnapshotProvider = Callable[[], "EventIndex | None"]


@dataclass(frozen=True)
class NewsBlackoutConfig:
    """Per-account configuration for :class:`NewsBlackoutRule`.

    Attributes:
        blackout_minutes_before: Minutes before each event the
            blackout starts. Default 5 — matches FTMO eval guidance.
        blackout_minutes_after: Minutes after each event the blackout
            ends.
        impact_levels: Lowercased event impact levels that trigger the
            blackout. Default ``{"high"}``.
        symbols_filter: When set, the rule only fires when the order's
            symbol is in this set. ``None`` ⇒ all symbols.
    """

    blackout_minutes_before: int = 5
    blackout_minutes_after: int = 5
    impact_levels: frozenset[str] = field(default_factory=lambda: HIGH_IMPACT)
    symbols_filter: frozenset[str] | None = None


class NewsBlackoutRule:
    """Block orders inside a window around high-impact news events."""

    rule_type: ClassVar[str] = "news_blackout"
    # After daily-loss / max-drawdown / position-size critical rules,
    # before informational ones. Aligned with ConsistencyRule (5).
    priority: ClassVar[int] = 6

    def __init__(
        self,
        blackout_minutes_before: int = 5,
        blackout_minutes_after: int = 5,
        impact_levels: list[str] | None = None,
        symbols_filter: list[str] | None = None,
        snapshot_provider: SnapshotProvider | None = None,
        action: str = "block_trading",  # YAML compat — rule always blocks
        **kwargs: Any,
    ) -> None:
        if blackout_minutes_before < 0 or blackout_minutes_after < 0:
            raise ValueError(
                "NewsBlackoutRule blackout windows must be non-negative "
                f"(before={blackout_minutes_before}, "
                f"after={blackout_minutes_after})"
            )

        if impact_levels is None:
            impacts = HIGH_IMPACT
        else:
            impacts = frozenset(level.strip().lower() for level in impact_levels)
            if not impacts:
                raise ValueError(
                    "NewsBlackoutRule.impact_levels must list at least "
                    "one impact level"
                )

        symbols: frozenset[str] | None = None
        if symbols_filter:
            symbols = frozenset(s.strip().upper() for s in symbols_filter if s.strip())
            if not symbols:
                symbols = None

        self.config = NewsBlackoutConfig(
            blackout_minutes_before=blackout_minutes_before,
            blackout_minutes_after=blackout_minutes_after,
            impact_levels=impacts,
            symbols_filter=symbols,
        )
        self._snapshot_provider: SnapshotProvider | None = snapshot_provider

    @property
    def name(self) -> str:
        levels = "/".join(sorted(self.config.impact_levels))
        return (
            f"News Blackout {levels} "
            f"±{self.config.blackout_minutes_before}/"
            f"{self.config.blackout_minutes_after}m"
        )

    def attach_snapshot_provider(self, provider: SnapshotProvider) -> None:
        """Late-bind the snapshot provider.

        :class:`RuleParser` builds the rule from YAML and does not know
        about the calendar service. The orchestrator binds the live
        provider after construction.
        """
        self._snapshot_provider = provider

    # ----- BaseRule protocol ----------------------------------------------

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Block when ``now`` is inside a blackout window for ``symbol``."""
        symbol = str(context.get("symbol") or "").strip()

        if (
            self.config.symbols_filter is not None
            and symbol.upper() not in self.config.symbols_filter
        ):
            # Out of scope — blackout doesn't apply to this account / symbol.
            return RuleResult(action=RuleAction.ALLOW)

        if self._snapshot_provider is None:
            # Misconfiguration: rule on the account but no calendar
            # service wired. Fail open with a WARN — the spec calls this
            # the "operational responsibility" mode (R5 in the epic
            # context).
            logger.warning(
                "NewsBlackoutRule has no snapshot_provider — failing open"
            )
            return RuleResult(
                action=RuleAction.WARN,
                message="News calendar unavailable — blackout cannot be enforced",
                metadata={
                    "rule_type": self.rule_type,
                    "snapshot_available": False,
                },
            )

        snapshot = self._snapshot_provider()
        if snapshot is None or len(snapshot) == 0:
            return RuleResult(
                action=RuleAction.WARN,
                message="News calendar empty — blackout cannot be enforced",
                metadata={
                    "rule_type": self.rule_type,
                    "snapshot_available": False,
                },
            )

        now = self._resolve_now(context)
        active = snapshot.active_events_at(
            now,
            minutes_before=self.config.blackout_minutes_before,
            minutes_after=self.config.blackout_minutes_after,
            impact_levels=self.config.impact_levels,
            symbol=symbol or None,
        )

        if active:
            event = active[0]  # most-relevant for the message
            minutes_to_event = (event.start - now).total_seconds() / 60.0
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"News blackout: {event.title} ({event.country}) "
                    f"in {minutes_to_event:+.1f} min"
                ),
                metadata={
                    "rule_type": self.rule_type,
                    "event_title": event.title,
                    "event_country": event.country,
                    "event_start": event.start.isoformat(),
                    "event_impact": event.impact,
                    "active_event_count": len(active),
                },
            )

        return RuleResult(action=RuleAction.ALLOW)

    def get_current_value(self, context: dict[str, Any]) -> float:
        """How many active blackout events at ``now`` (informational)."""
        if self._snapshot_provider is None:
            return 0.0
        snapshot = self._snapshot_provider()
        if snapshot is None:
            return 0.0
        now = self._resolve_now(context)
        symbol = str(context.get("symbol") or "").strip() or None
        return float(
            len(
                snapshot.active_events_at(
                    now,
                    minutes_before=self.config.blackout_minutes_before,
                    minutes_after=self.config.blackout_minutes_after,
                    impact_levels=self.config.impact_levels,
                    symbol=symbol,
                )
            )
        )

    def get_threshold(self) -> float:
        """Threshold = 0 active events. Anything > 0 blocks."""
        return 0.0

    def get_warning_thresholds(self) -> list[float]:
        """No warn-ladder — the rule is binary block/allow."""
        return []

    # ----- Internals ------------------------------------------------------

    @staticmethod
    def _resolve_now(context: dict[str, Any]) -> datetime:
        raw = context.get("now")
        if isinstance(raw, datetime):
            if raw.tzinfo is None:
                return raw.replace(tzinfo=timezone.utc)
            return raw
        return datetime.now(timezone.utc)
