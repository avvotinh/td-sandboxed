# 02 — Roadmap v2

Nguyên tắc sắp xếp: **mở khóa research loop trước** (P1–P2), rồi kernel chiến lược (P3),
nghiên cứu (P4 — chạy liên tục), live path (P5), FTMO (P6). Harness redesign (P-H)
chạy song song ngay từ đầu. Mỗi phase có exit criteria — không sang phase sau khi chưa đạt.

Gap references (G1–G7) xem [00-analysis.md](00-analysis.md) §4.

## P0 — Nền tài liệu & dọn quyết định *(0.5 ngày)*

- [x] Tạo `docs/v2/` + bộ tài liệu này.
- [ ] Đánh dấu deprecated lên đầu `docs/architecture.md`, `docs/prd.md`, `docs/epics.md`
      (một dòng banner trỏ về `docs/v2/`).
- [ ] Tạo `docs/v2/decisions.md` từ bảng D1–D7.
- [ ] Cập nhật `CLAUDE.md` mục Active Technologies + Structure theo v2 (sau khi P-H xong).

**Exit:** người mới đọc `docs/v2/README.md` hiểu được toàn cảnh, không lạc sang docs cũ.

## P1 — Result Contract v2 *(1–2 ngày — keystone, làm đầu tiên)*

| Task | Chi tiết | Gap |
|---|---|---|
| 1.1 | `lab/recorder/EquityRecorder` — actor độc lập ghi equity per-bar, tách khỏi `PropFirmComplianceActor` | G2 |
| 1.2 | `lab/recorder/IndicatorRecorder` — strategy đăng ký indicator series, recorder ghi `{time, value}` trong lúc chạy | G6 |
| 1.3 | `TradeRecord` mở rộng: `sl`, `tp`, `sl_path`, `entry_reason`, `exit_reason`, `r_multiple` thật (port phần `_extract_trades` + `sl_updates` từ commit `75bf832`) | G1, G7 |
| 1.4 | `lab/export/result_writer.py` — ghi full Contract v2 JSON (schema §4 của 01-architecture), kèm `data_ref` + fingerprint | G1 |
| 1.5 | CLI: `backtest run --export results/<run-id>.json`; sweep/WF thêm `--export-full` per-cell | G1 |
| 1.6 | Sửa `configs/backtest/*.yaml` sang đường dẫn tương đối repo-root; script regen manifests-2y chạy được trên máy Windows hiện tại | G4 |
| 1.7 | Tests: schema round-trip, equity không phụ thuộc prop_firm, R-multiple đúng per-trade | — |

**Exit:** một lệnh `backtest run` tạo ra file JSON chứa đủ candles-ref + trades + SL path
+ indicators + equity + metrics; test pass.

## P2 — Chart viewer service *(2–3 ngày)*

| Task | Chi tiết |
|---|---|
| 2.1 | Scaffold `services/chart-viewer/` (Python 3.12, FastAPI, uv; KHÔNG Docker) |
| 2.2 | Port từ `75bf832`: vendored lightweight-charts v5.2.0, template render + `esc()` của `chart_writer.py`, `ChartSeries`/`candles_from_dataframe`/`trades_to_payload` của `chart_data.py` + 329 dòng tests (`git show 75bf832:<path>` để lấy file) |
| 2.3 | Endpoint: `GET /` danh sách runs (scan `results/*.json` → bảng metadata + metrics tóm tắt); `GET /run/{run_id}` trang chart; `GET /api/run/{run_id}/candles?start&end` đọc parquet theo `data_ref` |
| 2.4 | Render: candles+volume, indicators từ JSON (không recompute), entry/exit markers, SL/TP + SL-path step line, equity pane, trade table click-to-jump, metrics header |
| 2.5 | So sánh 2 run cạnh nhau (A/B view) — phục vụ study verdicts |
| 2.6 | Tests: payload builder, escaping, API đọc parquet slice |

**Exit:** `uv run chart-viewer` → mở browser xem được kết quả một run donchian XAUUSD 2y
với đầy đủ trades/SL/TP/indicators/PnL. **Đây là điểm demo đầu tiên cho user.**

## P3 — Kernel v2 & prune engine *(3–5 ngày)*

