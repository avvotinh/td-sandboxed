---
name: chart-viewer
description: How to run and use the chart-viewer service — the local FastAPI + lightweight-charts app that renders backtest results (candles, indicators, trades, SL/TP paths, equity) from Result Contract v2 JSONs. Use when inspecting backtest runs visually, comparing A/B runs, or working on services/chart-viewer/.
origin: Sandboxed
---

# Chart Viewer

FastAPI app local (Quyết định D2) đọc `results/*.json` (Result Contract v2) + parquet qua
`data_ref`. **KHÔNG cần Docker/TimescaleDB/Redis** — chạy thuần local (D6).
Service: `services/chart-viewer/`.

## How to run

```bash
cd services/chart-viewer
uv run chart-viewer --results-dir <repo-root>/results --port 8777
```

- URL: `http://127.0.0.1:8777/` — trang danh sách run (đọc metadata từ các `results/*.json`)
- Run cụ thể: `http://127.0.0.1:8777/run/<run-id>`
- So sánh A/B: `http://127.0.0.1:8777/compare?a=<run-id>&b=<run-id>`

Slash command tương đương: `/viewer [run-id]`.

## What it renders (all from the result JSON — see skill `result-contract`)

- **Candles + volume** — server đọc parquet qua `run.data_ref`, browser nhận JSON slice
- **Indicators** — overlays/panes render từ `indicators[]` đã ghi trong JSON.
  **NEVER recompute indicators trong viewer** — backtest đã ghi sẵn qua IndicatorRecorder;
  viewer chỉ vẽ series có sẵn. Thiếu indicator = fix ở backtest export, không phải ở viewer.
- **Entry/exit markers** per trade
- **SL/TP** ban đầu + **SL path** (breakeven/trailing ratchet) từ `trades[].sl_path`
- **Equity curve pane** từ `equity_curve[]`
- **Trade table** click-to-jump với PnL / R-multiple
- **Metrics summary** (win rate, PF, Sharpe, max DD)
- **/compare** — hai run A/B side-by-side

## Constraints

- Viewer là công cụ phân tích **offline** kết quả backtest — không phải real-time dashboard
- Chỉ đọc `schema_version: "2"` — version lạ phải fail loudly, không đoán
- `results/` gitignored — viewer không sinh artifact nào cần commit
- Front-end tái dùng từ commit `75bf832`: vendored `lightweight-charts v5.2.0`,
  template + `esc()` XSS-hardening — không kéo JS từ CDN

## Troubleshooting

- Run không hiện trong danh sách → check file có `schema_version: "2"` và nằm đúng
  `--results-dir` (mặc định trỏ `results/` ở repo root)
- Candles trống → `run.data_ref.manifest` trỏ parquet không tồn tại trên máy này
  (data paths là repo-root-relative; check env `TD_REPO_ROOT`)
- Port bận → đổi `--port`, nhớ in URL mới
