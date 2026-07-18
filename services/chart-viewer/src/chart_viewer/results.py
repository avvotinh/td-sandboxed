"""Scan + load Result Contract v2 JSON files from a results directory.

Only ``schema_version == "2"`` files are accepted (fail loudly on
anything else — no guessing). Malformed files are skipped with a
warning entry so the run-list page can surface them instead of
crashing the whole listing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metrics import fallback_net_pnl, fallback_win_rate

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = "2"

# run_ids become URL path segments and are matched against file stems —
# never let them carry path separators or dots-only segments.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class UnknownRunError(KeyError):
    """No result file with the requested run_id exists."""


class InvalidResultError(ValueError):
    """A result file is unreadable, malformed, or has a foreign schema."""


def is_valid_run_id(run_id: str) -> bool:
    """True when ``run_id`` is safe to use as a lookup key / URL part."""
    return bool(_RUN_ID_RE.match(run_id)) and ".." not in run_id


@dataclass(frozen=True)
class RunSummary:
    """Run-list row: identity + headline metrics for one result file."""

    run_id: str
    file_name: str
    strategy: str
    symbol: str
    timeframe: str
    window_name: str
    start: str | None
    end: str | None
    trade_count: int
    net_pnl: float | None
    win_rate: float | None
    profit_factor: float | None
    sharpe_ratio: float | None
    max_drawdown_pct: float | None


@dataclass(frozen=True)
class ScanWarning:
    """One skipped file: name + human-readable reason."""

    file_name: str
    reason: str


def load_result(path: Path) -> dict[str, Any]:
    """Read + validate one Contract v2 file; raise :class:`InvalidResultError`."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidResultError(f"unreadable file: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidResultError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidResultError("top-level JSON value is not an object")
    version = data.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise InvalidResultError(
            f"unsupported schema_version {version!r} "
            f"(viewer reads {SUPPORTED_SCHEMA_VERSION!r} only)"
        )
    run = data.get("run")
    if not isinstance(run, dict) or not run.get("run_id"):
        raise InvalidResultError("missing run.run_id")
    return data


def summarize(data: dict[str, Any], file_name: str) -> RunSummary:
    """Headline row for the run-list page (tolerates missing metrics)."""
    run = data["run"]
    window = run.get("window") or {}
    metrics = data.get("metrics") or {}
    pnl = metrics.get("pnl") or {}
    risk = metrics.get("risk") or {}
    trades_m = metrics.get("trades") or {}
    drawdown = metrics.get("drawdown") or {}
    account = data.get("account") or {}
    trades = data.get("trades") or []

    net_pnl = fallback_net_pnl(account, pnl)
    win_rate = fallback_win_rate(trades, trades_m)

    return RunSummary(
        run_id=str(run["run_id"]),
        file_name=file_name,
        strategy=str(run.get("strategy", "?")),
        symbol=str(run.get("symbol", "?")),
        timeframe=str(run.get("timeframe", "?")),
        window_name=str(window.get("name", "?")),
        start=window.get("start"),
        end=window.get("end"),
        trade_count=len(trades),
        net_pnl=net_pnl,
        win_rate=win_rate,
        profit_factor=pnl.get("profit_factor"),
        sharpe_ratio=risk.get("sharpe_ratio"),
        max_drawdown_pct=drawdown.get("max_overall_dd_pct"),
    )


class ResultStore:
    """Read-only access to ``<results_dir>/*.json`` Contract v2 files.

    The directory is re-scanned per call — result sets are small (one
    file per run) and re-scanning keeps the viewer live as new runs
    are exported while the server is up.
    """

    def __init__(self, results_dir: Path) -> None:
        self._results_dir = results_dir

    @property
    def results_dir(self) -> Path:
        return self._results_dir

    def scan(self) -> tuple[list[RunSummary], list[ScanWarning]]:
        """All valid run summaries (newest first) + skip warnings."""
        summaries: list[RunSummary] = []
        warnings: list[ScanWarning] = []
        if not self._results_dir.is_dir():
            return summaries, warnings
        for path in sorted(self._results_dir.glob("*.json")):
            try:
                data = load_result(path)
                summaries.append(summarize(data, path.name))
            except InvalidResultError as exc:
                logger.warning("Skipping %s: %s", path.name, exc)
                warnings.append(ScanWarning(file_name=path.name, reason=str(exc)))
        summaries.sort(key=lambda s: s.run_id, reverse=True)
        return summaries, warnings

    def get(self, run_id: str) -> dict[str, Any]:
        """Full Contract v2 dict for ``run_id``; :class:`UnknownRunError` if absent.

        Fast path: ``<run_id>.json`` (the exporter's naming convention).
        Fallback: scan every valid file for a matching ``run.run_id``
        (files may be renamed by hand).
        """
        if not is_valid_run_id(run_id):
            raise UnknownRunError(run_id)
        direct = self._results_dir / f"{run_id}.json"
        if direct.is_file():
            try:
                data = load_result(direct)
                if data["run"]["run_id"] == run_id:
                    return data
            except InvalidResultError:
                pass
        if self._results_dir.is_dir():
            for path in sorted(self._results_dir.glob("*.json")):
                try:
                    data = load_result(path)
                except InvalidResultError:
                    continue
                if data["run"]["run_id"] == run_id:
                    return data
        raise UnknownRunError(run_id)
