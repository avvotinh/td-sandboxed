"""Unit tests for DailyProfitHistory service (Epic 9 Phase 0, task P0.7).

The service holds the per-account rolling window of completed-day profits
that the ``ConsistencyRule`` needs in O(1) per validation. Tests cover
in-memory operations + an isolated test for the DB-loader code path
using a mock session factory.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.snapshots.daily_profit_history import DailyProfitHistory


class TestDailyProfitHistoryRecordAndQuery:
    """Basic record / query behaviour."""

    def test_empty_history_returns_zero_sum(self):
        h = DailyProfitHistory()
        assert h.get_positive_sum("acc-1") == 0.0

    def test_record_single_positive_day(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        assert h.get_positive_sum("acc-1") == 500.0

    def test_record_negative_day_excluded_from_sum(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), -200.0)
        assert h.get_positive_sum("acc-1") == 0.0

    def test_record_zero_day_excluded_from_sum(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 0.0)
        assert h.get_positive_sum("acc-1") == 0.0

    def test_multiple_days_summed(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        h.record("acc-1", date(2026, 4, 2), -100.0)
        h.record("acc-1", date(2026, 4, 3), 300.0)
        assert h.get_positive_sum("acc-1") == 800.0

    def test_per_account_isolation(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        h.record("acc-2", date(2026, 4, 1), 1000.0)
        assert h.get_positive_sum("acc-1") == 500.0
        assert h.get_positive_sum("acc-2") == 1000.0

    def test_decimal_input_coerced(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), Decimal("250.50"))
        assert h.get_positive_sum("acc-1") == pytest.approx(250.50)

    def test_unknown_account_returns_zero(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        assert h.get_positive_sum("unknown") == 0.0


class TestDailyProfitHistoryReplace:
    """Replacing an existing entry must keep the cache consistent."""

    def test_replace_positive_with_positive(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        h.record("acc-1", date(2026, 4, 1), 300.0)
        assert h.get_positive_sum("acc-1") == 300.0

    def test_replace_positive_with_negative(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        h.record("acc-1", date(2026, 4, 1), -100.0)
        assert h.get_positive_sum("acc-1") == 0.0

    def test_replace_negative_with_positive(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), -100.0)
        h.record("acc-1", date(2026, 4, 1), 400.0)
        assert h.get_positive_sum("acc-1") == 400.0


class TestDailyProfitHistoryExcludeDate:
    """``exclude_date`` is the hot path used by ConsistencyRule live."""

    def test_exclude_date_subtracts_that_days_positive_pnl(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        h.record("acc-1", date(2026, 4, 2), 300.0)
        assert h.get_positive_sum("acc-1", exclude_date=date(2026, 4, 1)) == 300.0
        # Original sum unchanged
        assert h.get_positive_sum("acc-1") == 800.0

    def test_exclude_date_with_negative_value_does_not_alter_sum(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), -200.0)
        h.record("acc-1", date(2026, 4, 2), 500.0)
        # exclude a loss day → sum unchanged
        assert h.get_positive_sum("acc-1", exclude_date=date(2026, 4, 1)) == 500.0

    def test_exclude_date_not_in_history_does_not_alter_sum(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        assert h.get_positive_sum(
            "acc-1", exclude_date=date(2099, 1, 1)
        ) == 500.0


class TestDailyProfitHistorySnapshot:
    """Snapshot dict for injection into rule context."""

    def test_get_history_dict_returns_copy(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 4, 1), 500.0)
        snap = h.get_history("acc-1")
        snap[date(2099, 1, 1)] = 999.0  # mutating shouldn't affect internal state
        assert h.get_history("acc-1") == {date(2026, 4, 1): 500.0}

    def test_get_history_unknown_account_returns_empty_dict(self):
        h = DailyProfitHistory()
        assert h.get_history("unknown") == {}


class TestDailyProfitHistoryPrune:
    """``prune`` keeps the working set bounded."""

    def test_prune_drops_dates_strictly_before_cutoff(self):
        h = DailyProfitHistory()
        h.record("acc-1", date(2026, 1, 1), 100.0)
        h.record("acc-1", date(2026, 4, 1), 200.0)
        h.record("acc-1", date(2026, 4, 15), 300.0)

        h.prune("acc-1", before=date(2026, 4, 1))

        assert h.get_history("acc-1") == {
            date(2026, 4, 1): 200.0,
            date(2026, 4, 15): 300.0,
        }
        assert h.get_positive_sum("acc-1") == 500.0


class TestDailyProfitHistoryDBLoader:
    """``load_from_db`` populates the in-memory cache from account_snapshots."""

    @pytest.mark.asyncio
    async def test_load_replaces_existing_history(self):
        rows = [
            MagicMock(snapshot_date=date(2026, 4, 1), daily_pnl=Decimal("500")),
            MagicMock(snapshot_date=date(2026, 4, 2), daily_pnl=Decimal("-100")),
            MagicMock(snapshot_date=date(2026, 4, 3), daily_pnl=Decimal("300")),
        ]
        result = MagicMock()
        result.all.return_value = rows

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        factory = MagicMock(return_value=session)

        h = DailyProfitHistory()
        # Pre-existing history that should be replaced
        h.record("acc-1", date(2025, 12, 31), 9999.0)

        await h.load_from_db("acc-1", session_factory=factory, lookback_days=60)

        assert h.get_positive_sum("acc-1") == 800.0
        assert h.get_history("acc-1") == {
            date(2026, 4, 1): 500.0,
            date(2026, 4, 2): -100.0,
            date(2026, 4, 3): 300.0,
        }

    @pytest.mark.asyncio
    async def test_load_with_no_rows_clears_account(self):
        result = MagicMock()
        result.all.return_value = []
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.execute = AsyncMock(return_value=result)
        factory = MagicMock(return_value=session)

        h = DailyProfitHistory()
        h.record("acc-1", date(2025, 12, 31), 500.0)

        await h.load_from_db("acc-1", session_factory=factory, lookback_days=60)

        assert h.get_history("acc-1") == {}
        assert h.get_positive_sum("acc-1") == 0.0
