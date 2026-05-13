"""End-to-end bridge test between the tv-api Go CLI and the Python
``DatasetManifest`` consumer.

Story 12.7.0d — gated by ``TV_E2E=1`` because it shells out to the Go
binary and hits TradingView's WebSocket, which adds latency and
external-dependency risk that should never run on every CI build.

Run locally:

.. code-block:: bash

    cd services/tv-api && go build -o bin/tv-cli ./cmd/tv-cli
    cd services/trading-engine
    TV_E2E=1 uv run pytest tests/integration/test_go_bridge_e2e.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.backtesting.dataset.go_manifest_loader import merge_go_manifests
from src.backtesting.dataset.manifest import DatasetManifest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("TV_E2E") != "1",
        reason="TV_E2E=1 not set — skipping live TradingView fetch",
    ),
]


REPO_ROOT = Path(__file__).resolve().parents[3]
TV_API_DIR = REPO_ROOT / "services" / "tv-api"
TV_CLI_BIN = TV_API_DIR / "bin" / "tv-cli"


def _ensure_cli_built() -> Path:
    """Build the Go CLI on demand if the binary is missing or stale.

    Stale = binary mtime older than the newest tracked Go source under
    services/tv-api/. Without this check, an old binary silently
    survives source edits and produces confusing cross-language
    contract failures during developer iteration.
    """
    if TV_CLI_BIN.exists():
        binary_mtime = TV_CLI_BIN.stat().st_mtime
        newest_source_mtime = max(
            (
                p.stat().st_mtime
                for p in TV_API_DIR.rglob("*.go")
                if "/.git/" not in str(p)
            ),
            default=0.0,
        )
        if newest_source_mtime <= binary_mtime:
            return TV_CLI_BIN

    subprocess.run(
        ["go", "build", "-o", str(TV_CLI_BIN), "./cmd/tv-cli"],
        cwd=TV_API_DIR,
        check=True,
    )
    return TV_CLI_BIN


def _cli_command(out: Path, *, from_iso: str, to_iso: str) -> list[str]:
    return [
        str(_ensure_cli_built()),
        "-command",
        "backtest-fetch",
        "-symbol",
        "OANDA:XAUUSD",
        "-timeframe",
        "5",
        "-from",
        from_iso,
        "-to",
        to_iso,
        "-window-name",
        "smoke",
        "-window-kind",
        "in_sample",
        "-out",
        str(out),
        "-throttle-ms",
        "200",
        "-batch-size",
        "500",
    ]


def test_go_cli_writes_python_loadable_manifest(tmp_path: Path) -> None:
    """A fresh fetch round-trips through DatasetManifest.load_json."""
    if not shutil.which("go"):
        pytest.skip("go toolchain not on PATH")

    out = tmp_path / "smoke.parquet"
    # 4 hours of M5 ≈ 48 bars — well below any rate-limit ceiling.
    end = datetime(2025, 4, 1, 4, 0, 0, tzinfo=UTC)
    start = end - timedelta(hours=4)

    cmd = _cli_command(
        out,
        from_iso=start.isoformat().replace("+00:00", "Z"),
        to_iso=end.isoformat().replace("+00:00", "Z"),
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"tv-cli failed: {result.stderr}"
    assert out.exists(), "Parquet file was not produced"

    sidecar = Path(str(out) + ".manifest.json")
    assert sidecar.exists(), "manifest sidecar was not produced"

    # The contract: Python loads what Go wrote, no adapter needed.
    manifest = DatasetManifest.load_json(sidecar)
    assert manifest.symbol == "XAUUSD"
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.timeframe == "5"
    assert entry.window_name == "smoke"
    assert entry.row_count > 0, "expected at least one bar"
    # Row-count consistency check (Go's BarRow ms timestamps × Python ns).
    assert entry.fingerprint.row_count == entry.row_count


def test_merge_two_sidecars_round_trip(tmp_path: Path) -> None:
    """Two independent fetches merge into a single canonical manifest."""
    if not shutil.which("go"):
        pytest.skip("go toolchain not on PATH")

    paths: list[Path] = []
    base = datetime(2025, 4, 1, 4, 0, 0, tzinfo=UTC)
    for i, name in enumerate(("shard_a", "shard_b")):
        out = tmp_path / f"{name}.parquet"
        end = base - timedelta(hours=4 * i)
        start = end - timedelta(hours=2)
        cmd = _cli_command(
            out,
            from_iso=start.isoformat().replace("+00:00", "Z"),
            to_iso=end.isoformat().replace("+00:00", "Z"),
        )
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, f"tv-cli failed for {name}: {result.stderr}"
        paths.append(Path(str(out) + ".manifest.json"))

    merged = merge_go_manifests(paths)
    assert len(merged.entries) == 2
    assert merged.symbol == "XAUUSD"
    # Total rows should equal the sum of per-shard rows.
    expected_total = sum(
        json.loads(p.read_text())["entries"][0]["row_count"] for p in paths
    )
    assert merged.total_rows == expected_total
