# Sandboxed Domain Rules (v2)

## Research loop — không phụ thuộc hạ tầng
- Research loop (backtest, sweep, walk-forward, chart viewer) chạy KHÔNG cần Docker/TimescaleDB/Redis (Quyết định D6, `docs/v2/01-architecture.md`) — dữ liệu là Parquet + JSON file
- KHÔNG thêm dependency vào DB/Redis cho code trong kernel/lab/viewer — DB/Redis chỉ dành cho live path
- KHÔNG yêu cầu user chạy `/up`, `/migrate` cho công việc research

## Results & run_id discipline
- `results/` là **gitignored** (file lớn) — KHÔNG commit result JSON
- Verdict markdown trong `docs/v2/studies/` PHẢI reference `run_id` của run tạo ra kết quả
- Mọi số liệu performance được trích dẫn (Sharpe, PF, DD, win-rate...) PHẢI kèm `run_id` — số liệu không truy vết được về một run cụ thể coi như không tồn tại

## Chống lookahead bias
- Mọi entry model MỚI phải kèm test chứng minh chỉ dùng dữ liệu ≤ t (bar hiện tại và trước đó) — không đọc bar tương lai, không dùng giá close của bar chưa đóng
- Indicator/feature tính trên toàn bộ series (scaling, normalization, rolling mà center) là red flag — phải tính cumulative/rolling trái
- Nghi ngờ kết quả backtest "quá đẹp" → kiểm tra lookahead trước khi tin

## Database discipline (chỉ live path)
- Áp dụng khi làm live path (P5+) — research loop không đụng DB
- Mọi schema change PHẢI đi qua Alembic migration (không `ALTER TABLE` thủ công)
- TimescaleDB hypertable: trade_audit_log, rule_check_log, account_snapshot — retention 180 ngày
- NEVER `DROP TABLE` trong migration prod — chỉ `DROP` qua backup/restore manual

## Study & decision workflow
- Study verdict (kết quả nghiên cứu chiến lược) → `docs/v2/studies/<slug>-<yyyy-mm-dd>.md`
- Quyết định kiến trúc → ghi vào `docs/v2/decisions.md`
- KHÔNG commit code ngoài scope study/task đang làm (dùng stash/branch khác)

## FTMO compliance boundaries
- Ngưỡng daily loss / max drawdown KHÔNG được hardcode — load từ `configs/ftmo-presets.yaml`
- Mọi thay đổi preset PHẢI kèm validation report ở `docs/sprint-artifacts/validation-report-*.md`
- FTMO layer chỉ bật SAU KHI chiến lược pass promotion gate D7 (OOS Sharpe ≥ 0.8 + WF pass + DD chấp nhận được)
