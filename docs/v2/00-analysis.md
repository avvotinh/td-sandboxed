# 00 — Phân tích hiện trạng (2026-07-14)

Mục tiêu: xác định **giữ gì / port gì / bỏ gì** từ hệ hiện tại, và các gap kỹ thuật
phải xử lý để đạt định hướng v2 (single MT5 account, strategy-first, chart viewer).

## 1. Hệ hiện tại là gì

4 services: `trading-engine` (Python/NautilusTrader), `mt5-bridge` (Rust/ZMQ),
`tv-api` (Go — TradingView webhook + data fetch), `notification` (Go — Telegram).
Hạ tầng: TimescaleDB + Redis. Trading-engine được xây cho **multi-account, multi-firm**
(account_manager, risk_registry, firm_registry, phase_promotion, recovery orchestrator…)
— phần lớn độ phức tạp này KHÔNG phục vụ định hướng v2.

## 2. Thực trạng nghiên cứu chiến lược

Từ `strategy-redesign-plan-2026-07-02.md` và các verdict gần nhất:

- Phase 12.A: **không strategy nào đạt Sharpe ≥ 0.8** (gate promotion).
- Walk-forward donchian M5 (07-09): **FAIL** theo Decision §4 — edge in-sample không lặp lại OOS.
- Regime-gate ablation (Track 4.3): không cứu được edge.
- Trailing tier-1 + BE fee-offset đã implement xong, A/B ma trận đã chạy.

**Hàm ý:** quyết định "tập trung build chiến lược trước, live sau" là đúng —
hệ live/compliance hiện tại đang gánh chi phí bảo trì cho một edge chưa tồn tại.
v2 đảo ưu tiên: vòng lặp research (backtest → xem chart → sửa chiến lược) phải nhanh nhất có thể.

## 3. Bảng verdict: giữ / port / bỏ

### GIỮ NGUYÊN (dùng tiếp, giá trị cao)

| Thành phần | Vị trí | Lý do |
|---|---|---|
| NautilusTrader làm engine core | `backtesting/engine.py`, strategies | Đã chạy ổn, sizing bug đã fix (Track 1), hỗ trợ cả Bar lẫn QuoteTick |
| Dataset pipeline + manifest | `backtesting/dataset/` (`manifest.py`, `pipeline.py`) | Manifest 2y fingerprinted, gap detection — nền data tin được |
| Indicators tùy biến | `src/indicators/` (supertrend, adx, bb_width, …) | Đã test, dùng lại nguyên vẹn |
| Bracket mixins (ATR SL/TP, BE, trailing, scale-out) | `src/strategies/mixins/`, `bracket_scale_out.py` | Chính là "chiến thuật SL/TP" mà v2 muốn tối ưu — đã có state machine + tests |
| Risk-percent sizing | `risk_based_position_sizer.py`, `contract_specs.py` | Đúng yêu cầu 1–2%/lệnh; never-upsize, lot↔unit chuẩn |
| Metrics engine | `backtesting/metrics/` | Schema Pydantic đầy đủ (pnl/drawdown/risk/trades/compliance) |
| Study harnesses | `parameter_sweep.py`, `walk_forward*.py`, `ab_compare.py`, `scripts/run_*.py` | Kỷ luật validation (WF fixed-params, A/B) — giữ nguyên phương pháp |
| Rule engine + FTMO presets | `src/rules/`, `backtesting/presets/*.yaml` | Đã decoupled khỏi strategy; v2 chỉ cần bật/tắt qua config |
| mt5-bridge (Rust) + wire protocol | `services/mt5-bridge/`, `adapters/zmq_models.py` | Đường live duy nhất còn lại; protocol JSON/ZMQ đã có e2e test |

### PORT / VIẾT LẠI GỌN (ý tưởng đúng, hiện thực phải làm lại)

