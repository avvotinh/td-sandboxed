# Epic 14 Outline — MT5 EA + Live Execution Path

**Ngày:** 2026-05-06
**Trạng thái:** Outline / proposal
**Branch đề xuất:** `epic-14-mt5-ea`
**Tham chiếu:** [`strategy-tactics-implementation-plan.md`](./strategy-tactics-implementation-plan.md) §5.5
**Mục tiêu:** Hoàn thiện live execution path: viết MT5 EA MQL5 (chưa code), extend `mt5-bridge` protocol cho modify/cancel/close, implement `ZmqExecutionClient` modify/cancel commands. Khi epic này xong, Sandboxed có thể trade live trên FTMO MT5 account.

---

## 1. Bối cảnh

Sandboxed đã ship Epic 8-12 (strategies, rule engine, backtest harness) nhưng **live execution path chưa hoạt động end-to-end**:

- ✅ `services/trading-engine/` (Python/Nautilus): submit orders qua ZMQ — works.
- ✅ `services/mt5-bridge/` (Rust): nhận Order từ ZMQ, queue cho heartbeat polling — works.
- ❌ **MT5 EA (MQL5): chưa code** — không có consumer để pickup orders từ bridge.
- ❌ `ZmqExecutionClient._modify_order` / `_cancel_order`: stub `NotImplementedError` (Epic 10 OoS, comment "deferred Epic 11+").
- ❌ Position/order/fill status reports cho warm restart reconciliation: stub `[]` với warning (`zmq_execution_client.py:191-218`).

Epic 13 (strategy tactics) chạy được trên backtest path mà không cần Epic 14, nhưng **không thể deploy live** cho đến khi Epic 14 ship.

## 2. Scope của Epic 14

### Trong scope

| Mục | Mô tả |
|---|---|
| **MT5 EA MQL5 skeleton** | ZMQ client, heartbeat, JSON message parser, OrderSend wrappers |
| **MT5 EA: market order execution** | TRADE_ACTION_DEAL cho BUY/SELL với SL/TP (theo `Order` schema hiện tại của bridge) |
| **MT5 EA: modify SL/TP** | TRADE_ACTION_SLTP cho position SL/TP atomic |
| **MT5 EA: cancel pending order** | TRADE_ACTION_REMOVE |
| **MT5 EA: close position** | TRADE_ACTION_DEAL ngược chiều với position size |
| **MT5 EA: result reporting** | Order fill, modify ack, cancel ack, error responses qua ZMQ |
| **MT5 EA: position/order snapshot** | Periodic broadcast trạng thái MT5 account cho engine reconciliation |
| **Bridge protocol extension** | `MessageType::ModifyOrder`, `CancelOrder`, `ClosePosition`, `ModifyOrderResult`, `CancelOrderResult`, `PositionSnapshot` |
| **Bridge handlers** | `modify_handler.rs`, `cancel_handler.rs`, `close_handler.rs`, `snapshot_handler.rs` |
| **Engine `_modify_order` impl** | Replace `NotImplementedError` tại `zmq_execution_client.py:234`, route qua `ValidatedZmqAdapter` với rule check + audit |
| **Engine `_cancel_order` impl** | `zmq_execution_client.py:239` |
| **Engine `_cancel_all_orders` impl** | `zmq_execution_client.py:244` |
| **Reconciliation reports** | `generate_order_status_reports`, `generate_fill_reports`, `generate_position_status_reports` — query MT5 EA snapshot endpoint |
| **CURVE auth** | Bridge ZMQ socket khi không ở localhost (per `common/security.md`) |
| **HMAC validation** | Order/modify command từ engine xuống EA |
| **Operator runbook** | Deploy MT5 EA, attach to chart, broker setup, FTMO account integration |
| **E2E test path** | MT5 demo account → bridge → engine → strategy → modify/cancel/close lifecycle |

### Ngoài scope

- Multi-account multiplexing (1 EA → multiple Sandboxed accounts) — sau Epic 14 stable.
- MT5 history sync (load past trades từ broker) — sẽ là Epic 16+.
- Live deploy / migration plan — Epic 15.
- Epic 13 strategy tactics integration — không phụ thuộc Epic 14 ở implementation, chỉ ở deployment time.

