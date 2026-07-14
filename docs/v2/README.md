# Sandboxed v2 — Tài liệu Redesign

> **Nơi chứa tài liệu MỚI** cho đợt thiết kế lại trading-engine (2026-07-14).
> Mọi tài liệu trong `docs/v2/` mô tả **kiến trúc mục tiêu v2**. Tài liệu bên ngoài
> (`docs/architecture.md`, `docs/prd.md`, `docs/epic-*-context.md`, `docs/epics.md`)
> là **legacy** — chỉ dùng để tra cứu hệ cũ, KHÔNG dùng làm căn cứ thiết kế mới.

## Định hướng v2 (tóm tắt)

1. **Một kết nối — một tài khoản MT5** (demo trước, tài khoản quỹ sau khi chiến lược pass gate).
2. **Strategy-first**: toàn bộ trọng tâm là xây và kiểm chứng chiến lược — entry từ bar data
   + quote data, tối ưu lợi nhuận bằng các chiến thuật SL/TP/trailing hợp lý.
3. **Chart viewer hoàn thiện**: service riêng đọc file JSON result, hiển thị candles,
   indicators, điểm vào/thoát lệnh, SL/TP, lời lỗ.
4. **Risk hai chế độ**: demo = sizing 1–2%/lệnh; tài khoản quỹ = sizing + lớp FTMO compliance
   (bật bằng config, không hardcode).
5. **Chỉ ứng dụng rules tài khoản quỹ SAU KHI backtest chứng minh có lợi nhuận** (gate rõ ràng).

## Mục lục

| Tài liệu | Nội dung |
|---|---|
| [00-analysis.md](00-analysis.md) | Phân tích hiện trạng: giữ gì, bỏ gì, các gap kỹ thuật |
| [01-architecture.md](01-architecture.md) | Kiến trúc mục tiêu v2 + Result Contract v2 + các quyết định thiết kế |
| [02-roadmap.md](02-roadmap.md) | Lộ trình theo phase, task cụ thể, exit criteria |
| [03-harness.md](03-harness.md) | Redesign harness `.claude/` (agents / skills / commands / rules) |
| `studies/` | Báo cáo nghiên cứu chiến lược v2 (thay cho `docs/sprint-artifacts/` cũ) |
| `decisions.md` | Decision log — mọi quyết định kiến trúc ghi tại đây (sẽ tạo khi có D mới) |

## Quy ước

- Tài liệu mới về v2 → luôn đặt trong `docs/v2/`.
- Báo cáo study/verdict mới → `docs/v2/studies/<slug>-<yyyy-mm-dd>.md`.
- Tài liệu legacy giữ nguyên chỗ cũ, không sửa (trừ khi đánh dấu deprecated).
- Kết quả nghiên cứu cũ vẫn có giá trị tham khảo: `docs/strategy-redesign-plan-2026-07-02.md`
  (Track 0–6) và `docs/sprint-artifacts/*-verdict.md` là đầu vào trực tiếp cho v2.
