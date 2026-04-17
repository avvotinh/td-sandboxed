"""Unit tests for TimescaleBarLoader with a mocked asyncpg pool."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.data_loader import TimescaleBarLoader


pytestmark = pytest.mark.unit


def _fake_pool(fetchrow_return=None, fetch_return=None) -> MagicMock:
    """Build a MagicMock that mimics ``asyncpg.Pool`` for our tests."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])

    acquire_ctx = MagicMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


class TestFingerprint:
    def test_fingerprint_from_metadata_row(self) -> None:
        min_dt = datetime(2026, 1, 1, tzinfo=UTC)
        max_dt = datetime(2026, 4, 1, tzinfo=UTC)
        pool = _fake_pool(
            fetchrow_return={"min_ts": min_dt, "max_ts": max_dt, "cnt": 1000}
        )
        loader = TimescaleBarLoader(pool)
        fp = asyncio.run(
            loader.afingerprint("XAUUSD", "1m", min_dt, max_dt)
        )
        assert fp.row_count == 1000
        assert fp.min_ts == int(min_dt.timestamp() * 1_000_000_000)
        assert fp.max_ts == int(max_dt.timestamp() * 1_000_000_000)

    def test_fingerprint_empty_range(self) -> None:
        pool = _fake_pool(
            fetchrow_return={"min_ts": None, "max_ts": None, "cnt": 0}
        )
        loader = TimescaleBarLoader(pool)
        fp = asyncio.run(
            loader.afingerprint(
                "XAUUSD",
                "1m",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 2, 1, tzinfo=UTC),
            )
        )
        assert fp == ContentHashFingerprint(min_ts=0, max_ts=0, row_count=0)


class TestLoad:
    def test_empty_result_returns_empty_df(self) -> None:
        pool = _fake_pool(fetch_return=[])
        loader = TimescaleBarLoader(pool)
        df = loader.load(
            "XAUUSD",
            "1m",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            ContentHashFingerprint(min_ts=0, max_ts=0, row_count=0),
        )
        assert df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_rows_mapped_to_dataframe(self) -> None:
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [
            {
                "time": t0,
                "open": Decimal("2400.00"),
                "high": Decimal("2410.00"),
                "low": Decimal("2390.00"),
                "close": Decimal("2405.00"),
                "volume": Decimal("100.00"),
            },
            {
                "time": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
                "open": Decimal("2405.00"),
                "high": Decimal("2415.00"),
                "low": Decimal("2400.00"),
                "close": Decimal("2410.00"),
                "volume": Decimal("120.00"),
            },
        ]
        pool = _fake_pool(fetch_return=rows)
        loader = TimescaleBarLoader(pool)
        df = loader.load(
            "XAUUSD",
            "1m",
            t0,
            datetime(2026, 2, 1, tzinfo=UTC),
            ContentHashFingerprint(min_ts=1, max_ts=2, row_count=2),
        )
        assert len(df) == 2
        assert df.iloc[0]["close"] == pytest.approx(2405.0)
        assert df.iloc[1]["close"] == pytest.approx(2410.0)

    def test_volume_null_coerced_to_zero(self) -> None:
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [
            {
                "time": t0,
                "open": Decimal("2400"),
                "high": Decimal("2400"),
                "low": Decimal("2400"),
                "close": Decimal("2400"),
                "volume": None,
            },
        ]
        pool = _fake_pool(fetch_return=rows)
        loader = TimescaleBarLoader(pool)
        df = loader.load(
            "XAUUSD",
            "1m",
            t0,
            datetime(2026, 2, 1, tzinfo=UTC),
            ContentHashFingerprint(min_ts=1, max_ts=2, row_count=1),
        )
        assert df.iloc[0]["volume"] == 0.0