| Thành phần | Vấn đề hiện tại | Hướng v2 |
|---|---|---|
| Chart viewer (commit `75bf832`, đã revert) | HTML-per-run, indicator recompute dính chặt engine | Service riêng đọc JSON result; tái dùng `chart_writer.py` + nửa serialize của `chart_data.py` + lightweight-charts v5.2.0 vendored (~900 dòng dùng lại được) |
| JSON result export | CLI chỉ xuất **counts** — mất mảng trades, equity curve, indicators (`_cli_utils.py:55`) | Result Contract v2 (xem 01-architecture §4) — đây là keystone |
| Equity curve | Sinh ra bởi `PropFirmComplianceActor` → không có compliance thì không có equity | Tách equity tracking khỏi compliance actor |
| Live session | `live_orchestrator` multi-account, recovery phức tạp | `live-runner` một account: session → strategy → validated adapter → bridge |
| Entry model | Entry chỉ từ `bar.close` (`bracket_strategy.py:482`) | Kernel v2: entry từ bar HOẶC quote (limit/stop + spread-aware fill) |

### BỎ / ĐÓNG BĂNG

| Thành phần | Lý do |
|---|---|
| `tv-api` webhook path (Go) | TradingView webhook không nằm trong v2. **Giữ lại duy nhất `tv-cli` fetch** làm công cụ tải data lịch sử cho tới khi có nguồn thay thế (fetch từ MT5 qua bridge) |
| `notification` service (Go) | Telegram bot không thiết yếu cho research loop; thêm lại sau nếu cần alert live |
| Multi-account: `accounts/` (account_manager, risk_registry, pnl_registry, signal_router, phase_promotion, risk_isolation) | v2 = 1 account |
| Multi-firm: `config/firm_profile.py`, `firm_registry.py`, presets `the5ers.yaml`, `wmt.yaml` | Chỉ còn FTMO preset; giữ file preset, bỏ registry abstraction |
| `engine/` live orchestration (recovery_orchestrator, lock_lost, account_session đa phiên) | Thay bằng live-runner tối giản |
| Strategies legacy `[]`-regime (bollinger_mr, rsi_mr, orb, ma_crossover) | Chỉ giữ dạng tham chiếu A/B; roster v2 build lại từ nghiên cứu |

## 4. Các gap kỹ thuật phải xử lý (đánh số để trace trong roadmap)

- **G1 — JSON result thiếu dữ liệu:** `result_to_json_dict` xuất `trades: <count>` thay vì
  mảng trades; equity curve không xuất. Chart viewer không thể hoạt động nếu chưa fix.
- **G2 — Equity curve phụ thuộc compliance actor:** backtest không gắn `prop_firm` thì
  không có equity curve (`prop_firm_actor.py:113`). Sai về separation of concerns.
- **G3 — Live SL-modify NotImplemented:** `ZmqExecutionClient._modify_order` raise —
  trailing/BE không chạy được trên live. Phải làm ở cả EA (MQL5) lẫn bridge.
- **G4 — Data path máy-specific:** `configs/backtest/*.yaml` trỏ đường dẫn tuyệt đối
  `/home/hopdev/...` (máy cũ Linux). Manifests-2y đang gitignored, cần script regen.
- **G5 — Chưa có quote data:** toàn bộ pipeline là bar (M5/M15). Entry "dựa trên quote data"
  cần nguồn tick/quote (MT5 history qua bridge, hoặc mô hình spread trên bar).
- **G6 — Indicator series không được export:** viewer cũ phải recompute indicators bằng
  cách feed lại Bar stream — nguồn drift. v2: strategy tự ghi lại series khi backtest chạy.
- **G7 — Metrics proxy:** `avg_r_multiple` và `calmar` là proxy (ghi chú tại
  `calculator.py:88`). Nên tính R-multiple thật per-trade khi đã có mảng trades đầy đủ (G1).

## 5. Ràng buộc môi trường (từ thực tế setup)

- Windows 11 + uv; **pin Python 3.12** (nautilus-trader chưa có wheel 3.14).
- Docker phụ thuộc WSL2 (đã có lúc blocked) → v2 nên chạy được research loop
  **không cần Docker** (parquet + JSON file, không bắt buộc TimescaleDB/Redis cho backtest).
- `gh` CLI chưa cài — PR qua web URL.