## 3. Architecture target

```
Strategy.modify_order(order, trigger_price=new_price)
    │
    ▼
ZmqExecutionClient._modify_order(command)               ← implement Epic 14
    │
    ▼
dispatch_modify_order(command, account_id, validated_adapter, ...)   ← order_translator.py extension
    │
    ▼
ValidatedZmqAdapter.send_modify_and_wait(modify_cmd)
    │ rule check + audit log + HMAC sign
    ▼
ZmqAdapter.send_modify(modify_cmd)
    │ ZMQ PUB topic "order:{account_id}", payload type=modify_order
    ▼
mt5-bridge ZmqServer (Rust)
    │ MessageType::ModifyOrder routed to ModifyHandler
    │ HMAC verify + queue cho EA delivery
    ▼
mpsc queue → MT5 EA heartbeat response
    │
    ▼
MT5 EA (MQL5)                                           ← code Epic 14
    │ JSON parse
    │ HMAC verify
    │ OrderSend(MqlTradeRequest{action: TRADE_ACTION_SLTP, position: ticket, sl: new_sl, tp: new_tp})
    ▼
MetaTrader 5 server
    │
    ▼ (response)
MT5 EA → ZMQ PUB topic "modify_result:{account_id}"
    ▼
mt5-bridge → ZmqAdapter receive → resolve future → ValidatedZmqAdapter audit ack
    ▼
ZmqExecutionClient emits OrderModified event → Strategy.on_order_modified()
```

Cùng cấu trúc cho `cancel_order`, `close_position`, `submit_order` (đã có cho submit, chỉ thiếu MT5 EA consumer).

## 4. Story breakdown

Pattern `Implement spec 14 story 14.x` per CLAUDE.md sandboxed-domain rules.

### Phase A — MT5 EA foundation (MQL5)

| Story | Size | Dependencies | Deliverable |
|---|---|---|---|
| 14.1 — MT5 EA project scaffold | S | — | MQL5 EA file `Sandboxed_EA.mq5`, ZMQ DLL binding (libzmq for Win64), config struct, MT5 build setup runbook |
| 14.2 — EA: heartbeat client | M | 14.1 | Periodic heartbeat publish (account_id, timestamp), match bridge `Heartbeat` message format. Test connectivity với bridge running |
| 14.3 — EA: JSON message parser | S | 14.2 | Parse incoming `MessageType` discriminator, dispatch tới handler. Reject malformed với `Error` response |
| 14.4 — EA: HMAC signature verify | M | 14.3 | Per `common/security.md` FTMO domain rules — verify HMAC trên mỗi command từ bridge. Reject unsigned. Test vector matches Python signing |
| 14.5 — EA: OrderSend market BUY/SELL | M | 14.4 | TRADE_ACTION_DEAL với SL/TP. Convert volume/price từ bridge `Order` schema. Publish `OrderResult` (status, fill_price, slippage, error) |
| 14.6 — EA: position/order snapshot broadcast | M | 14.5 | Periodic (5s default, configurable) publish `PositionSnapshot` với open positions, pending orders. Format khớp với engine reconciliation reports |

### Phase B — Bridge protocol extension (Rust)

| Story | Size | Dependencies | Deliverable |
|---|---|---|---|
| 14.7 — Protocol enum + structs cho modify/cancel/close | M | — | `protocol.rs`: `MessageType::{ModifyOrder, CancelOrder, ClosePosition, ModifyOrderResult, CancelOrderResult, PositionSnapshot}`. `models/`: structs với serde. proptest roundtrip per `rust/testing.md` |
| 14.8 — `modify_handler.rs` | M | 14.7 | Handler nhận `ModifyOrderCommand`, queue cho EA delivery, track pending acks với correlation ID, timeout. Tests unit |
| 14.9 — `cancel_handler.rs` + `close_handler.rs` | M | 14.7 | Tương tự 14.8 cho cancel pending order và close position |
| 14.10 — `snapshot_handler.rs` | M | 14.7 | Receive `PositionSnapshot` từ EA, expose qua REQ/REP endpoint cho engine query |
| 14.11 — `zmq_server.rs` routing extension | S | 14.7-14.10 | Route các message types mới tới handlers. Tests integration |

