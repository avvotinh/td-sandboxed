"""Tests for scanning + loading Contract v2 result files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chart_viewer.results import (
    InvalidResultError,
    ResultStore,
    UnknownRunError,
    is_valid_run_id,
    load_result,
    summarize,
)


@pytest.mark.parametrize(
    "run_id, ok",
    [
        ("donchian-xauusd-m5-20260101-000000", True),
        ("a.b_c-1", True),
        ("../etc/passwd", False),
        ("has/slash", False),
        ("..", False),
        ("", False),
    ],
)
def test_is_valid_run_id(run_id: str, ok: bool) -> None:
    assert is_valid_run_id(run_id) is ok


def test_load_result_rejects_foreign_schema(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"schema_version": "1", "run": {"run_id": "z"}}), encoding="utf-8")
    with pytest.raises(InvalidResultError):
        load_result(p)


def test_load_result_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidResultError):
        load_result(p)


def test_load_result_requires_run_id(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"schema_version": "2", "run": {}}), encoding="utf-8")
    with pytest.raises(InvalidResultError):
        load_result(p)


def test_summarize_derives_net_pnl_from_account(sample_result: dict) -> None:
    sample_result["metrics"]["pnl"].pop("net_pnl")
    summary = summarize(sample_result, "f.json")
    assert summary.net_pnl == pytest.approx(970.0)
    assert summary.trade_count == 1


def test_scan_lists_valid_and_warns_on_foreign(results_dir: Path) -> None:
    store = ResultStore(results_dir)
    summaries, warnings = store.scan()
    assert len(summaries) == 1
    assert summaries[0].strategy == "donchian_breakout"
    assert [w.file_name for w in warnings] == ["foreign.json"]


def test_scan_missing_dir_is_empty(tmp_path: Path) -> None:
    summaries, warnings = ResultStore(tmp_path / "nope").scan()
    assert summaries == [] and warnings == []


def test_get_by_run_id(results_dir: Path) -> None:
    store = ResultStore(results_dir)
    data = store.get("donchian_breakout-xauusd-m5-20260101-000000")
    assert data["run"]["run_id"] == "donchian_breakout-xauusd-m5-20260101-000000"


def test_get_unknown_raises(results_dir: Path) -> None:
    with pytest.raises(UnknownRunError):
        ResultStore(results_dir).get("does-not-exist")


def test_get_rejects_traversal(results_dir: Path) -> None:
    with pytest.raises(UnknownRunError):
        ResultStore(results_dir).get("../foreign")
