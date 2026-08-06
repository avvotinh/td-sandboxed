"""Unit tests for repo-root data-path resolution (Contract v2 P1, gap G4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.lab.job_config import repo_root, resolve_data_path

pytestmark = pytest.mark.unit


class TestRepoRoot:
    def test_finds_directory_containing_dot_git(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TD_REPO_ROOT", raising=False)
        root = repo_root()
        assert (root / ".git").exists()
        # This module lives inside the repo the root was derived from.
        assert Path(__file__).resolve().is_relative_to(root)

    def test_env_override_wins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("TD_REPO_ROOT", str(tmp_path))
        assert repo_root() == tmp_path


class TestResolveDataPath:
    def test_relative_path_resolves_under_repo_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TD_REPO_ROOT", raising=False)
        relative = Path("data/historical/XAUUSD/M5/in_sample.parquet")
        assert resolve_data_path(relative) == repo_root() / relative

    def test_absolute_path_untouched(self, tmp_path: Path) -> None:
        absolute = tmp_path / "bars.parquet"
        assert resolve_data_path(absolute) == absolute

    def test_env_override_applies_to_relative_paths(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("TD_REPO_ROOT", str(tmp_path))
        assert (
            resolve_data_path(Path("data/x.parquet"))
            == tmp_path / "data" / "x.parquet"
        )

    def test_relative_preset_path_resolves_and_loads(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pin the composition run_backtest uses for prop-firm presets:
        ``load_prop_firm_preset(resolve_data_path(preset_path))``."""
        from src.lab.prop_firm_preset import (
            DEFAULT_PROP_FIRM_PRESET_PATH,
            load_prop_firm_preset,
        )

        target = tmp_path / "configs" / "preset.yaml"
        target.parent.mkdir()
        target.write_text(DEFAULT_PROP_FIRM_PRESET_PATH.read_text())
        monkeypatch.setenv("TD_REPO_ROOT", str(tmp_path))

        preset = load_prop_firm_preset(
            resolve_data_path(Path("configs/preset.yaml"))
        )
        assert preset.daily_loss_pct == 5.0

    def test_posix_rooted_path_treated_as_absolute(self) -> None:
        """A stale ``/home/...`` path must fail loudly at read time, not
        silently resolve under the repo root (Windows: rooted-but-driveless
        paths report ``is_absolute() == False``)."""
        stale = Path("/home/hopdev/Dev/Sandboxed/data/x.parquet")
        assert resolve_data_path(stale) == stale
