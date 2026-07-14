# Decision Log — v2

Mọi quyết định kiến trúc v2 ghi tại đây. Format: mỗi quyết định một mục, có ngày,
trạng thái (ĐÃ DUYỆT / ĐỀ XUẤT / THAY THẾ bởi D-x), lý do và trade-off.

## D1 — Giữ NautilusTrader làm engine core *(2026-07-14, ĐÃ DUYỆT)*

Không viết matching engine mới. "Thiết kế lại hoàn toàn" áp dụng cho kiến trúc service
và workflow, không phải viết lại engine. Nautilus đã proven trong repo, hỗ trợ Bar +
QuoteTick, sizing bug đã fix (Track 1). Viết mới tốn nhiều tuần và tái tạo bug cũ.

## D2 — Chart viewer là FastAPI service riêng *(2026-07-14, ĐÃ DUYỆT)*

`services/chart-viewer/` đọc JSON result (Contract v2) + parquet qua `data_ref`,
thay vì HTML-per-run (đã revert ở `ed2131c`). Tái dùng ~900 dòng từ commit `75bf832`
(template, escaping, lightweight-charts v5.2.0 vendored). Viewer KHÔNG recompute
indicators — chỉ render series đã ghi trong JSON.

## D3 — Prune-in-place `services/trading-engine/` *(2026-07-14, ĐÃ DUYỆT)*

Tái cấu trúc `src/` → `kernel/ lab/ live/ rules/` bằng git mv (P3), không tạo service
Python mới. Giữ ~120 unit tests + git history. Parity check bắt buộc sau reorganize.
Trong P1–P2, code mới đặt tạm trong `src/backtesting/` (recorder/, export/) —
P3 sẽ move vào `lab/`.

## D4 — Số phận Go services *(2026-07-14, ĐÃ DUYỆT)*

`notification` xóa (P3). `tv-api` đóng băng, giữ duy nhất `tv-cli` fetch làm công cụ
tải data lịch sử cho tới khi có MT5 history fetch qua bridge.

## D5 — Quote data giai đoạn 1 = spread model trên bar *(2026-07-14, ĐÃ DUYỆT)*

Entry limit/stop mô phỏng fill bằng spread model (fill = close ± spread/2) trước.
Tick data thật từ MT5 chỉ nạp cho ứng viên chiến lược đã hứa hẹn (2y tick rất nặng).

## D6 — Research loop không cần Docker/TimescaleDB/Redis *(2026-07-14, ĐÃ DUYỆT)*

Backtest + viewer chạy trên parquet + JSON file thuần. DB/Redis chỉ cho live path (P5+).
Tránh phụ thuộc WSL2 trên máy Windows hiện tại.

## D7 — Promotion gate giữ nguyên Decision §4 *(2026-07-14, ĐÃ DUYỆT)*

OOS Sharpe ≥ 0.8 + walk-forward pass + drawdown chấp nhận được → mới bật FTMO layer
và chuyển tài khoản quỹ. Không nới gate (bài học donchian WF FAIL 2026-07-09).

## Known gaps sau P1 *(2026-07-14)*

- **Contract v2 `reason` fields**: `trades[].entry.reason` / `exit.reason` hiện là
  `null` — Nautilus không giữ lý do entry/exit; wiring reason thật qua `TradeRecord`
  (strategy ghi lý do lúc submit/close) là follow-up khi viewer P2 cần.
- **Compliance vẫn chạy trên realized balance**: `PropFirmComplianceActor` đánh giá
  rule trên `balance_total` (không cộng unrealized PnL) — giữ nguyên semantics cũ.
  Equity curve của Contract v2 (từ `EquityRecorderActor`) LÀ mark-to-market;
  equity-based compliance là follow-up ở live path (P6).
