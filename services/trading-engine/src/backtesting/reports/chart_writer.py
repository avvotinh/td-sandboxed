"""Self-contained HTML chart report — TradingView Lightweight Charts.

Renders the payload from :mod:`src.backtesting.reports.chart_data` into
a single offline HTML file: candlesticks + volume, per-trade entry/exit
markers, initial-SL / TP levels, the SL modification path (breakeven +
trailing ratchets), strategy indicator overlays, and a click-to-jump
trade list.

The vendored ``lightweight-charts.standalone.production.js`` (v5.2.0,
Apache-2.0, license header retained inside the bundle) is inlined so
the report opens with no network access. Follows the same write-guard
conventions as :mod:`src.backtesting.reports.html_writer` (no ``..``
traversal, UTF-8).
"""

from __future__ import annotations

import html
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_LIB_FILENAME = "lightweight-charts.standalone.production.js"


@lru_cache(maxsize=1)
def _library_js() -> str:
    """The vendored lightweight-charts bundle (cached read)."""
    lib_path = _ASSET_DIR / _LIB_FILENAME
    if not lib_path.is_file():
        raise FileNotFoundError(
            f"Vendored chart library missing at {lib_path} — re-download "
            "lightweight-charts.standalone.production.js (v5.x) into "
            "src/backtesting/reports/assets/."
        )
    return lib_path.read_text(encoding="utf-8")


def _payload_json(payload: dict[str, Any]) -> str:
    """Compact JSON, safe to embed inside a ``<script>`` block."""
    return json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")


def render_chart_html(payload: dict[str, Any]) -> str:
    """Render the full standalone HTML document for ``payload``."""
    meta = payload.get("meta", {})
    title = (
        f"{meta.get('strategy', '?')} · {meta.get('symbol', '?')} "
        f"{meta.get('timeframe', '')} · {meta.get('window', '')}"
    )
    return (
        _TEMPLATE
        .replace("__TITLE__", html.escape(title))
        .replace("__LIB_JS__", _library_js())
        .replace("__PAYLOAD_JSON__", _payload_json(payload))
    )


