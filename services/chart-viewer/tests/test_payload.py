"""Tests for the viewer payload builder."""

from __future__ import annotations

from chart_viewer.payload import (
    build_run_payload,
    equity_to_payload,
    iso_to_epoch,
    trades_to_payload,
)


def test_iso_to_epoch_assumes_utc_when_naive() -> None:
    assert iso_to_epoch("2024-01-01T00:00:00") == iso_to_epoch("2024-01-01T00:00:00+00:00")


def test_trades_to_payload_shapes_row(sample_result: dict) -> None:
    rows = trades_to_payload(sample_result["trades"])
    assert len(rows) == 1
    row = rows[0]
    assert row["side"] == "LONG"
    assert row["entryPrice"] == 2010.3
    assert row["quantity"] == 3.54
    # sl_path carries the initial SL forward to the exit timestamp.
    assert row["slPath"][0]["time"] == iso_to_epoch("2024-01-01T00:05:00+00:00")
    assert row["slPath"][-1]["time"] == iso_to_epoch("2024-01-01T00:10:00+00:00")


def test_sl_path_collapses_same_time_writes() -> None:
    trade = {
        "entry": {"ts": "2024-01-01T00:00:00+00:00", "price": 100.0},
        "exit": {"ts": "2024-01-01T01:00:00+00:00", "price": 110.0},
        "sl": 95.0,
        "sl_path": [
            {"ts": "2024-01-01T00:30:00+00:00", "price": 98.0},
            {"ts": "2024-01-01T00:30:00+00:00", "price": 99.0},  # same ts → last wins
        ],
        "side": "LONG",
    }
    [row] = trades_to_payload([trade])
    times = [p["time"] for p in row["slPath"]]
    assert times == sorted(times)
    assert len(times) == len(set(times))  # strictly ascending, no dupes
    # last-write-wins at the collapsed timestamp
    collapsed = next(p for p in row["slPath"] if p["time"] == iso_to_epoch("2024-01-01T00:30:00+00:00"))
    assert collapsed["price"] == 99.0


def test_equity_to_payload_dedups_by_ts() -> None:
    curve = [
        {"ts": "2024-01-01T00:00:00+00:00", "equity": 100.0},
        {"ts": "2024-01-01T00:00:00+00:00", "equity": 101.0},
    ]
    out = equity_to_payload(curve)
    assert out == [{"time": iso_to_epoch("2024-01-01T00:00:00+00:00"), "value": 101.0}]


def test_build_run_payload_headline(sample_result: dict) -> None:
    payload = build_run_payload(sample_result)
    meta = payload["meta"]
    assert meta["runId"] == "donchian_breakout-xauusd-m5-20260101-000000"
    assert meta["netPnl"] == 970.87
    assert meta["sharpe"] == 0.42
    assert meta["winRate"] == 1.0
    assert len(payload["trades"]) == 1
    assert len(payload["indicators"]) == 1
    assert len(payload["equity"]) == 2
