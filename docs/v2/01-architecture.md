# 01 — Kiến trúc mục tiêu v2

## 1. Mục tiêu & Non-goals

**Mục tiêu:**
- Vòng lặp research nhanh: sửa chiến lược → backtest → xem chart → verdict, tất cả local,
  không cần Docker/DB.
- Một kết nối tới một tài khoản MT5 (demo mặc định; tài khoản quỹ khi pass gate).
- Entry tính từ bar data + quote data; lợi nhuận tối ưu qua các chiến thuật SL/TP/trailing.
- Chart viewer hoàn thiện đọc JSON result: candles, indicators, entry/exit, SL/TP, PnL.

**Non-goals (v2 KHÔNG làm):**
- Multi-account, multi-firm, TradingView webhook, Telegram notification.
- Chạy FTMO compliance trong giai đoạn research (chỉ bật khi promote).
- Real-time dashboard — viewer là công cụ phân tích offline kết quả backtest.

## 2. Sơ đồ tổng thể

```text
                    RESEARCH LOOP (offline, không cần Docker)
┌──────────────────────────────────────────────────────────────────┐
│  data/ (parquet + manifest)                                       │
│      │                                                            │
│  ┌───▼──────────┐   result JSON (Contract v2)   ┌──────────────┐  │
│  │ strategy-lab  │ ────────────────────────────▶ │ chart-viewer │  │
│  │ (backtest,    │   results/<run-id>.json       │ FastAPI +    │  │
│  │  sweep, WF,   │                               │ lightweight- │  │
│  │  A/B)         │                               │ charts       │  │
│  └───┬──────────┘                               └──────────────┘  │
└──────┼───────────────────────────────────────────────────────────┘
       │  PROMOTION GATE (Decision §4: OOS Sharpe, WF pass, DD)
┌──────▼───────────────────────────────────────────────────────────┐
│                    LIVE PATH (1 tài khoản)                        │
│  ┌────────────┐  ZMQ REQ/REP  ┌────────────┐  DLL  ┌──────────┐  │
│  │ live-runner │ ◀───────────▶ │ mt5-bridge │ ◀───▶ │  MT5 EA  │  │
│  │ (1 session) │               │  (Rust)    │       │  (MQL5)  │  │
│  └────────────┘               └────────────┘       └──────────┘  │
│   RiskProfile: demo = 1–2%/lệnh │ fund = 1–2% + FTMO layer        │
└──────────────────────────────────────────────────────────────────┘
```

## 3. Các khối chính

### 3.1 strategy-lab (Python, trong `services/trading-engine/`)

Giữ NautilusTrader làm core (Quyết định D1). Tái cấu trúc `src/` quanh 3 package:

```text
src/
├── kernel/        # Chiến lược & chiến thuật (port từ strategies/ + indicators/)
│   ├── indicators/          # giữ nguyên
│   ├── entries/             # NEW: entry models — bar-based, quote-based (limit/stop)
│   ├── exits/               # port mixins: atr_stop, breakeven, trailing, scale_out
│   ├── sizing/              # risk_based_position_sizer + contract_specs
│   └── strategies/          # roster v2 (compose entry × exit × sizing)
├── lab/           # Backtest & study (port từ backtesting/)
│   ├── runner, engine, job_config
│   ├── dataset/             # manifest, pipeline — giữ nguyên
│   ├── metrics/             # + R-multiple thật per-trade (G7)
│   ├── recorder/            # NEW: EquityRecorder + IndicatorRecorder (fix G2, G6)
│   └── export/              # NEW: Result Contract v2 writer (fix G1)
├── live/          # NEW gọn: single-account session
│   ├── session.py           # connect bridge → run strategy → shutdown
│   ├── risk_profile.py      # demo | fund(preset FTMO)
│   └── adapters/            # zmq_adapter + validated_adapter (port)
└── rules/         # giữ nguyên (đã decoupled), chỉ FTMO preset
```

Nguyên tắc: **backtest và live chạy cùng một strategy class** (Nautilus đảm bảo điều này) —
không có nhánh code riêng cho live.

### 3.2 Kernel v2 — mô hình chiến lược

- **Entry**: `EntryModel` trả về `EntryIntent {side, kind: market|limit|stop, price?, reason}`.
  - Bar-based: tính trên `on_bar` như hiện tại.
  - Quote-aware: entry limit/stop đặt trước, fill mô phỏng bằng quote/spread
    (G5 — giai đoạn đầu dùng spread model trên bar: fill = close ± spread/2;
    giai đoạn sau nạp tick data thật từ MT5 để backtest chính xác hơn).
- **Exit**: các tactic composable đã có (ATR SL/TP, breakeven + fee-offset, trailing
  supertrend, scale-out, safety cap) — chuẩn hóa thành `ExitPolicy` config duy nhất.
- **Sizing**: `risk_percent` 1.0–2.0, never-upsize, skip nếu dưới min lot (giữ nguyên).
- **Kỷ luật chống lookahead**: mọi entry model mới phải kèm test "chỉ dùng dữ liệu ≤ t".

### 3.3 chart-viewer (service mới `services/chart-viewer/`)

