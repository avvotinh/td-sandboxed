"""Markdown comparison report — Epic 12 Story 12.3.

Renders a single side-by-side table for a list of
:class:`BacktestResult` produced by :func:`run_baseline`. The report
is what the validation campaign (Phase 12.A) writes into
``docs/sprint-artifacts/epic-12-validation-report.md``: one row per
strategy, columns Sharpe / Sortino / Max DD / Profit Factor / Win Rate
/ Trades / Breaches / Verdict.

The verdict column applies the Decision §2 in-sample filter (sharpe
≥ 0.8, max overall DD ≤ 8 pp, trades ≥ 200, zero compliance breaches).
Strategies that fail the filter must NOT proceed to Phase 12.B
(parameter sweep) — the threshold is intentionally cheap so the report
itself flags overfitting candidates.

Markdown is the chosen format because Comparison reports are read in
code review (git-diffable) and pasted into memos. Per-strategy
deep-dive HTML lives in :mod:`src.backtesting.reports.html_writer`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.backtesting.metrics.schema import PropFirmMetricsSchema
from src.backtesting.result import BacktestResult


logger = logging.getLogger(__name__)


_DASH = "—"  # em-dash used for missing-value cells


class FingerprintMismatchError(ValueError):
    """Two results in the same report cite different dataset fingerprints."""


@dataclass(frozen=True, slots=True)
class BaselineFilter:
    """Thresholds for the in-sample acceptance filter (Decision §2).

    Defaults match ``docs/epic-12-context.md`` exactly. Overriding
    these is rare and explicit — the report header records the values
    used so a reader can tell at a glance what bar applied.
    """

    min_sharpe: float = 0.8
    max_drawdown_pct: float = 8.0
    min_trades: int = 200
    max_daily_loss_breaches: int = 0
    # Fifth Decision §2 condition. Configurable so non-FTMO contexts
    # (where the flag is meaningless) can opt out without losing the
    # other thresholds.
    block_on_max_dd_breach: bool = True


@dataclass(frozen=True, slots=True)
class FilterVerdict:
    """Outcome of applying a :class:`BaselineFilter` to one result."""

    passed: bool
    reasons: tuple[str, ...] = ()


def evaluate_filter(
    result: BacktestResult,
    baseline_filter: BaselineFilter,
) -> FilterVerdict:
    """Apply ``baseline_filter`` to ``result``.

    Returns :class:`FilterVerdict` with ``passed=True`` only when every
    threshold clears. ``reasons`` is non-empty when ``passed=False`` so
    the report can render specific failure modes per strategy.
    """
    if result.metrics is None:
        return FilterVerdict(
            passed=False,
            reasons=("metrics unavailable (likely zero trades)",),
        )

    metrics: PropFirmMetricsSchema = result.metrics
    reasons: list[str] = []

    if metrics.risk.sharpe_ratio < baseline_filter.min_sharpe:
        reasons.append(
            f"sharpe {metrics.risk.sharpe_ratio:.2f} "
            f"< {baseline_filter.min_sharpe:.2f}"
        )
    if metrics.drawdown.max_overall_dd_pct > baseline_filter.max_drawdown_pct:
        reasons.append(
            f"max drawdown {metrics.drawdown.max_overall_dd_pct:.2f}% "
            f"> {baseline_filter.max_drawdown_pct:.2f}%"
        )
    if metrics.trades.total_trades < baseline_filter.min_trades:
        reasons.append(
            f"trades {metrics.trades.total_trades} "
            f"< {baseline_filter.min_trades}"
        )
    if (
        metrics.prop_firm_compliance.daily_loss_breaches
        > baseline_filter.max_daily_loss_breaches
    ):
        reasons.append(
            f"daily loss breaches "
            f"{metrics.prop_firm_compliance.daily_loss_breaches} "
            f"> {baseline_filter.max_daily_loss_breaches}"
        )
    if (
        baseline_filter.block_on_max_dd_breach
        and metrics.prop_firm_compliance.max_dd_breach
    ):
        reasons.append("max drawdown breach flag set")

    return FilterVerdict(passed=not reasons, reasons=tuple(reasons))


def render_comparison_report(
    results: Sequence[BacktestResult],
    *,
    baseline_filter: BaselineFilter | None = None,
) -> str:
    """Render the side-by-side markdown table for ``results``.

    Validates that all results share the same dataset fingerprint and
    ``run_label`` — diverging values mean the caller mixed datasets or
    runs by accident, and the report would silently misrepresent which
    bytes the metrics belong to.

    Args:
        results: Output of :func:`run_baseline` (or a subset).
        baseline_filter: Override the Decision §2 thresholds. Default
            instance applies when omitted.

    Returns:
        Markdown text. The output is deterministic for fixed inputs.

    Raises:
        FingerprintMismatchError: Two results cite different dataset
            fingerprints.
        ValueError: Two results carry different ``run_label`` values.
    """
    bf = baseline_filter or BaselineFilter()

    if not results:
        return _render_empty(bf)

    header = _resolve_header(results)
    verdicts = [evaluate_filter(r, bf) for r in results]
    rows = [_render_row(r, v) for r, v in zip(results, verdicts, strict=True)]
    summary = _render_summary(results, verdicts)

    parts = [
        _render_header(header, bf),
        _table(rows),
        summary,
    ]
    return "\n\n".join(p for p in parts if p) + "\n"


# --- Internals --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ReportHeader:
    """Resolved provenance shared by every result in the report."""

    run_label: str | None
    spec_name: str | None
    dataset_version: str | None
    fingerprint_short: str | None
    window_name: str | None


def _resolve_header(results: Sequence[BacktestResult]) -> _ReportHeader:
    """Collect run-level metadata, asserting consistency across results."""
    fingerprints: set[str] = set()
    run_labels: set[str] = set()
    spec_names: set[str] = set()
    versions: set[str] = set()
    windows: set[str] = set()

    for result in results:
        snapshot = result.config_snapshot
        if not snapshot:
            continue
        ds = snapshot.get("dataset") or {}
        fp = (ds.get("fingerprint") or {}).get("sha256_short")
        if fp:
            fingerprints.add(fp)
        if (rl := snapshot.get("run_label")):
            run_labels.add(rl)
        if (sn := ds.get("spec_name")):
            spec_names.add(sn)
        if (dv := ds.get("dataset_version")):
            versions.add(dv)
        if (wn := ds.get("window_name")):
            windows.add(wn)

    if len(fingerprints) > 1:
        raise FingerprintMismatchError(
            f"results cite multiple dataset fingerprints: "
            f"{sorted(fingerprints)}"
        )
    if len(run_labels) > 1:
        raise ValueError(
            f"results carry diverging run_label values: {sorted(run_labels)}"
        )

    return _ReportHeader(
        run_label=next(iter(run_labels), None),
        spec_name=next(iter(spec_names), None),
        dataset_version=next(iter(versions), None),
        fingerprint_short=next(iter(fingerprints), None),
        window_name=next(iter(windows), None),
    )


def _render_header(header: _ReportHeader, bf: BaselineFilter) -> str:
    lines = ["# In-sample comparison report", ""]
    lines.append(f"- Run label: `{header.run_label or 'unknown'}`")
    lines.append(
        f"- Dataset: `{header.spec_name or 'unknown'}` "
        f"v`{header.dataset_version or 'unknown'}` "
        f"(window `{header.window_name or 'unknown'}`)"
    )
    fp = header.fingerprint_short or "missing — legacy result without snapshot"
    lines.append(f"- Dataset fingerprint: `{fp}`")
    breach_clause = (
        "max-DD breach blocks"
        if bf.block_on_max_dd_breach
        else "max-DD breach ignored"
    )
    lines.append(
        f"- Filter: sharpe ≥ {bf.min_sharpe:.2f}, "
        f"max DD ≤ {bf.max_drawdown_pct:.2f}%, "
        f"trades ≥ {bf.min_trades}, "
        f"daily-loss breaches ≤ {bf.max_daily_loss_breaches}, "
        f"{breach_clause}"
    )
    return "\n".join(lines)


def _render_row(
    result: BacktestResult,
    verdict: FilterVerdict,
) -> tuple[str, ...]:
    metrics = result.metrics
    label = _strategy_label(result)
    if metrics is None:
        return (
            label,
            _DASH,
            _DASH,
            _DASH,
            _DASH,
            _DASH,
            _DASH,
            _DASH,
            "FAIL — " + ", ".join(verdict.reasons),
        )

    breaches = (
        f"{metrics.prop_firm_compliance.daily_loss_breaches}"
        f"{' + max-DD' if metrics.prop_firm_compliance.max_dd_breach else ''}"
    )
    verdict_cell = (
        "PASS" if verdict.passed else "FAIL — " + ", ".join(verdict.reasons)
    )
    return (
        label,
        f"{metrics.risk.sharpe_ratio:.2f}",
        f"{metrics.risk.sortino_ratio:.2f}",
        f"{metrics.drawdown.max_overall_dd_pct:.2f}%",
        f"{metrics.pnl.profit_factor:.2f}",
        f"{metrics.trades.win_rate * 100:.1f}%",
        f"{metrics.trades.total_trades}",
        breaches,
        verdict_cell,
    )


def _table(rows: Sequence[Sequence[str]]) -> str:
    columns = (
        "Strategy",
        "Sharpe",
        "Sortino",
        "Max DD",
        "Profit Factor",
        "Win Rate",
        "Trades",
        "Breaches",
        "Verdict",
    )
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _render_summary(
    results: Sequence[BacktestResult],
    verdicts: Sequence[FilterVerdict],
) -> str:
    passes: list[str] = []
    fails: list[str] = []
    for result, verdict in zip(results, verdicts, strict=True):
        bucket = passes if verdict.passed else fails
        bucket.append(_strategy_label(result))

    parts = ["## Summary"]
    if passes:
        parts.append(
            f"- Pass ({len(passes)}): "
            + ", ".join(f"`{name}`" for name in passes)
            + " — eligible for Phase 12.B walk-forward + sweep."
        )
    else:
        parts.append("- Pass: _none_ — no strategies eligible for Phase 12.B.")
    if fails:
        parts.append(
            f"- Fail ({len(fails)}): "
            + ", ".join(f"`{name}`" for name in fails)
            + " — do not tune (overfitting trap, see Decision §2)."
        )
    return "\n".join(parts)


def _render_empty(bf: BaselineFilter) -> str:
    breach_clause = (
        "max-DD breach blocks"
        if bf.block_on_max_dd_breach
        else "max-DD breach ignored"
    )
    return (
        "# In-sample comparison report\n\n"
        "_no results — empty input passed to render_comparison_report._\n\n"
        f"Filter: sharpe ≥ {bf.min_sharpe:.2f}, "
        f"max DD ≤ {bf.max_drawdown_pct:.2f}%, "
        f"trades ≥ {bf.min_trades}, "
        f"daily-loss breaches ≤ {bf.max_daily_loss_breaches}, "
        f"{breach_clause}.\n"
    )


def _strategy_label(result: BacktestResult) -> str:
    snapshot: dict[str, Any] | None = result.config_snapshot
    if snapshot:
        strat = snapshot.get("strategy") or {}
        if (label := strat.get("label")):
            return _sanitise_table_cell(str(label))
    return _sanitise_table_cell(result.strategy_name)


def _sanitise_table_cell(value: str) -> str:
    """Defang characters that would split a markdown table cell.

    ``|`` opens an extra column; ``\\n``/``\\r`` start a new table row.
    Backticks render as inline code and are visually fine. Strategy
    labels come from caller-controlled YAML so we cannot trust them
    structurally.
    """
    return value.replace("|", "\\|").replace("\r", "").replace("\n", " ")