def write_chart_html(payload: dict[str, Any], path: Path) -> Path:
    """Render and write the chart report to ``path`` (UTF-8)."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError(
            f"Path traversal via '..' not allowed in output path: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_chart_html(payload), encoding="utf-8")
    return path


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #131722; --panel: #1e222d; --border: #2a2e39;
    --text: #d1d4dc; --muted: #787b86;
    --green: #26a69a; --red: #ef5350; --amber: #ffb74d;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    background: var(--bg); color: var(--text);
    font: 13px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
    padding: 8px 14px; background: var(--panel);
    border-bottom: 1px solid var(--border);
  }
  header h1 { font-size: 15px; font-weight: 600; }
  header .stat { color: var(--muted); }
  header .stat b { color: var(--text); font-weight: 600; }
  .pos { color: var(--green); } .neg { color: var(--red); }
  main { display: flex; flex: 1; min-height: 0; }
  #chart { flex: 1; min-width: 0; }
  aside {
    width: 330px; display: flex; flex-direction: column;
    background: var(--panel); border-left: 1px solid var(--border);
  }
  aside h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); padding: 10px 12px 6px;
  }
  #trades { flex: 1; overflow-y: auto; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 4px 8px; text-align: right; white-space: nowrap; }
  th {
    position: sticky; top: 0; background: var(--panel);
    color: var(--muted); font-weight: 500; font-size: 11px;
    border-bottom: 1px solid var(--border);
  }
  th:first-child, td:first-child { text-align: left; }
  tbody tr { cursor: pointer; border-bottom: 1px solid #ffffff08; }
  tbody tr:hover { background: #2a2e3966; }
  tbody tr.sel { background: #2962ff33; }
  .badge {
    display: inline-block; min-width: 34px; text-align: center;
    padding: 0 5px; border-radius: 3px; font-size: 11px; font-weight: 600;
  }
  .badge.buy { background: #26a69a33; color: var(--green); }
  .badge.sell { background: #ef535033; color: var(--red); }
  #detail {
    border-top: 1px solid var(--border); padding: 10px 12px;
    font-size: 12px; min-height: 116px;
  }
  #detail .row { display: flex; justify-content: space-between; padding: 1px 0; }
  #detail .row span:first-child { color: var(--muted); }
  #legend {
    position: absolute; z-index: 10; top: 8px; left: 12px;
    font-size: 12px; color: var(--muted); pointer-events: none;
    text-shadow: 0 1px 2px #000;
  }
  .chart-wrap { position: relative; flex: 1; min-width: 0; display: flex; }
</style>
</head>
<body>
<header id="header"></header>
<main>
  <div class="chart-wrap">
    <div id="legend"></div>
    <div id="chart"></div>
  </div>
  <aside>
    <h2>Trades</h2>
    <div id="trades"></div>
    <div id="detail"><span style="color:var(--muted)">Click a trade to inspect entry / SL / TP.</span></div>
  </aside>
</main>
<script>__LIB_JS__</script>
<script id="chart-data" type="application/json">__PAYLOAD_JSON__</script>
<script>
(function () {
  "use strict";
  const LWC = window.LightweightCharts;
  const DATA = JSON.parse(document.getElementById("chart-data").textContent);
  const meta = DATA.meta;

  // ---- Header ----------------------------------------------------------
  // Payload strings are data, not markup — escape EVERYTHING that is
  // interpolated into innerHTML (the JSON embed only protects the
  // <script> block, not the DOM).
  const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
  const fmtPct = (x) => (x == null ? "–" : (100 * x).toFixed(1) + "%");
  const fmtMoney = (x) =>
    (x < 0 ? "−$" : "$") + Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const pnlCls = (x) => (x >= 0 ? "pos" : "neg");
  document.getElementById("header").innerHTML =
    '<h1>' + esc(meta.strategy) + ' · ' + esc(meta.symbol) + ' ' + esc(meta.timeframe) + '</h1>' +
    '<span class="stat">window <b>' + esc(meta.window) + '</b></span>' +
    '<span class="stat">' + esc(meta.start.slice(0, 10)) + ' → ' + esc(meta.end.slice(0, 10)) + '</span>' +
    '<span class="stat">PnL <b class="' + pnlCls(meta.pnl) + '">' + fmtMoney(meta.pnl) + '</b></span>' +
    '<span class="stat">trades <b>' + meta.tradeCount + '</b></span>' +
    '<span class="stat">win <b>' + fmtPct(meta.winRate) + '</b></span>';

  // ---- Chart -----------------------------------------------------------
  const chart = LWC.createChart(document.getElementById("chart"), {
    autoSize: true,
    layout: {
      background: { type: "solid", color: "#131722" },
      textColor: "#d1d4dc",
      panes: { separatorColor: "#2a2e39", enableResize: true },
    },
    grid: {
      vertLines: { color: "#1e222d" },
      horzLines: { color: "#1e222d" },
    },
    crosshair: { mode: 0 },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#2a2e39" },
    rightPriceScale: { borderColor: "#2a2e39" },
  });

  const candleSeries = chart.addSeries(LWC.CandlestickSeries, {
    upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
    wickUpColor: "#26a69a", wickDownColor: "#ef5350",
  });
  candleSeries.setData(DATA.candles);

  const volumeSeries = chart.addSeries(LWC.HistogramSeries, {
    priceScaleId: "volume", priceFormat: { type: "volume" },
    priceLineVisible: false, lastValueVisible: false,
  });
  chart.priceScale("volume").applyOptions({
    scaleMargins: { top: 0.85, bottom: 0 },
  });
  volumeSeries.setData(DATA.candles.map((c) => ({
    time: c.time, value: c.volume,
    color: c.close >= c.open ? "#26a69a44" : "#ef535044",
  })));

  // ---- Indicators ------------------------------------------------------
  let nextPane = 1;
  DATA.indicators.forEach((ind) => {
    const paneIndex = ind.pane === "lower" ? nextPane++ : 0;
    const series = chart.addSeries(LWC.LineSeries, {
      color: ind.color, lineWidth: ind.lineWidth, lineStyle: ind.lineStyle,
      title: ind.title, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false,
    }, paneIndex);
    series.setData(ind.points);
    ind.levels.forEach((level) => series.createPriceLine({
      price: level, color: "#787b86", lineWidth: 1, lineStyle: 1,
      axisLabelVisible: true,
    }));
    if (paneIndex > 0) {
      const pane = chart.panes()[paneIndex];
      if (pane && pane.setHeight) pane.setHeight(110);
    }
  });

  // ---- Trade levels: SL step path + TP line (whitespace-gapped) --------
  // One shared series per level kind; a whitespace item 1s after each
  // trade's exit breaks the line before the next trade starts.
  function buildLevelData(kind) {
    const data = [];
    let lastTime = -Infinity;
    const push = (item) => {
      if (item.time > lastTime) { data.push(item); lastTime = item.time; }
    };
    DATA.trades.forEach((tr) => {
      if (kind === "sl") {
        tr.slPath.forEach((p) => push({ time: p.time, value: p.price }));
        if (tr.slPath.length) push({ time: tr.exitTime + 1 });
      } else if (tr.tp != null) {
        push({ time: tr.entryTime, value: tr.tp });
        push({ time: tr.exitTime, value: tr.tp });
        push({ time: tr.exitTime + 1 });
      }
    });
    return data;
  }
  const slSeries = chart.addSeries(LWC.LineSeries, {
    color: "#ef5350", lineWidth: 1, lineStyle: 2, lineType: 1,
    title: "SL", priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
  slSeries.setData(buildLevelData("sl"));
  const tpSeries = chart.addSeries(LWC.LineSeries, {
    color: "#26a69a", lineWidth: 1, lineStyle: 2,
    title: "TP", priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
  tpSeries.setData(buildLevelData("tp"));

  // ---- Trade markers ---------------------------------------------------
  const markers = [];
  DATA.trades.forEach((tr, i) => {
    const buy = tr.side === "BUY";
    markers.push({
      time: tr.entryTime,
      position: buy ? "belowBar" : "aboveBar",
      shape: buy ? "arrowUp" : "arrowDown",
      color: buy ? "#26a69a" : "#ef5350",
      text: (buy ? "L" : "S") + (i + 1),
    });
    markers.push({
      time: tr.exitTime,
      position: "inBar",
      shape: "circle",
      color: tr.pnl >= 0 ? "#26a69a" : "#ef5350",
      text: "x" + (i + 1),
      size: 0.7,
    });
  });
  markers.sort((a, b) => a.time - b.time);
  LWC.createSeriesMarkers(candleSeries, markers);

  // ---- Selected-trade connector ----------------------------------------
  const connector = chart.addSeries(LWC.LineSeries, {
    color: "#2962ff", lineWidth: 2, lineStyle: 0,
    priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false,
  });

  // ---- Trade list ------------------------------------------------------
  const fmtTime = (t) => {
    const d = new Date(t * 1000);
    return d.toISOString().slice(2, 16).replace("T", " ");
  };
  const tbody = document.createElement("tbody");
  DATA.trades.forEach((tr, i) => {
    const row = document.createElement("tr");
    row.innerHTML =
      "<td>" + (i + 1) + " · " + fmtTime(tr.entryTime) + "</td>" +
      '<td><span class="badge ' + (tr.side === "BUY" ? "buy" : "sell") + '">' + esc(tr.side) + "</span></td>" +
      '<td class="' + pnlCls(tr.pnl) + '">' + tr.pnl.toFixed(0) + "</td>";
    row.addEventListener("click", () => selectTrade(i, row));
    tbody.appendChild(row);
  });
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>entry (UTC)</th><th>side</th><th>pnl</th></tr></thead>";
  table.appendChild(tbody);
  document.getElementById("trades").appendChild(table);

  let selectedRow = null;
  function selectTrade(i, row) {
    const tr = DATA.trades[i];
    if (selectedRow) selectedRow.classList.remove("sel");
    row.classList.add("sel");
    selectedRow = row;
    const span = Math.max(tr.exitTime - tr.entryTime, 1);
    chart.timeScale().setVisibleRange({
      from: tr.entryTime - span * 2,
      to: tr.exitTime + span * 2,
    });
    connector.setData([
      { time: tr.entryTime, value: tr.entryPrice },
      { time: tr.exitTime, value: tr.exitPrice },
    ]);
    connector.applyOptions({ color: tr.pnl >= 0 ? "#26a69a" : "#ef5350" });
    const fmtPx = (x) => (x == null ? "–" : x.toLocaleString("en-US", { maximumFractionDigits: 5 }));
    document.getElementById("detail").innerHTML =
      '<div class="row"><span>trade</span><b>#' + (i + 1) + " " + esc(tr.id) + "</b></div>" +
      '<div class="row"><span>side / qty</span><b>' + esc(tr.side) + " · " + tr.quantity + "</b></div>" +
      '<div class="row"><span>entry</span><b>' + fmtPx(tr.entryPrice) + " @ " + fmtTime(tr.entryTime) + "</b></div>" +
      '<div class="row"><span>exit</span><b>' + fmtPx(tr.exitPrice) + " @ " + fmtTime(tr.exitTime) + "</b></div>" +
      '<div class="row"><span>SL initial' + (tr.slPath.length > 1 ? " (+" + (tr.slPath.length - 1) + " moves)" : "") + "</span><b>" + fmtPx(tr.sl) + "</b></div>" +
      '<div class="row"><span>TP</span><b>' + fmtPx(tr.tp) + "</b></div>" +
      '<div class="row"><span>PnL</span><b class="' + pnlCls(tr.pnl) + '">' + tr.pnl.toFixed(2) + "</b></div>";
  }

  // ---- OHLC legend -----------------------------------------------------
  const legend = document.getElementById("legend");
  chart.subscribeCrosshairMove((param) => {
    const bar = param.seriesData && param.seriesData.get(candleSeries);
    if (!bar) { legend.textContent = ""; return; }
    legend.textContent =
      "O " + bar.open + "  H " + bar.high + "  L " + bar.low + "  C " + bar.close;
  });

  chart.timeScale().fitContent();
})();
</script>
</body>
</html>
"""
