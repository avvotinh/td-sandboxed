"""Shared fixtures — a minimal Contract v2 result written to a temp dir."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _result(run_id: str, *, manifest: str = "synthetic:trending:count=3:seed=1") -> dict:
    return {
        "schema_version": "2",
        "run": {
            "run_id": run_id,
            "strategy": "donchian_breakout",
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "window": {
                "name": "synthetic",
                "start": "2024-01-01T00:00:00+00:00",
                "end": "2024-01-01T00:30:00+00:00",
            },
            "params": {"channel_period": 20},
            "data_ref": {"manifest": manifest, "entry": None, "fingerprint": None},
            "engine": {"nautilus_version": "1.221.0", "commit": "abc123"},
        },
        "account": {
            "initial_balance": 100000,
            "final_balance": 100970,
            "currency": "USD",
            "risk_profile": "demo",
        },
        "trades": [
            {
                "trade_id": "SIM-1-001",
                "side": "LONG",
                "entry": {"ts": "2024-01-01T00:05:00+00:00", "price": 2010.3, "reason": None},
                "exit": {"ts": "2024-01-01T00:10:00+00:00", "price": 2013.1, "reason": None},
                "quantity_lots": 3.54,
                "pnl": 970.87,
                "r_multiple": 1.998,
                "sl": 2008.9,
                "tp": 2013.1,
                "sl_path": [{"ts": "2024-01-01T00:10:00+00:00", "price": 2008.9, "reason": None}],
            }
        ],
        "equity_curve": [
            {"ts": "2024-01-01T00:00:00+00:00", "equity": 100000.0},
            {"ts": "2024-01-01T00:30:00+00:00", "equity": 100970.0},
        ],
        "indicators": [
            {
                "key": "donchian_upper",
                "title": "Donchian Upper",
                "pane": "overlay",
                "color": "#22c55e",
                "points": [{"time": 1704067500, "value": 2010.1}],
                "levels": [],
            }
        ],
        "metrics": {
            "pnl": {"net_pnl": 970.87, "profit_factor": 1.8},
            "risk": {"sharpe_ratio": 0.42},
            "trades": {"win_rate": 1.0},
            "drawdown": {"max_overall_dd_pct": 0.05},
        },
        "breaches": [],
    }


@pytest.fixture
def results_dir(tmp_path: Path) -> Path:
    """A results dir holding one valid run + one foreign-schema file."""
    (tmp_path / "donchian_breakout-xauusd-m5-20260101-000000.json").write_text(
        json.dumps(_result("donchian_breakout-xauusd-m5-20260101-000000")), encoding="utf-8"
    )
    (tmp_path / "foreign.json").write_text(
        json.dumps({"schema_version": "1", "run": {"run_id": "old"}}), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def sample_result() -> dict:
    return _result("donchian_breakout-xauusd-m5-20260101-000000")