### Phase C — Engine integration (Python)

| Story | Size | Dependencies | Deliverable |
|---|---|---|---|
| 14.12 — `zmq_models.py` Pydantic models | S | 14.7 | `ModifyOrder`, `CancelOrder`, `ClosePosition` request models + result models. Schema khớp với Rust serde |
| 14.13 — `zmq_adapter.py`: send/wait cho modify/cancel/close | M | 14.12 | `send_modify_and_wait`, `send_cancel_and_wait`, `send_close_and_wait` mirror `send_order_and_wait` pattern. Pending futures dict, timeout handling |
| 14.14 — `validated_adapter.py`: rule + audit cho modify/cancel | M | 14.13 | Extend ValidatedZmqAdapter với 3 new entry points. Audit log to `audit_writer` per `common/sandboxed-domain.md` |
| 14.15 — `order_translator.py`: dispatch_modify_order, dispatch_cancel_order, dispatch_close_position | M | 14.14 | Translate Nautilus commands → bridge commands. Emit Nautilus events on completion |
| 14.16 — `zmq_execution_client.py`: implement modify/cancel | M | 14.15 | Replace `NotImplementedError` ở line 234, 239, 244, 249. Hookup dispatch functions |
| 14.17 — `zmq_execution_client.py`: reconciliation reports | M | 14.10, 14.16 | Replace stub `generate_*_reports` (line 184-222) with real query qua snapshot endpoint. Kill phantom-flat warning |

### Phase D — End-to-end + runbook

| Story | Size | Dependencies | Deliverable |
|---|---|---|---|
| 14.18 — E2E integration test (MT5 demo) | XL | 14.6 + 14.11 + 14.17 | Test full lifecycle trên MT5 demo account: submit order → fill → modify SL → close. Đo latency, slippage. Document caveats |
| 14.19 — Operator runbook: MT5 EA deployment | M | 14.18 | `docs/runbooks/mt5-ea-deployment.md`: Windows MT5 install, attach EA to chart, ZMQ DLL setup, broker credentials, FTMO challenge integration. Screenshots, troubleshooting |
| 14.20 — CURVE auth khi non-loopback | M | 14.11 | Generate keypairs, store in config, enable bind to non-loopback per `rust/security.md` |
| 14.21 — Sprint artifacts + retrospective | S | 14.20 | Update sprint-status.yaml, validation report, update `docs/architecture.md` với live path detail |

**Tổng:** ~21 stories. Estimate **3-5 tuần** dev time tùy:
- MQL5 expertise availability (dev có code MQL5 trước chưa?)
- ZMQ DLL Win64 build path (có pre-built không?)
- Test infrastructure cho MT5 demo (Windows VM, broker demo account ready?)

## 5. Risks và mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| MQL5 expertise gap (đa số team Python/Rust) | High | Story 14.1 dành thời gian onboarding; dùng existing MT5 EA templates open-source (GitHub: `dingmaotu/mql-zmq` reference) |
| ZMQ DLL Win64 binding fragile | Medium | Sử dụng `libzmq` precompiled DLL (4.3.x). Pin version. Document trong runbook |
| MT5 EA crash → orphan positions | High | Heartbeat timeout detection (đã có ở bridge zmq_server.rs:20), engine pause khi miss N heartbeats. Position snapshot reconciliation tại boot |
| Race: engine submit modify trong khi EA đang process cũ | Medium | Correlation ID per modify command + EA queue serialization. Test latency-injected |
| FTMO compliance: audit log cho modify/cancel (trade_audit_log) | High | `common/sandboxed-domain.md` rule: mọi mutation `account.*` PHẢI qua audit_writer trước. Story 14.14 enforce |
| HMAC key rotation procedure | Medium | Document trong runbook. Manual rotation, automated khỏi scope Epic 14 |
| Slippage mismatch backtest vs live | High (operational) | Document trong validation report. Live slippage thường > backtest model. Spread-aware fee model đã có (Epic 12.x) |
| MT5 server-side reject (margin call, market closed) | Low | EA forward error code/message, engine treat as `OrderRejected` |
| ZMQ message ordering | Low | ZMQ guarantees per-socket ordering. Multi-account scenario với separate sockets per account |
| Phantom-flat reconciliation gap (existing) | Critical | Already a TODO trong code (line 191-218). Story 14.17 đóng gap này |

