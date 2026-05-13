---
name: ftmo-compliance
description: Checklist tuân thủ FTMO khi thêm/sửa rule engine, risk limits, audit logging
---

# FTMO Compliance Checklist

## Daily loss limit
- [ ] Tính theo starting balance của NGÀY, reset 00:00 UTC+2 (giờ Prague)
- [ ] Ngưỡng warning: 80% của limit → gửi Telegram
- [ ] Ngưỡng block: 100% → close all + emergency stop

## Max drawdown
- [ ] Floating equity curve, không phải realized PnL
- [ ] Tham chiếu high-water mark lưu trong Redis `account:{id}:hwm`

## Audit trail
- [ ] Mỗi trade phải có record trong `trade_audit_log` (hypertable)
- [ ] Mỗi rule check phải có record trong `rule_check_log`
- [ ] Mỗi emergency stop phải có record trong `emergency_events`
