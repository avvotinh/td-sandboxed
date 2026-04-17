"""Unit tests for the FTMO preset loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backtesting.ftmo_preset import (
    DEFAULT_FTMO_PRESET_PATH,
    FtmoPreset,
    load_ftmo_preset,
)


pytestmark = pytest.mark.unit


class TestDefaultPreset:
    def test_default_file_exists(self) -> None:
        assert DEFAULT_FTMO_PRESET_PATH.exists(), (
            f"expected preset at {DEFAULT_FTMO_PRESET_PATH}"
        )

    def test_default_preset_matches_ftmo_2025_1(self) -> None:
        preset = load_ftmo_preset()
        assert isinstance(preset, FtmoPreset)
        assert preset.daily_loss_pct == 5.0
        assert preset.max_drawdown_pct == 10.0
        assert preset.profit_target_pct == 10.0
        assert preset.min_trading_days == 4
        assert preset.max_position_lots == 100.0


class TestMissingFile:
    def test_missing_path_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            load_ftmo_preset(tmp_path / "nope.yaml")


class TestMissingRules:
    def test_missing_daily_loss_raises(self, tmp_path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: broken\nrules:\n  - type: max_drawdown\n    threshold_percent: 10\n")
        with pytest.raises(ValueError, match="daily_loss_limit"):
            load_ftmo_preset(bad)

    def test_missing_max_drawdown_raises(self, tmp_path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: broken\nrules:\n  - type: daily_loss_limit\n    threshold_percent: 5\n"
        )
        with pytest.raises(ValueError, match="max_drawdown"):
            load_ftmo_preset(bad)


class TestFrozen:
    def test_preset_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        preset = load_ftmo_preset()
        with pytest.raises(FrozenInstanceError):
            preset.daily_loss_pct = 99.0  # type: ignore[misc]


class TestCustomPreset:
    def test_custom_preset_loaded(self, tmp_path: Path) -> None:
        yaml_text = """
name: Custom Firm
rules:
  - type: daily_loss_limit
    threshold_percent: 3.0
  - type: max_drawdown
    threshold_percent: 6.0
  - type: max_position_size
    max_lots: 50.0
  - type: profit_target
    threshold_percent: 8.0
  - type: min_trading_days
    required_days: 2
"""
        preset_file = tmp_path / "custom.yaml"
        preset_file.write_text(yaml_text)
        preset = load_ftmo_preset(preset_file)
        assert preset.name == "Custom Firm"
        assert preset.daily_loss_pct == 3.0
        assert preset.max_drawdown_pct == 6.0
        assert preset.profit_target_pct == 8.0
        assert preset.min_trading_days == 2
        assert preset.max_position_lots == 50.0
