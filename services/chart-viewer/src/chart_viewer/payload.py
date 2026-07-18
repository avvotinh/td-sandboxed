"""Viewer payload builder — Result Contract v2 JSON → chart-ready shapes.

Port of the serialization half of the reverted
``src/backtesting/reports/chart_data.py`` (commit ``75bf832``), adapted
to consume Contract v2 dicts instead of live ``TradeRecord`` objects.
Indicators are passed through verbatim — the viewer NEVER recomputes
them (Decision D2 / architecture §3.3).

Everything here is pure transformation — no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .metrics import fallback_net_pnl, fallback_win_rate


def iso_to_epoch(ts: str) -> int:
    """ISO-8601 timestamp → epoch seconds (UTC assumed when naive)."""
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _sl_path(trade: dict[str, Any], entry_t: int, exit_t: int) -> list[dict[str, Any]]:
    """Step path of the SL level over the trade's lifetime.

    Starts at the initial bracket SL, walks each recorded modification
    (clamped into the trade window, same-time writes collapse to the
    last one, consecutive duplicate prices dropped), and carries the
    final level to the exit timestamp so the step line spans the full
    trade. Times must end up strictly ascending — duplicate times break
    lightweight-charts ``setData``.
    """
    sl = trade.get("sl")
    if sl is None:
        return []
    path: list[dict[str, Any]] = [{"time": entry_t, "price": float(sl)}]
    for update in trade.get("sl_path") or []:
        t = min(max(iso_to_epoch(update["ts"]), entry_t), exit_t)
        price = float(update["price"])
        if t <= path[-1]["time"]:
            # Same-bar modifications (BE move + trail ratchet on one
            # on_bar call) collapse to the last write.
            path[-1] = {"time": path[-1]["time"], "price": price}
            continue
        if price == path[-1]["price"]:
            continue
        path.append({"time": t, "price": price})
    if path[-1]["time"] < exit_t:
        path.append({"time": exit_t, "price": path[-1]["price"]})
    return path


def trades_to_payload(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Contract v2 trade rows → chart rows sorted by entry time."""
    rows = []
    for trade in trades:
        entry = trade.get("entry") or {}
        exit_ = trade.get("exit") or {}
        entry_t = iso_to_epoch(entry["ts"])
        exit_t = iso_to_epoch(exit_["ts"])
        quantity = trade.get("quantity_lots", trade.get("quantity_units"))
        rows.append(
            {
                "id": str(trade.get("trade_id", "?")),
                "side": str(trade.get("side", "?")),
                "entryTime": entry_t,
                "exitTime": exit_t,
                "entryPrice": float(entry["price"]),
                "exitPrice": float(exit_["price"]),
                "entryReason": entry.get("reason"),
                "exitReason": exit_.get("reason"),
                "quantity": float(quantity) if quantity is not None else None,
                "pnl": float(trade.get("pnl") or 0.0),
                "rMultiple": trade.get("r_multiple"),
                "sl": float(trade["sl"]) if trade.get("sl") is not None else None,
                "tp": float(trade["tp"]) if trade.get("tp") is not None else None,
                "slPath": _sl_path(trade, entry_t, exit_t),
            }
        )
    rows.sort(key=lambda r: (r["entryTime"], r["id"]))
    return rows


def equity_to_payload(equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Equity curve → line points; same-ts writes collapse to the last."""
    deduped: dict[int, float] = {}
    for point in equity_curve:
        deduped[iso_to_epoch(point["ts"])] = float(point["equity"])
    return [{"time": t, "value": v} for t, v in sorted(deduped.items())]


def indicators_to_payload(indicators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pass indicators through verbatim (already chart-shaped in the JSON).

    ``points[].time`` is already epoch seconds per the contract; only
    the envelope keys the front-end relies on are normalized.
    """
    out = []
    for series in indicators:
        out.append(
            {
                "key": str(series.get("key", "?")),
                "title": str(series.get("title", series.get("key", "?"))),
                "pane": str(series.get("pane", "overlay")),
                "color": str(series.get("color", "#2962ff")),
                "points": series.get("points") or [],
                "levels": series.get("levels") or [],
            }
        )
    return out


def _headline_metrics(data: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Net pnl / win rate / PF / Sharpe / max DD, tolerating null metrics."""
    metrics = data.get("metrics") or {}
    pnl_m = metrics.get("pnl") or {}
    risk = metrics.get("risk") or {}
    trades_m = metrics.get("trades") or {}
    drawdown = metrics.get("drawdown") or {}
    account = data.get("account") or {}

    net_pnl = fallback_net_pnl(account, pnl_m)
    win_rate = fallback_win_rate(trades, trades_m)
    return {
        "netPnl": net_pnl,
        "tradeCount": len(trades),
        "winRate": win_rate,
        "profitFactor": pnl_m.get("profit_factor"),
        "sharpe": risk.get("sharpe_ratio"),
        "maxDdPct": drawdown.get("max_overall_dd_pct"),
    }


def build_run_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Full viewer payload for one run — everything except candles.

    Candles are served separately (``/api/run/{id}/candles``) because
    they come from the parquet referenced by ``run.data_ref``, not
    from the result JSON.
    """
    run = data.get("run") or {}
    window = run.get("window") or {}
    account = data.get("account") or {}
    trades = trades_to_payload(data.get("trades") or [])
    meta: dict[str, Any] = {
        "runId": run.get("run_id"),
        "strategy": run.get("strategy"),
        "symbol": run.get("symbol"),
        "timeframe": run.get("timeframe"),
        "window": window.get("name"),
        "start": window.get("start"),
        "end": window.get("end"),
        "params": run.get("params") or {},
        "dataRef": run.get("data_ref") or {},
        "initialBalance": account.get("initial_balance"),
        "finalBalance": account.get("final_balance"),
        "currency": account.get("currency"),
    }
    meta.update(_headline_metrics(data, trades))
    return {
        "meta": meta,
        "trades": trades,
        "indicators": indicators_to_payload(data.get("indicators") or []),
        "equity": equity_to_payload(data.get("equity_curve") or []),
        "metrics": data.get("metrics"),
        "breaches": data.get("breaches") or [],
    }