| Task | Chi tiết |
|---|---|
| 3.1 | Reorganize `src/` → `kernel/ lab/ live/ rules/` (git mv, giữ tests) theo 01-architecture §3.1 |
| 3.2 | Xóa dead code: `accounts/` (multi-account), `config/firm_registry`, `engine/` orchestration cũ, `calendar/` (giữ news_blackout rule đọc file tĩnh), presets `the5ers/wmt` |
| 3.3 | `kernel/entries/` — chuẩn hóa `EntryModel` interface; port các entry hiện có (supertrend flip, donchian cross, MR band) |
| 3.4 | Quote-aware entries: limit/stop intent + spread model trên bar (D5); test chống lookahead cho mọi entry model |
| 3.5 | `kernel/exits/ExitPolicy` — hợp nhất config ATR SL/TP + BE fee-offset + trailing + scale-out thành một block khai báo |
| 3.6 | Xóa `notification/`; đóng băng `tv-api` chỉ còn fetch CLI (D4) |
| 3.7 | Chạy lại full test suite + một backtest chuẩn (donchian XAUUSD 2y) đối chiếu metrics trước/sau reorganize — **parity check bắt buộc** |

**Exit:** test suite xanh, parity check khớp (same trades, same metrics), codebase chỉ còn
những gì v2 dùng.

## P4 — Vòng lặp nghiên cứu chiến lược *(liên tục — trọng tâm chính)*

Tiếp nối trực tiếp Track 5.1/4.3 của plan cũ, nay có viewer để soi từng trade:

| Task | Chi tiết |
|---|---|
| 4.1 | Soi chart các run trailing A/B + entry-filter A/B đã chạy (07-06) — tìm pattern thua bằng mắt, điều mà bảng metrics không cho thấy |
| 4.2 | Study: entry filters (ADX gate, session windows, MR re-cross — research 07-05 đã có) trên kernel v2 |
| 4.3 | Study: quote-aware entries (limit pullback thay market-on-close) — giả thuyết giảm spread cost + entry tốt hơn |
| 4.4 | Study: ExitPolicy matrix (BE fee-offset × trailing tier-1 × scale-out) — ma trận A/B trên manifest 2y |
| 4.5 | Mỗi study: verdict markdown vào `docs/v2/studies/`, kỷ luật WF fixed-params + OOS reserve như cũ |

**Exit (= promotion gate D7):** ít nhất 1 chiến lược đạt OOS Sharpe ≥ 0.8 + WF pass.
Chưa đạt thì **không làm P5/P6** — lặp lại P4.

## P5 — Live path tối giản (demo account) *(3–4 ngày, chỉ khi P4 có ứng viên)*

| Task | Chi tiết | Gap |
|---|---|---|
| 5.1 | `live/session.py` — single-account session: connect bridge, nạp strategy + risk profile demo (1–2%), graceful shutdown | — |
| 5.2 | `modify_order` end-to-end: protocol message mới → bridge handler (Rust) → EA `OrderModify` (MQL5) — trailing/BE chạy live | G3 |
| 5.3 | Reconciliation khi start: query MT5 positions, đối chiếu, log lệch | — |
| 5.4 | Soak test trên demo: chạy ≥ 2 tuần, đối chiếu fill/slippage live vs backtest | — |

**Exit:** strategy ứng viên chạy demo ổn định 2 tuần, slippage/fill trong dự kiến,
trailing hoạt động đúng trên live.

## P6 — FTMO layer & tài khoản quỹ *(1–2 ngày)*

| Task | Chi tiết |
|---|---|
| 6.1 | `risk-profiles.yaml` profile `fund`: bật rule engine với `ftmo-presets.yaml` qua validated adapter |
| 6.2 | Backtest lại ứng viên VỚI compliance actor bật — xác nhận không breach daily-loss/max-DD trong 2y |
| 6.3 | Validation report vào `docs/v2/studies/` (theo quy tắc sandboxed-domain: mọi thay đổi preset kèm validation report) |
| 6.4 | Chuyển kết nối sang tài khoản quỹ |

**Exit:** chạy tài khoản quỹ với đầy đủ guard, 0 hardcode threshold.

## P-H — Harness redesign *(song song, chi tiết ở [03-harness.md](03-harness.md))*

Thứ tự: cập nhật rules/commands trước (đang gây nhiễu), agents/skills mới theo nhu cầu P1–P4.

## Rủi ro chính

| Rủi ro | Giảm thiểu |
|---|---|
| Reorganize P3 phá test/behavior | Parity check 3.7 bắt buộc; git mv từng bước, commit nhỏ |
| Không strategy nào pass gate (như 12.A) | Viewer P2 tăng chất lượng chẩn đoán; gate giữ nguyên — thà không live còn hơn live lỗ |
| Tick data quá nặng khi cần độ chính xác quote | D5 phân kỳ: spread model trước, tick sau, chỉ cho ứng viên đã hứa hẹn |
| `modify_order` live khác semantics backtest | Soak test 5.4 so khớp hành vi trailing live vs backtest |