## 6. Dependencies với các epic khác

| Epic | Quan hệ |
|---|---|
| Epic 8-11 (shipped) | Foundation — không phụ thuộc |
| Epic 12 (paused) | Independent — Epic 12 backtest harness không touch live path |
| Epic 13 (active) | Independent ở implementation. Cùng deploy với Epic 14 trong Epic 15 |
| Epic 15 (future) | Depends on Epic 13 + Epic 14 done. Production deployment, monitoring, alerting |

Epic 14 có thể chạy parallel với Epic 13. Recommend: assign 1 dev cho Epic 13 (Python-only), 1 dev cho Epic 14 (cross-language). Ngắn hạn Epic 13 ship trước (~2 tuần), Epic 14 ship sau (~3-5 tuần).

## 7. Success criteria

- [ ] MT5 EA deploy được trên Windows MT5 đính FTMO demo account
- [ ] Submit market order qua engine → fill qua MT5 → result emit về engine trong < 500ms (P95)
- [ ] Modify SL qua `Strategy.modify_order(...)` → MT5 acknowledge → `OrderModified` event tại engine. Atomic, no double-modify
- [ ] Cancel pending order qua `Strategy.cancel_order(...)` → MT5 confirm → `OrderCanceled` event
- [ ] Close position qua `Strategy.close_position(...)` → confirm
- [ ] Warm restart: engine restart khi MT5 có 2 open positions → `generate_position_status_reports` trả đúng 2 positions, KHÔNG submit duplicate orders trên top
- [ ] Coverage 80%+ cho new Python/Rust code
- [ ] All existing tests still pass (`uv run pytest`, `cargo test`)
- [ ] Lint sạch
- [ ] Runbook validated bởi 1 operator independent (không phải dev viết code)
- [ ] Audit log có entry cho mỗi submit/modify/cancel với correlation ID
- [ ] HMAC verify hoạt động end-to-end
- [ ] No phantom-flat warning trong logs sau warm restart

## 8. Open questions

1. **Ai own MT5 EA development?** Team có MQL5 expertise, hay cần outsource/library port? Câu trả lời ảnh hưởng story 14.1-14.6 estimate.
2. **MT5 demo account cho test:** FTMO challenge demo, hay broker demo riêng (ICMarkets, OANDA MT5)? FTMO demo có thể có rule check active làm test phức tạp.
3. **ZMQ DLL distribution:** ship cùng EA package, hay user install separately? Distribution licensing với libzmq (LGPLv3+SE).
4. **MT5 build:** team dùng MetaEditor IDE (Windows), có thể build trên Linux qua Wine không?
5. **Multi-account roadmap:** có nên design Epic 14 cho multi-account từ đầu, hay single-account first và refactor sau?

## 9. References

- [`docs/research/strategy-tactics-implementation-plan.md`](./strategy-tactics-implementation-plan.md) §5.5 — discovery context
- `services/mt5-bridge/src/protocol.rs:20-27` — current MessageType enum
- `services/mt5-bridge/src/models/order.rs:14-34` — current Order schema
- `services/mt5-bridge/src/zmq_server.rs:182-220` — current message routing
- `services/trading-engine/src/engine/clients/zmq_execution_client.py:184-252` — stubs cần implement
- `services/trading-engine/src/adapters/zmq_adapter.py:347-412` — `send_order` pattern để mirror
- `services/trading-engine/src/execution/validated_adapter.py` — rule check + audit pattern
- `.claude/rules/common/security.md` — CURVE auth, HMAC requirements
- `.claude/rules/common/sandboxed-domain.md` — audit_log + FTMO compliance discipline
- `.claude/rules/rust/testing.md` — proptest cho protocol roundtrip
- Reference MQL5 ZMQ binding: https://github.com/dingmaotu/mql-zmq (verify trước khi adopt)