- **FastAPI app local** (Quyết định D2), không Docker: `uv run chart-viewer --results-dir results/`.
- Trang danh sách run (đọc metadata từ các `results/*.json`) → click mở chart.
- Front-end: tái dùng từ commit `75bf832` — vendored `lightweight-charts v5.2.0`,
  template + `esc()` XSS-hardening của `chart_writer.py`, phần serialize của `chart_data.py`.
- **KHÔNG recompute indicators** — viewer chỉ render `payload["indicators"]` đọc từ JSON
  (backtest đã ghi sẵn qua IndicatorRecorder). Candles: viewer đọc parquet qua `data_ref`
  trong result JSON (server-side đọc parquet, browser nhận JSON slice).
- Hiển thị: candles + volume, indicator overlays/panes, marker entry/exit per trade,
  đường SL/TP ban đầu + SL path (BE/trailing ratchet), bảng trade click-to-jump với PnL,
  equity curve pane, tổng kết metrics (win rate, PF, Sharpe, max DD).

### 3.4 live-runner + mt5-bridge + EA

- Giữ nguyên wire protocol ZMQ JSON hiện có (`zmq_models.py` ↔ `protocol.rs`).
- `live/session.py`: một process, một account, một (hoặc vài) strategy —
  không orchestrator, không distributed lock.
- Bổ sung **`modify_order` end-to-end** (G3): message `modify` mới trong protocol →
  bridge handler → EA `OrderModify` — điều kiện tiên quyết để trailing/BE chạy live.
- Reconciliation tối thiểu: khi start, query positions từ MT5 (source of truth) và đối chiếu.

### 3.5 Risk hai chế độ

```yaml
# configs/risk-profiles.yaml
demo:
  sizing: {risk_percent: 1.0}      # hoặc 2.0
  compliance: none
fund:
  sizing: {risk_percent: 1.0}
  compliance:
    preset: configs/ftmo-presets.yaml   # daily loss, max DD, position size…
```

Lớp compliance = rule engine hiện có (`src/rules/`) gắn vào validated adapter —
bật/tắt hoàn toàn qua profile, không đổi code strategy.

## 4. Result Contract v2 — keystone của toàn hệ

Một schema JSON duy nhất, versioned, do `lab/export/` ghi và chart-viewer + backtest-analyst đọc:

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
  "metrics": { /* PropFirmMetricsSchema model_dump — giữ nguyên schema hiện có */ },
  "breaches": [ /* chỉ khi compliance bật */ ]
}
```

Quy tắc:
- `results/` gitignored (file lớn); verdict markdown trong `docs/v2/studies/` reference `run_id`.
- Mọi thay đổi schema tăng `schema_version` + ghi vào `decisions.md`.
- Sweep/WF/AB emit file tổng hợp riêng nhưng mỗi cell/fold có thể xuất full Contract v2
  khi cần soi chart (`--export-full`).

## 5. Quyết định thiết kế (Decision log khởi tạo)

| # | Quyết định | Lựa chọn | Lý do / Trade-off |
|---|---|---|---|
| D1 | Engine core | **Giữ NautilusTrader**, không viết engine mới | Đã proven trong repo, hỗ trợ Bar + QuoteTick, sizing bug đã fix; viết mới tốn nhiều tuần và tái tạo bug cũ. "Hoàn toàn mới" áp dụng cho *kiến trúc service & workflow*, không phải viết lại matching engine |
| D2 | Chart viewer | **FastAPI service riêng** đọc JSON + parquet, thay vì HTML-per-run | Đúng hướng đã pivot sau khi revert `75bf832`; browse nhiều run, không sinh rác HTML; vẫn tái dùng ~900 dòng front-end cũ |
| D3 | Tái cấu trúc code | **Prune-in-place trong `services/trading-engine/`** (xóa dead packages, reorganize thành kernel/lab/live), KHÔNG tạo service Python mới | Giữ được ~120 unit test + git history; port sang repo/dir mới sẽ mất 1–2 tuần thuần cơ học. Chart-viewer là service MỚI duy nhất |
| D4 | Số phận Go services | `notification` xóa; `tv-api` đóng băng, giữ mỗi **`tv-cli` fetch** cho tới khi có MT5 history fetch qua bridge | Không phá pipeline data hiện tại; giảm dần Go về 0 |
| D5 | Quote data giai đoạn 1 | **Spread model trên bar** trước, tick data MT5 sau | Tick 2y rất nặng; spread model đủ để đánh giá limit/stop entries; nâng cấp khi chiến lược hứa hẹn |
| D6 | Hạ tầng research loop | **Không cần Docker/TimescaleDB/Redis** cho backtest + viewer | Parquet + JSON file là đủ; tránh phụ thuộc WSL2. DB/Redis chỉ cho live path |
| D7 | Promotion gate | Giữ kỷ luật Decision §4 của plan cũ: **OOS Sharpe ≥ 0.8 + WF pass + DD chấp nhận được** thì mới bật FTMO layer và lên tài khoản quỹ | Đã có bài học donchian WF FAIL — không nới gate |
