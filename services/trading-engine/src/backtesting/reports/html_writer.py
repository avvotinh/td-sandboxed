"""Single-file HTML report writer for ``BacktestResult``.

Produces a self-contained HTML document (no external assets, no JS)
with a summary table, inline SVG equity curve, trade list, and breach
list. The output is deterministic: byte-for-byte identical across runs
for the same input.

All user-provided strings are HTML-escaped on their way in — breach
``rule_name`` / ``message`` may contain arbitrary characters.
"""

from __future__ import annotations

import math
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backtesting.result import BacktestResult, BreachEvent, TradeRecord


_STYLE = """
body { font-family: system-ui, -apple-system, sans-serif; max-width: 980px;
       margin: 24px auto; padding: 0 16px; color: #222; }
h1 { margin-bottom: 4px; }
h2 { margin-top: 32px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; }
th { background: #fafafa; }
.metric { font-variant-numeric: tabular-nums; }
.breach { color: #b91c1c; }
.positive { color: #15803d; }
.negative { color: #b91c1c; }
.empty { color: #888; font-style: italic; margin: 8px 0; }
svg { border: 1px solid #eee; background: #fbfbfb; }
"""

_MAX_TRADE_ROWS = 100


def render_html_report(result: BacktestResult) -> str:
    """Return a self-contained HTML document for ``result``."""
    net_pnl = Decimal(result.final_balance) - Decimal(result.initial_balance)
    pnl_class = "positive" if net_pnl >= 0 else "negative"

    summary_rows = [
        ("Strategy", escape(result.strategy_name)),
        (
            "Window",
            f"{_fmt_ts(result.start)} → {_fmt_ts(result.end)}",
        ),
        ("Initial balance", _fmt_decimal(result.initial_balance)),
        ("Final balance", _fmt_decimal(result.final_balance)),
        ("Net PnL", f"<span class='{pnl_class}'>{_fmt_decimal(net_pnl)}</span>"),
        ("Trades", str(len(result.trades))),
        ("Breaches", str(len(result.breaches))),
    ]
    if result.metrics is not None:
        m = result.metrics
        summary_rows.extend(
            [
                ("Profit factor", _fmt_float(m.pnl.profit_factor)),
                ("Sharpe ratio", _fmt_float(m.risk.sharpe_ratio)),
                ("Max overall DD %", _fmt_float(m.drawdown.max_overall_dd_pct)),
                ("Win rate", f"{m.trades.win_rate * 100:.2f}%"),
            ]
        )

    summary_html = _table(("Metric", "Value"), summary_rows)
    equity_svg = _render_equity_curve(result.equity_curve)
    trades_html = _render_trades(result.trades)
    breaches_html = _render_breaches(result.breaches)

    return (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n"
        "<head>\n"
        "<meta charset='utf-8'>\n"
        f"<title>Backtest: {escape(result.strategy_name)}</title>\n"
        f"<style>{_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>Backtest: {escape(result.strategy_name)}</h1>\n"
        "<h2>Summary</h2>\n"
        f"{summary_html}"
        "<h2>Equity Curve</h2>\n"
        f"{equity_svg}"
        "<h2>Trades</h2>\n"
        f"{trades_html}"
        "<h2>Breaches</h2>\n"
        f"{breaches_html}"
        "</body>\n</html>\n"
    )


