"""Per-account rolling daily-profit history (Epic 9 Phase 0, task P0.7).

Backs the :class:`ConsistencyRule` which needs a fast lookup of "sum of
positive prior days' P&L". An :class:`asyncio.Lock` is intentionally
omitted: the engine's hot path is single-threaded asyncio cooperative,
and updates happen at coarse-grained boundaries (per-trade-close,
end-of-day snapshot flush, account onboarding load).

Design:
- Per-account dict ``date → daily_pnl`` (absolute P&L in account currency).
- Precomputed ``positive_sum`` cache so ``get_positive_sum`` is O(1).
  ``record`` keeps the cache consistent on insert + replace.
- Today's value is NOT stored here — callers pass ``current_day_pnl``
  directly to the rule. The history holds COMPLETED prior days only.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


def _coerce_pnl(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


class DailyProfitHistory:
    """In-memory rolling window of completed daily P&L per account."""

    def __init__(self) -> None:
        self._history: dict[str, dict[date, float]] = {}
        self._positive_sum: dict[str, float] = {}

    # ---------------------------------------------------------------- record

    def record(self, account_id: str, day: date, pnl: Any) -> None:
        """Insert or replace a day's P&L for an account.

        Cache invariant: ``_positive_sum[account_id]`` always equals
        ``sum(v for v in _history[account_id].values() if v > 0)``.
        """
        new_value = _coerce_pnl(pnl)
        history = self._history.setdefault(account_id, {})
        old_value = history.get(day)

        history[day] = new_value
        prev_sum = self._positive_sum.get(account_id, 0.0)
        if old_value is not None and old_value > 0:
            prev_sum -= old_value
        if new_value > 0:
            prev_sum += new_value
        self._positive_sum[account_id] = prev_sum

    # ----------------------------------------------------------------- read

    def get_positive_sum(
        self, account_id: str, exclude_date: date | None = None,
    ) -> float:
        """Return Σ(positive day pnl) for ``account_id``, optionally
        excluding the contribution from ``exclude_date``.
        """
        total = self._positive_sum.get(account_id, 0.0)
        if exclude_date is not None:
            history = self._history.get(account_id)
            if history is not None:
                excluded_value = history.get(exclude_date)
                if excluded_value is not None and excluded_value > 0:
                    total -= excluded_value
        return total

    def get_history(self, account_id: str) -> dict[date, float]:
        """Return a defensive copy of the per-account history dict.

        Mutating the returned dict does not affect internal state.
        """
        return dict(self._history.get(account_id, {}))

    # ----------------------------------------------------------------- prune

    def prune(self, account_id: str, before: date) -> None:
        """Drop entries strictly earlier than ``before``.

        Recomputes the ``_positive_sum`` cache from scratch for that
        account to keep the invariant cheap to reason about.
        """
        history = self._history.get(account_id)
        if not history:
            return
        kept = {d: pnl for d, pnl in history.items() if d >= before}
        self._history[account_id] = kept
        self._positive_sum[account_id] = sum(v for v in kept.values() if v > 0)

    # -------------------------------------------------------------- DB load

    async def load_from_db(
        self,
        account_id: str,
        session_factory: "async_sessionmaker",
        lookback_days: int = 60,
    ) -> None:
        """Replace this account's history from ``account_snapshots``.

        Pulls the last ``lookback_days`` of ``daily_pnl`` from the
        TimescaleDB hypertable and rebuilds the cache.
        """
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT snapshot_date, daily_pnl "
                    "FROM account_snapshots "
                    "WHERE account_id = :account_id "
                    "AND snapshot_date >= CURRENT_DATE - :lookback "
                    "ORDER BY snapshot_date"
                ),
                {"account_id": account_id, "lookback": lookback_days},
            )
            rows = result.all()

        new_history: dict[date, float] = {}
        for row in rows:
            if row.daily_pnl is None:
                continue
            new_history[row.snapshot_date] = _coerce_pnl(row.daily_pnl)
        self._history[account_id] = new_history
        self._positive_sum[account_id] = sum(v for v in new_history.values() if v > 0)
        logger.info(
            "DailyProfitHistory: loaded %d snapshots for %s (positive sum=%.2f)",
            len(new_history), account_id, self._positive_sum[account_id],
        )
