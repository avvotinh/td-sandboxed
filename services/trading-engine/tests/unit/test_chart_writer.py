"""Unit tests for the lightweight-charts HTML writer."""

from __future__ import annotations

import json

import pytest

from src.backtesting.reports.chart_writer import (
    render_chart_html,
    write_chart_html,
)

pytestmark = pytest.mark.unit


def _payload() -> dict:
    return {
        "meta": {
            "strategy": "supertrend",
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "window": "in_sample",
            "start": "2024-01-01T00:00:00+00:00",
            "end": "2024-02-01T00:00:00+00:00",
            "params": {},
            "initialBalance": 100000.0,
            "finalBalance": 100500.0,
            "pnl": 500.0,
            "tradeCount": 1,
            "winRate": 1.0,
        },
        "candles": [
            {"time": 1704067200, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}
        ],
        "trades": [],
        "indicators": [],
    }


class TestRender:
    def test_contains_title_payload_and_library(self) -> None:
        html_doc = render_chart_html(_payload())
        assert "supertrend · XAUUSD M5" in html_doc
        assert "Lightweight Charts" in html_doc  # vendored lib banner
        assert '"tradeCount":1' in html_doc
        assert "__PAYLOAD_JSON__" not in html_doc
        assert "__LIB_JS__" not in html_doc

    def test_script_close_sequence_is_escaped(self) -> None:
        payload = _payload()
        payload["meta"]["strategy"] = "x</script><script>alert(1)"
        html_doc = render_chart_html(payload)
        # Inside the JSON block the close tag must be neutralised.
        json_block = html_doc.split('type="application/json">')[1].split("</script>")[0]
        assert "</script" not in json_block
        assert json.loads(json_block.replace("<\\/", "</"))

    def test_render_is_deterministic(self) -> None:
        assert render_chart_html(_payload()) == render_chart_html(_payload())


class TestWrite:
    def test_writes_utf8_file(self, tmp_path) -> None:
        out = tmp_path / "charts" / "report.html"
        written = write_chart_html(_payload(), out)
        assert written == out
        text = out.read_text(encoding="utf-8")
        assert text.startswith("<!DOCTYPE html>")

    def test_rejects_path_traversal(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="traversal"):
            write_chart_html(_payload(), tmp_path / ".." / "escape.html")
