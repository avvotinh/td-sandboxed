# Sandboxed Domain Rules

## Monorepo boundaries
- `services/trading-engine/` KHÔNG được import từ `services/tv-api/` (và ngược lại)
- Communication giữa các service CHỈ qua ZeroMQ (order flow) hoặc Redis pub/sub (events)
- KHÔNG tạo shared library chung giữa các service khác ngôn ngữ — nếu cần shared Python code, đặt trong `services/_shared/` (thư mục này sẽ được tạo khi có nhu cầu thực tế, hiện chưa tồn tại); Go services giữ copy riêng của contract DTOs

## Database discipline
- Mọi schema change PHẢI đi qua Alembic migration (không `ALTER TABLE` thủ công)
- TimescaleDB hypertable: trade_audit_log, rule_check_log, account_snapshot — retention 180 ngày
- NEVER `DROP TABLE` trong migration prod — chỉ `DROP` qua backup/restore manual

## Sprint workflow
- Trước khi commit: kiểm tra `docs/sprint-artifacts/sprint-status.yaml` có phản ánh đúng trạng thái story không
- Mỗi commit tương ứng 1 story — message format: `Implement spec <epic> story <story>`
- KHÔNG commit code ngoài scope story đang làm (dùng stash/branch khác)

## FTMO compliance boundaries
- Ngưỡng daily loss / max drawdown KHÔNG được hardcode — load từ `configs/ftmo-presets.yaml`
- Mọi thay đổi preset PHẢI kèm validation report ở `docs/sprint-artifacts/validation-report-*.md`
