"""Unit tests for the pure-logic helpers in ``scripts/run_trailing_ab.py``.

The script lives outside the ``src`` package, so it is loaded via
importlib straight from the scripts directory — same module the CLI
executes, no copy-paste drift.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[3] / "scripts" / "run_trailing_ab.py"
_spec = importlib.util.spec_from_file_location("run_trailing_ab", _SCRIPT)
assert _spec is not None and _spec.loader is not None
run_trailing_ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_trailing_ab)


class TestVariantOverlays:
    def test_four_variants_in_report_order(self) -> None:
        overlays = run_trailing_ab._variant_overlays("10")
        assert list(overlays) == [
            "baseline",
            "scaleout",
            "trailonly",
            "scaleout-beoffset",
        ]

    def test_baseline_is_empty(self) -> None:
        assert run_trailing_ab._variant_overlays("10")["baseline"] == {}

    def test_scaleout_enables_partial_and_trail(self) -> None:
        overlay = run_trailing_ab._variant_overlays("10")["scaleout"]
        assert overlay["scale_out_enabled"] is True
        assert overlay["trailing_enabled"] is True
        assert overlay["breakeven_at_r"] == "1.0"
        assert "breakeven_offset_pips" not in overlay

    def test_trailonly_has_no_partial_and_no_be(self) -> None:
        overlay = run_trailing_ab._variant_overlays("10")["trailonly"]
        assert overlay["scale_out_enabled"] is False
        assert overlay["trailing_enabled"] is True
        assert overlay["breakeven_at_r"] is None

    def test_beoffset_extends_scaleout_with_offset(self) -> None:
        overlays = run_trailing_ab._variant_overlays("10")
        offset = overlays["scaleout-beoffset"]
        assert offset["breakeven_offset_pips"] == "10"
        assert {k: v for k, v in offset.items() if k != "breakeven_offset_pips"} == (
            overlays["scaleout"]
        )


class TestBuildStrategies:
    def test_eight_specs_with_unique_labels(self) -> None:
        specs = run_trailing_ab._build_strategies("M5", be_offset_pips="10")
        assert len(specs) == 8
        labels = [s.display_label for s in specs]
        assert len(set(labels)) == 8
        assert "supertrend[trailonly]" in labels
        assert "donchian_breakout[scaleout-beoffset]" in labels

    def test_params_stay_json_primitive(self) -> None:
        for spec in run_trailing_ab._build_strategies("M15", be_offset_pips="10"):
            for key, value in spec.params.items():
                assert isinstance(value, (int, float, str, bool, type(None))), (
                    f"{spec.display_label}.{key} = {value!r}"
                )

    def test_unknown_timeframe_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            run_trailing_ab._build_strategies("M7", be_offset_pips="10")


class TestResolveBeOffset:
    def test_cli_override_wins(self) -> None:
        assert run_trailing_ab._resolve_be_offset("XAUUSD", "3") == "3"

    def test_symbol_default(self) -> None:
        assert run_trailing_ab._resolve_be_offset("xauusd", None) == "10"

    def test_unknown_symbol_without_override_raises(self) -> None:
        with pytest.raises(ValueError, match="No default BE offset"):
            run_trailing_ab._resolve_be_offset("EURUSD", None)


class TestPipsArg:
    def test_accepts_non_negative_decimal(self) -> None:
        assert run_trailing_ab._pips_arg("7.5") == "7.5"
        assert run_trailing_ab._pips_arg("0") == "0"

    @pytest.mark.parametrize("bad", ["abc", "-1"])
    def test_rejects_malformed_and_negative(self, bad: str) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            run_trailing_ab._pips_arg(bad)
