/*
 * chart-viewer front-end — draws one Result Contract v2 run.
 *
 * Adapted from the reverted single-file writer (commit 75bf832): here
 * the payload and candles arrive from the JSON API instead of being
 * inlined, and candles are OPTIONAL — synthetic runs have none on disk,
 * so markers fall back to an overlay indicator (or a trade-price line)
 * and the chart still renders indicators + trades + equity.
 *
 * All payload strings are DATA, not markup — esc() everything before it
 * touches innerHTML.
 */
"use strict";

(function () {
  const LWC = window.LightweightCharts;
  const runId = window.__RUN_ID__;

  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  const fmtPct = (x) => (x == null ? "–" : (100 * x).toFixed(1) + "%");
  const fmtMoney = (x) =>
    x == null ? "–" : (x < 0 ? "−$" : "$") +
      Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const fmtNum = (x, d) => (x == null ? "–" : Number(x).toFixed(d == null ? 2 : d));
  const fmtPx = (x) =>
    x == null ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: 5 });
  const pnlCls = (x) => ((x || 0) >= 0 ? "pos" : "neg");
  const fmtTime = (t) => new Date(t * 1000).toISOString().slice(2, 16).replace("T", " ");

  async function getJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(url + " → " + resp.status);
    return resp.json();
  }

  function fail(msg) {
    document.getElementById("note").textContent = msg;
    document.getElementById("note").style.color = "var(--red)";
  }

  Promise.all([
    getJSON("/api/run/" + encodeURIComponent(runId)),
    getJSON("/api/run/" + encodeURIComponent(runId) + "/candles"),
  ])
    .then(([payload, candleResp]) => render(payload, candleResp))
    .catch((err) => fail(String(err)));

  function render(DATA, candleResp) {
    const meta = DATA.meta;
    const candles = candleResp.candles || [];

    // ---- Header --------------------------------------------------------
    const win = (meta.start && meta.end)
      ? esc(meta.start.slice(0, 10)) + " → " + esc(meta.end.slice(0, 10)) : "";
    document.getElementById("header").innerHTML =
      '<h1><a href="/">runs</a> / ' + esc(meta.strategy) + " · " +
        esc(meta.symbol) + " " + esc(meta.timeframe) + "</h1>" +
      '<span class="stat">window <b>' + esc(meta.window) + "</b></span>" +
      '<span class="stat">' + win + "</span>" +
      '<span class="stat">net <b class="' + pnlCls(meta.netPnl) + '">' + fmtMoney(meta.netPnl) + "</b></span>" +
      '<span class="stat">trades <b>' + meta.tradeCount + "</b></span>" +
      '<span class="stat">win <b>' + fmtPct(meta.winRate) + "</b></span>" +
      '<span class="stat">PF <b>' + fmtNum(meta.profitFactor) + "</b></span>" +
      '<span class="stat">Sharpe <b>' + fmtNum(meta.sharpe, 3) + "</b></span>" +
      '<span class="stat">maxDD <b>' + fmtPct(meta.maxDdPct) + "</b></span>";
    if (candleResp.note) document.getElementById("note").textContent = candleResp.note;

    // ---- Chart ---------------------------------------------------------
    const chart = LWC.createChart(document.getElementById("chart"), {
      autoSize: true,
      layout: {
        background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc",
        panes: { separatorColor: "#2a2e39", enableResize: true },
      },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
      crosshair: { mode: 0 },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#2a2e39" },
      rightPriceScale: { borderColor: "#2a2e39" },
    });

    // Candle series (may be empty for synthetic runs).
    const candleSeries = chart.addSeries(LWC.CandlestickSeries, {
      upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
      wickUpColor: "#26a69a", wickDownColor: "#ef5350",
    });
    candleSeries.setData(candles);
    if (candles.length) {
      const volumeSeries = chart.addSeries(LWC.HistogramSeries, {
        priceScaleId: "volume", priceFormat: { type: "volume" },
        priceLineVisible: false, lastValueVisible: false,
      });
      chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      volumeSeries.setData(candles.map((c) => ({
        time: c.time, value: c.volume,
        color: c.close >= c.open ? "#26a69a44" : "#ef535044",
      })));
    }

    // ---- Indicators ----------------------------------------------------
    // Pane 0 = overlay; each distinct "lower" indicator gets its own pane.
    let nextPane = 1;
    let firstOverlay = null;
    DATA.indicators.forEach((ind) => {
      const overlay = ind.pane === "overlay" || ind.pane === "0" || ind.pane === 0;
      const paneIndex = overlay ? 0 : nextPane++;
      const series = chart.addSeries(LWC.LineSeries, {
        color: ind.color || "#2962ff", lineWidth: 1,
        title: ind.title, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      }, paneIndex);
      series.setData(ind.points || []);
      (ind.levels || []).forEach((level) => series.createPriceLine({
        price: level, color: "#787b86", lineWidth: 1, lineStyle: 1, axisLabelVisible: true,
      }));
      if (paneIndex === 0 && !firstOverlay && (ind.points || []).length) firstOverlay = series;
      if (paneIndex > 0) {
        const pane = chart.panes()[paneIndex];
        if (pane && pane.setHeight) pane.setHeight(110);
      }
    });

    // Markers must attach to a series that HAS data. Prefer candles, then
    // an overlay indicator, then a synthesized trade-price line.
    let anchor = candles.length ? candleSeries : firstOverlay;
    if (!anchor && DATA.trades.length) {
      anchor = chart.addSeries(LWC.LineSeries, {
        color: "#787b8688", lineWidth: 1, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false,
      });
      const seen = new Set();
      const pts = [];
      DATA.trades.forEach((tr) => {
        [[tr.entryTime, tr.entryPrice], [tr.exitTime, tr.exitPrice]].forEach(([t, p]) => {
          if (!seen.has(t)) { seen.add(t); pts.push({ time: t, value: p }); }
        });
      });
      pts.sort((a, b) => a.time - b.time);
      anchor.setData(pts);
    }

    // ---- SL step path + TP line (whitespace-gapped between trades) ------
    function buildLevelData(kind) {
      const data = [];
      let lastTime = -Infinity;
      const push = (item) => { if (item.time > lastTime) { data.push(item); lastTime = item.time; } };
      DATA.trades.forEach((tr) => {
        if (kind === "sl") {
          (tr.slPath || []).forEach((p) => push({ time: p.time, value: p.price }));
          if ((tr.slPath || []).length) push({ time: tr.exitTime + 1 });
        } else if (tr.tp != null) {
          push({ time: tr.entryTime, value: tr.tp });
          push({ time: tr.exitTime, value: tr.tp });
          push({ time: tr.exitTime + 1 });
        }
      });
      return data;
    }
    const slSeries = chart.addSeries(LWC.LineSeries, {
      color: "#ef5350", lineWidth: 1, lineStyle: 2, lineType: 1, title: "SL",
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    slSeries.setData(buildLevelData("sl"));
    const tpSeries = chart.addSeries(LWC.LineSeries, {
      color: "#26a69a", lineWidth: 1, lineStyle: 2, title: "TP",
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    tpSeries.setData(buildLevelData("tp"));

    // ---- Equity pane ---------------------------------------------------
    if (DATA.equity && DATA.equity.length) {
      const eqPane = nextPane++;
      const eqSeries = chart.addSeries(LWC.LineSeries, {
        color: "#ffb74d", lineWidth: 1, title: "equity",
        priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false,
      }, eqPane);
      eqSeries.setData(DATA.equity);
      const pane = chart.panes()[eqPane];
      if (pane && pane.setHeight) pane.setHeight(90);
    }

    // ---- Trade markers -------------------------------------------------
    if (anchor) {
      const markers = [];
      DATA.trades.forEach((tr, i) => {
        const buy = tr.side === "BUY" || tr.side === "LONG";
        markers.push({
          time: tr.entryTime, position: buy ? "belowBar" : "aboveBar",
          shape: buy ? "arrowUp" : "arrowDown", color: buy ? "#26a69a" : "#ef5350",
          text: (buy ? "L" : "S") + (i + 1),
        });
        markers.push({
          time: tr.exitTime, position: "inBar", shape: "circle",
          color: (tr.pnl || 0) >= 0 ? "#26a69a" : "#ef5350", text: "x" + (i + 1), size: 0.7,
        });
      });
      markers.sort((a, b) => a.time - b.time);
      LWC.createSeriesMarkers(anchor, markers);
    }

    // ---- Selected-trade connector --------------------------------------
    const connector = chart.addSeries(LWC.LineSeries, {
      color: "#2962ff", lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // ---- Trade list ----------------------------------------------------
    const tbody = document.createElement("tbody");
    DATA.trades.forEach((tr, i) => {
      const buy = tr.side === "BUY" || tr.side === "LONG";
      const row = document.createElement("tr");
      row.innerHTML =
        "<td>" + (i + 1) + " · " + fmtTime(tr.entryTime) + "</td>" +
        '<td><span class="badge ' + (buy ? "buy" : "sell") + '">' + esc(tr.side) + "</span></td>" +
        '<td class="' + pnlCls(tr.pnl) + '">' + fmtNum(tr.pnl, 0) + "</td>";
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
      const span = Math.max(tr.exitTime - tr.entryTime, 60);
      chart.timeScale().setVisibleRange({ from: tr.entryTime - span * 2, to: tr.exitTime + span * 2 });
      connector.setData([
        { time: tr.entryTime, value: tr.entryPrice },
        { time: tr.exitTime, value: tr.exitPrice },
      ]);
      connector.applyOptions({ color: (tr.pnl || 0) >= 0 ? "#26a69a" : "#ef5350" });
      const moves = (tr.slPath || []).length;
      document.getElementById("detail").innerHTML =
        '<div class="row"><span>trade</span><b>#' + (i + 1) + " " + esc(tr.id) + "</b></div>" +
        '<div class="row"><span>side / qty</span><b>' + esc(tr.side) + " · " + esc(tr.quantity) + "</b></div>" +
        '<div class="row"><span>entry</span><b>' + fmtPx(tr.entryPrice) + " @ " + fmtTime(tr.entryTime) + "</b></div>" +
        '<div class="row"><span>exit</span><b>' + fmtPx(tr.exitPrice) + " @ " + fmtTime(tr.exitTime) + "</b></div>" +
        '<div class="row"><span>SL initial' + (moves > 1 ? " (+" + (moves - 1) + " moves)" : "") + "</span><b>" + fmtPx(tr.sl) + "</b></div>" +
        '<div class="row"><span>TP</span><b>' + fmtPx(tr.tp) + "</b></div>" +
        '<div class="row"><span>R</span><b>' + fmtNum(tr.rMultiple, 2) + "</b></div>" +
        '<div class="row"><span>PnL</span><b class="' + pnlCls(tr.pnl) + '">' + fmtNum(tr.pnl, 2) + "</b></div>";
    }

    // ---- OHLC legend ---------------------------------------------------
    const legend = document.getElementById("legend");
    chart.subscribeCrosshairMove((param) => {
      const bar = param.seriesData && param.seriesData.get(candleSeries);
      if (!bar || bar.open == null) { legend.textContent = ""; return; }
      legend.textContent = "O " + bar.open + "  H " + bar.high + "  L " + bar.low + "  C " + bar.close;
    });

    chart.timeScale().fitContent();
  }
})();
