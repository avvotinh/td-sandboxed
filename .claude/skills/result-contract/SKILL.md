---
name: result-contract
description: Source of truth for Result Contract v2 — the versioned JSON schema every backtest run exports and every consumer (chart-viewer, backtest-analyst, study tooling) reads. Use when reading/writing result JSONs, changing the export schema, or building anything that consumes results/*.json.
origin: Sandboxed
---

# Result Contract v2

Một schema JSON duy nhất, versioned — keystone của research loop v2
(`docs/v2/01-architecture.md` §4). Writer: `services/trading-engine/src/backtesting/export/result_writer.py`
(sẽ move vào `lab/export/` ở P3). Readers: chart-viewer, `backtest-analyst` agent, study scripts.

## Where files live

- `results/` ở **repo root**, **gitignored** (file lớn) — KHÔNG commit result JSON
- Một run = một file: `results/<run_id>.json`
- Verdict markdown trong `docs/v2/studies/` reference run bằng `run_id` — đó là artifact bền

## run_id format

```
<strategy>-<symbol>-<tf>-<YYYYMMDD-HHMMSS>
```

Ví dụ: `donchian_breakout-xauusd-m5-20260714-153000`. UTC timestamp, lowercase,
symbol sanitized cho filesystem (`EUR/USD` → `eurusd`). Generator: `make_run_id()` trong
`export/result_writer.py`.

## How to export

```bash
cd services/trading-engine
uv run python -m src backtest run --job <job.yaml> --export <repo-root>/results/
# → "Contract v2 result written to results/<run_id>.json (run_id=...)"
```

`--export` nhận directory (hoặc path kết thúc bằng `/`) → ghi `<run_id>.json` bên trong;
path khác → ghi đúng file đó. Sweep/WF emit file tổng hợp riêng (`--out`); từng cell/fold
có thể xuất full Contract v2 khi cần soi chart.

## Schema (schema_version "2")

```jsonc
{
  "schema_version": "2",
  "run": {
    "run_id": "donchian-xauusd-m5-20260714-153000",
    "strategy": "donchian_breakout", "symbol": "XAUUSD", "timeframe": "M5",
    "window": {"name": "in_sample", "start": "...", "end": "..."},
    "params": { /* strategy_params snapshot đầy đủ */ },
    "data_ref": {"manifest": "manifests/xauusd-2y.json", "entry": "in_sample/M5",
                  "fingerprint": "sha256_short"},
    "engine": {"nautilus_version": "...", "commit": "..."}
  },
  "account": {"initial_balance": 100000, "final_balance": 103200, "currency": "USD",
               "risk_profile": "demo"},
  "trades": [{
    "trade_id": "...", "side": "LONG",
    "entry": {"ts": "...", "price": 2031.5, "kind": "market", "reason": "donchian_upper_cross"},
    "exit":  {"ts": "...", "price": 2035.1, "reason": "tp"},
    "quantity_lots": 0.12, "pnl": 432.0, "r_multiple": 1.85,
    "sl": 2029.2, "tp": 2036.1,
    "sl_path": [{"ts": "...", "price": 2031.5, "reason": "breakeven"}]
  }],
  "equity_curve": [{"ts": "...", "equity": 100000.0}],
  "indicators": [{"key": "supertrend_up", "title": "Supertrend", "pane": "overlay",
                   "color": "#22c55e", "points": [{"time": 1718000000, "value": 2030.1}],
                   "levels": []}],
  "metrics": { /* PropFirmMetricsSchema model_dump — pnl, drawdown, risk, trades, prop_firm_compliance */ },
  "breaches": [ /* chỉ khi compliance bật */ ]
}
```

Notes on the real writer output:

- `r_multiple` là price-based: `(exit−entry)/(entry−sl)` cho LONG (ngược lại cho SHORT);
  `null` khi thiếu SL hoặc risk ≤ 0
- `sl_path` là lịch sử modify SL (breakeven/trailing ratchet), dedup theo timestamp
- `quantity_lots` khi symbol có contract spec; fallback `quantity_units` khi không
- `indicators[].points[].time` là epoch seconds (khớp lightweight-charts); `equity_curve`/`trades` dùng ISO timestamps
- `metrics` là `PropFirmMetricsSchema.model_dump(mode="json")` — giữ nguyên schema metrics hiện có

## Versioning rule

- MỌI thay đổi schema → bump `SCHEMA_VERSION` trong `export/result_writer.py`
  **và** ghi một mục vào `docs/v2/decisions.md`
- Reader phải check `schema_version` và fail loudly với version lạ — không đoán

## Known gaps (see decisions.md "Known gaps sau P1")

- `trades[].entry.reason` / `exit.reason` / `sl_path[].reason` hiện là `null` —
  Nautilus không giữ lý do entry/exit; wiring reason thật qua `TradeRecord` là follow-up
  khi viewer P2 cần. Đừng coi đây là data loss khi phân tích.
- Compliance vẫn đánh giá trên realized balance; `equity_curve` LÀ mark-to-market
  (từ `EquityRecorderActor`) — hai thứ khác nhau, đừng đối chiếu 1:1.

## Discipline

- Số liệu performance trích dẫn (Sharpe, PF, DD, win-rate…) PHẢI kèm `run_id` —
  số không truy vết được coi như không tồn tại (`.claude/rules/common/sandboxed-domain.md`)
- Viewer KHÔNG recompute indicators — chỉ render `indicators[]` đã ghi trong JSON
