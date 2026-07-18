# chart-viewer

Local FastAPI viewer for **Result Contract v2** backtest runs — candles,
indicators, entry/exit markers, SL step-path + TP levels, equity curve,
and a click-to-jump trade table, drawn with a vendored
[lightweight-charts](https://github.com/tradingview/lightweight-charts)
v5.2.0 bundle.

No Docker / TimescaleDB / Redis — it reads `results/*.json` (and the
parquet each run references) straight off disk (v2 Decision D6).

## Run

```bash
cd services/chart-viewer
uv run chart-viewer --results-dir ../../results --port 8777
# → http://127.0.0.1:8777/
```

- `/` — run list (metadata + headline metrics from every `results/*.json`)
- `/run/<run_id>` — one run's chart
- `/compare?a=<run_id>&b=<run_id>` — two runs side by side

Slash-command equivalent: `/viewer [run-id]`.

## What it draws

Everything comes from the result JSON (see the `result-contract` skill),
**except candles**, which are read from the parquet at `run.data_ref`:

| Element | Source |
|---|---|
| Candles + volume | parquet at `run.data_ref.manifest` (repo-root-relative) |
| Indicators (overlay + panes) | `indicators[]` — **never recomputed** in the viewer |
| Entry/exit markers, SL path, TP | `trades[]` |
| Equity curve pane | `equity_curve[]` |
| Headline metrics | `metrics` (win rate, PF, Sharpe, max DD) |

Synthetic runs (`data_ref.manifest` = `synthetic:…`) have no parquet on
disk, so candles are unavailable — the chart still renders indicators,
trades, and equity, and shows the reason in the top-right note.

## Constraints

- Reads `schema_version: "2"` only — foreign versions fail loudly, no guessing.
- Offline analysis tool, not a real-time dashboard.
- `results/` is gitignored; the viewer produces no committed artifacts.
- Vendored JS only — no CDN. Re-download
  `src/chart_viewer/static/lightweight-charts.standalone.production.js`
  (v5.x, Apache-2.0) if it goes missing.

## Troubleshooting

- **Run missing from the list** → confirm the file has `schema_version: "2"`
  and lives in `--results-dir`. Skipped files are listed under the table.
- **Candles empty** → synthetic run, or `data_ref.manifest` parquet is not
  on this machine. Data paths are repo-root-relative; set `TD_REPO_ROOT`
  if the repo root can't be auto-detected.
- **Port busy** → change `--port`; the printed URL updates.

## Develop

```bash
uv run pytest          # unit + API tests
uv run ruff check .
```
