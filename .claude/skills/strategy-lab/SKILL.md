---
name: strategy-lab
description: How to run the v2 research loop in services/trading-engine — backtest run/sweep/walkforward/ab CLI, job YAML anatomy, Contract v2 export, and validation discipline (WF fixed-params, OOS reserve, promotion gate D7). Use when running backtests, parameter sweeps, walk-forward analyses, or A/B comparisons.
origin: Sandboxed
---

# Strategy Lab — research loop v2

Vòng lặp research: sửa chiến lược → backtest → xem chart → verdict. Chạy hoàn toàn local,
**KHÔNG cần Docker/TimescaleDB/Redis** (Quyết định D6) — data là Parquet, output là JSON.
CLI source: `services/trading-engine/src/lab/cli.py`.

## Invocation

Tất cả lệnh chạy từ `services/trading-engine/`:

```bash
cd services/trading-engine
uv run python -m src backtest <run|sweep|walkforward|ab> [flags]
```

## `backtest run` — point backtest

```bash
uv run python -m src backtest run --job configs/backtest/<job>.yaml --export ../../results/
```

| Flag | Ý nghĩa |
|---|---|
| `--job / -j <yaml>` | Job YAML (bắt buộc) |
| `--export <path>` | Ghi **Result Contract v2** JSON. Directory (hoặc path kết thúc `/`) → `<run_id>.json` bên trong; path khác → ghi đúng file |
| `--json` | In JSON summary ra stdout thay vì bảng human-readable |
| `--out <file>` | Ghi JSON summary ra file (`.html` → HTML report) |

Luôn export vào `results/` ở **repo root** (gitignored) — từ `services/trading-engine/`
là `../../results/`. Xem skill `result-contract` cho schema + run_id format.

## `backtest sweep` — grid/random parameter sweep

```bash
uv run python -m src backtest sweep --job <job.yaml> --grid <grid.yaml> \
  --search grid --workers 4 --out sweep-out/
```

| Flag | Ý nghĩa |
|---|---|
| `--job / -j`, `--grid / -g` | Job YAML + grid YAML (mapping `param_name: [values...]`) |
| `--search` | `grid` (default) \| `random` |
| `--n-iter` | Số iteration cho random search |
| `--workers` | Số process song song (default 1) |
| `--seed` | Random seed (default 42) — giữ cố định để reproducible |
| `--early-stop-metric` / `--early-stop-threshold` | Skip-record combos vượt ngưỡng (vd `max_overall_dd_pct`) |
| `--out` | JSON output (file `.json` hoặc directory → `sweep.json`) |

## `backtest walkforward` — WF optimization + OOS eval

```bash
uv run python -m src backtest walkforward --job <job.yaml> --grid <grid.yaml> \
  --start 2024-01-01 --end 2026-01-01 --train 90d --test 30d --step 30d \
  --mode anchored --workers 4 --out wf-out/
```

| Flag | Ý nghĩa |
|---|---|
| `--start` / `--end` | ISO dates — tổng window |
| `--train` / `--test` / `--step` | Durations, vd `90d`, `30d` |
| `--mode` | `anchored` (default) \| `rolling` |
| `--search`, `--n-iter`, `--workers`, `--seed` | Như sweep |
| `--out` | JSON (file hoặc directory → `walkforward.json`) |

## `backtest ab` — side-by-side comparison

```bash
uv run python -m src backtest ab --baseline <base.yaml> --variant <var.yaml> --out ab.json
```

Hai job phải cùng dataset + venue; chỉ strategy params khác nhau. Output: metric deltas
+ winner-R-multiple distribution.

## Job YAML anatomy

Ví dụ thật: `services/trading-engine/configs/backtest/epic13-donchian-baseline-m5.yaml`.
Schema: `BacktestJobConfig` (`src/lab/job_config.py`) — Pydantic, `extra="forbid"`.

```yaml
strategy: donchian_breakout          # phải có trong strategy registry
instrument_symbol: XAUUSD            # whitelist trong job_config.py (_SUPPORTED_SYMBOLS)
bar_type_suffix: 5-MINUTE-LAST-EXTERNAL
venue:
  name: SIM
  starting_balance: "100000"         # Decimal → quote string
  currency: USD
  commission_per_lot_usd: "0"        # fee model — set số thật cho firm-bound jobs
  oms_type: HEDGING                  # HEDGING cho phân tích per-trade R; NETTING là default
strategy_params:                     # snapshot đầy đủ vào Contract v2 run.params
  channel_period: 20
  atr_period: 14
  risk_percent: "0.5"
data:
  kind: parquet                      # parquet | synthetic | timescale
  path: data/historical/XAUUSD/M5/in_sample.parquet
# prop_firm:                         # optional — compliance wiring
#   preset_path: configs/firms/ftmo.yaml
#   account_id: test
# start / end:                       # optional ISO — narrow window (WF folds dùng cái này)
```

**Data paths là repo-root-relative**: path tương đối resolve từ repo root (walk up tới `.git`;
override bằng env `TD_REPO_ROOT`) — không phụ thuộc CWD. Path tuyệt đối giữ nguyên.

## Validation discipline (không thương lượng)

1. **OOS reserve untouched** — tuning chỉ trên in-sample; cửa sổ `oos_reserve` chỉ được
   đọc MỘT lần để đánh giá, không bao giờ để re-pick params.
2. **Walk-forward fixed-params** — WF pass nghĩa là params cố định sống qua các fold OOS;
   per-fold re-tuning trình bày như validation là leakage.
3. **Promotion gate D7** (`docs/v2/decisions.md`): OOS Sharpe ≥ 0.8 + WF pass + DD chấp nhận
   được → mới bật FTMO layer. Không nới gate.
4. **Verdicts → `docs/v2/studies/<slug>-<yyyy-mm-dd>.md`**, mọi số liệu kèm `run_id`
   (dùng `backtest-analyst` agent).
5. **Anti-lookahead**: mọi entry model MỚI phải kèm test chứng minh chỉ dùng dữ liệu ≤ t
   (không đọc bar tương lai, không dùng close của bar chưa đóng, không full-series
   scaling/centered rolling) — xem `.claude/rules/common/sandboxed-domain.md`. Chạy
   `quant-reviewer` agent trước khi tin kết quả backtest của model mới.

## After a run

- Soi chart: skill `chart-viewer` / `/viewer <run-id>`
- Sinh verdict: `backtest-analyst` agent / `/study <slug>`
