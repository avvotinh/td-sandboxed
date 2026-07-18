"""Tests for the repo-root path-traversal guard.

This guard is the sole defense against a crafted ``run.data_ref.manifest``
in a hand-edited result file escaping the repo root, so it is exercised
directly here rather than only incidentally through candle loading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chart_viewer.paths import PathOutsideRepoError, resolve_within_repo


def test_resolves_relative_within_root(tmp_path: Path) -> None:
    resolved = resolve_within_repo("data/bars.parquet", tmp_path)
    assert resolved == (tmp_path / "data" / "bars.parquet").resolve()


def test_accepts_absolute_inside_root(tmp_path: Path) -> None:
    inside = tmp_path / "data" / "bars.parquet"
    assert resolve_within_repo(str(inside), tmp_path) == inside.resolve()


@pytest.mark.parametrize(
    "ref",
    [
        "../../etc/passwd",
        "../../../Windows/win.ini",
        "data/../../secret.parquet",
    ],
)
def test_rejects_relative_ascent(tmp_path: Path, ref: str) -> None:
    with pytest.raises(PathOutsideRepoError):
        resolve_within_repo(ref, tmp_path)


def test_rejects_absolute_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere" / "bars.parquet"
    with pytest.raises(PathOutsideRepoError):
        resolve_within_repo(str(outside), tmp_path)