def write_html_report(result: BacktestResult, path: Path) -> None:
    """Render + write the HTML report to ``path`` (creates parents).

    Rejects paths containing ``..`` components — consistent with the
    ``ParquetDataSpec.path`` / ``PropFirmSpec.preset_path`` guards. Forces
    UTF-8 so the output matches the ``<meta charset='utf-8'>`` header
    regardless of the host platform's default encoding.
    """
    path = Path(path)
    if ".." in path.parts:
        raise ValueError(
            f"Path traversal via '..' not allowed in HTML report path: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html_report(result), encoding="utf-8")


# ---- helpers --------------------------------------------------------


def _fmt_decimal(value) -> str:
    return f"{Decimal(value):.2f}"


def _fmt_float(value: float) -> str:
    return f"{value:.4f}" if abs(value) < 1000 else f"{value:.2f}"


def _fmt_ts(value) -> str:
    if value is None:
        return "-"
    return escape(value.isoformat())


def _table(headers: tuple[str, str], rows: list[tuple[str, str]]) -> str:
    """Render a 2-column table.

    The ``key`` column is HTML-escaped. The ``html_value`` column is
    injected **verbatim as trusted HTML** — callers must pre-escape
    any untrusted strings (see ``_fmt_ts`` / ``_fmt_decimal`` for the
    standard pattern). The asymmetry is what lets summary rows embed
    safe ``<span>`` markup for coloured PnL, but adding a row whose
    value comes directly from user input without escaping would be an
    XSS foothold.
    """
    head = "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in headers) + "</tr>"
    body = "".join(
        "<tr>"
        + f"<td>{escape(key)}</td><td class='metric'>{html_value}</td>"
        + "</tr>"
        for key, html_value in rows
    )
    return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>\n"


def _render_trades(trades: list[TradeRecord]) -> str:
    if not trades:
        return "<p class='empty'>No trades recorded.</p>\n"
    head = "<tr><th>#</th><th>Time</th><th>Side</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th></tr>"
    body_rows = []
    for i, t in enumerate(trades[:_MAX_TRADE_ROWS], start=1):
        pnl_class = "positive" if t.pnl >= 0 else "negative"
        body_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{_fmt_ts(t.entry_ts)}</td>"
            f"<td>{escape(t.side)}</td>"
            f"<td class='metric'>{_fmt_decimal(t.entry_price)}</td>"
            f"<td class='metric'>{_fmt_decimal(t.exit_price)}</td>"
            f"<td class='metric'>{_fmt_decimal(t.quantity)}</td>"
            f"<td class='metric {pnl_class}'>{_fmt_decimal(t.pnl)}</td>"
            "</tr>"
        )
    more = (
        f"<p class='empty'>(+{len(trades) - _MAX_TRADE_ROWS} additional trades omitted)</p>\n"
        if len(trades) > _MAX_TRADE_ROWS
        else ""
    )
    return (
        "<table><thead>"
        + head
        + "</thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table>\n"
        + more
    )


def _render_breaches(breaches: list[BreachEvent]) -> str:
    if not breaches:
        return "<p class='empty'>No prop-firm rule breaches.</p>\n"
    head = (
        "<tr><th>Time</th><th>Rule</th><th>Current</th><th>Threshold</th><th>Message</th></tr>"
    )
    body_rows = []
    for b in breaches:
        body_rows.append(
            "<tr class='breach'>"
            f"<td>{_fmt_ts(b.ts)}</td>"
            f"<td>{escape(b.rule_name)}</td>"
            f"<td class='metric'>{_fmt_float(b.current_value)}</td>"
            f"<td class='metric'>{_fmt_float(b.threshold_value)}</td>"
            f"<td>{escape(b.message)}</td>"
            "</tr>"
        )
    return (
        "<table><thead>"
        + head
        + "</thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table>\n"
    )


def _render_equity_curve(
    equity_curve: list[tuple[object, Decimal]],
) -> str:
    """Render the equity curve as inline SVG. Empty curve → placeholder."""
    if len(equity_curve) < 2:
        return "<p class='empty'>Equity curve not available.</p>\n"

    width = 900
    height = 240
    margin = 30

    values = [float(v) for _, v in equity_curve]
    # A NaN or Inf in the equity curve would poison the SVG coordinates
    # and render an invisible / unbounded polyline. Surface it as a
    # visible placeholder instead of a mysterious blank curve.
    if not all(math.isfinite(v) for v in values):
        return "<p class='empty'>Equity curve contains non-finite values.</p>\n"
    n = len(values)
    v_min = min(values)
    v_max = max(values)
    v_range = v_max - v_min or 1.0

    def x_of(i: int) -> float:
        return margin + (width - 2 * margin) * (i / (n - 1))

    def y_of(v: float) -> float:
        return height - margin - (height - 2 * margin) * ((v - v_min) / v_range)

    points = " ".join(
        f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(values)
    )
    return (
        f"<svg width='{width}' height='{height}' xmlns='http://www.w3.org/2000/svg'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#fbfbfb'/>"
        f"<polyline fill='none' stroke='#2563eb' stroke-width='1.5' points='{points}'/>"
        f"<text x='{margin}' y='{height - 8}' font-size='11' fill='#666'>"
        f"min {v_min:.2f}</text>"
        f"<text x='{width - margin - 80}' y='{height - 8}' font-size='11' fill='#666'>"
        f"max {v_max:.2f}</text>"
        "</svg>\n"
    )
