# Architecture Review — Sandboxed Multi-Account Trading System

**Date:** 2026-04-30
**Reviewer:** ECC harness review (Opus 4.7 1M-context, project ECC config)
**Scope:** Tổng thể kiến trúc dự án sau khi Epic 9 (Multi-firm Foundation) đóng — focus on: thành phần & mối liên hệ, data flows, storage, drift giữa docs và code, tech-debt ưu tiên.
**Source-of-truth docs cross-checked:** `docs/architecture.md` v3.0 (2025-12-07), `docs/prd.md`, `docs/epic-9-context.md` (2026-04-30), `infra/timescaledb/init.sql` + 6 migrations, toàn bộ `services/*/src/`.
**Git head at review:** `e9e9b5f` (Implement spec 9 story 9.16 — Epic 9 closed).

---

## Executive Summary

Kiến trúc cốt lõi **đã solid và Epic 9 vừa đóng foundation multi-firm**: monorepo polyglot 4 service độc lập, dual-bus messaging (ZeroMQ low-latency + Redis Pub/Sub), tách hot cache (Redis) và cold storage (TimescaleDB) với per-account namespacing, pluggable rule engine với 3-layer override (firm baseline → phase → account) và safety guard không cho nới lỏng block threshold.

Tuy nhiên có **2 nhóm nợ kỹ thuật lớn cần xử lý trước khi đi live thật sự với capital**:
1. **Orchestrator god-object + audit double-entry chưa chuẩn** (D1, D3, D5, D6) — gây risk về data integrity và testability.
2. **P0 production-readiness chưa cover** từ Review 3 của Epic 9 còn lại 3 mục: live orchestrator full, news blackout, kill-switch flat-positions (D5, D7).

Bên cạnh đó là 4 nợ trung bình (D2 coexistence rule source, D4 multi-port mt5-bridge, D8 backtest spread/swap parity, D10 schema double-source-of-truth) và nợ thấp về housekeeping (D9 untracked report files).

**Khuyến nghị:** Mở 1 Epic mới "Operational Hardening" (gợi ý Epic 10) gom D1+D3+D5+D6+D7 trước khi triển khai live; D2+D10 cleanup làm song song khi tất cả account đã chuyển sang firm-bound.

---

## 1. Bức tranh hệ thống

### 1.1 Service inventory

| Service | Ngôn ngữ | LOC src/ | Vai trò chính |
|---|---|---|---|
| `tv-api` | Go 1.21+ | (multi-binary: tv-chart, tv-quote, tv-cli, benchmark, storage-test) | Thu thập OHLCV + quote từ TradingView WS, ghi Redis + TimescaleDB |
| `mt5-bridge` | Rust 1.75+ + Tokio | ~1.5K | Cầu ZeroMQ ↔ MT5 EA — forward tick, gửi lệnh, nhận execution result |
| `trading-engine` | Python 3.11 + Nautilus + asyncio | ~15.4K | Bộ não — multi-account, strategy, **rule engine**, risk, audit, state recovery, backtest |
| `notification` | Go 1.21+ | ~1K | Telegram bot — subscribe `alerts:*` Redis channel → format → push |

Nguyên tắc service-independence (CLAUDE.md §sandboxed-domain): không shared library cross-language; communication chỉ qua ZeroMQ (order flow) hoặc Redis pub/sub (events).

### 1.2 Communication mesh

```
TradingView ──WS──▶ tv-api ──┬─▶ Redis (tick:*, candles:*, bars:* PubSub)
                              └─▶ TimescaleDB (candles hypertable)

MT5 EA ─ZMQ REQ/REP─▶ mt5-bridge ─PUB :5556─▶ trading-engine (Tick stream)
trading-engine ─PUB :5557─▶ mt5-bridge ─REQ─▶ MT5 EA (Order command)
                                       ◀────  OrderResult

trading-engine ─Redis PUB─▶ alerts:trade / alerts:risk / alerts:system
                              └────▶ notification ─▶ Telegram HTTPS

trading-engine ──INSERT──▶ TimescaleDB (trades, audit_logs, rule_violations,
                                         account_snapshots, state_snapshots)
```

**Communication matrix** (đầy đủ): xem `docs/architecture.md:697-708`.

---

## 2. Data flows

### 2.1 Market data (read path)

1. `tv-api/cmd/tv-chart` và `cmd/tv-quote` connect WS TradingView, parse → 2 đường ghi song song:
   - **Hot path** (`internal/store/redis.go`): `tick:{symbol}:latest` (Hash, TTL 60s), `candles:{symbol}:{tf}` (Sorted Set, TTL 24h), publish `bars:{symbol}:{tf}`.
   - **Cold path** (`internal/store/timescaledb.go`): batch buffer → `candles` hypertable, retention được TimescaleDB quản lý.
2. `trading-engine/src/adapters/redis_adapter.py` SUB `bars:*` → callback đẩy vào `StrategyDataRouter` (`strategies/data_router.py`) → router filter theo `account.signal_filter.symbols` → fan-out tới các `BaseStrategy` instance đang chạy.
3. Tick từ MT5 đi qua `zmq_adapter.receive_ticks()` (background async generator) — dùng cho execution-time bid/ask, **không** cho strategy entry decision (entry chạy theo bar event từ tv-api).

### 2.2 Order flow (write path — hot path FTMO/The5ers compliance)

1. `BaseStrategy.on_bar()` (Nautilus lifecycle) → subclass override `generate_signal()` → trả `SignalType` (BUY/SELL/CLOSE/NONE).
2. Strategy gọi xuống `OrderExecutionService.execute_signal()` tại `services/trading-engine/src/orders/execution_service.py` (587 LOC).
3. **Validation gate**: lệnh đi qua `ValidatedZmqAdapter` (`src/execution/validated_adapter.py`) — wrapper của `OrderGateway` Protocol (P0.12, `src/orders/order_gateway.py`). Validate bằng `RuleEngine` per-account trước khi `send_order_and_wait()`.
4. `RuleEngine.validate()` (`src/rules/engine.py:73`) — **synchronous theo thiết kế** (perf), sort rule theo priority, trả `RuleEngineResult` với action `ALLOW`/`WARN`/`BLOCK`. Strict mode: lỗi runtime = BLOCK.
5. **Rule set per account** được resolve bởi `RuleAssignmentService` (`src/rules/assignment_service.py`) qua **3 layer** (P0.16):
   ```
   product baseline → phase overrides → account overrides
   ```
   Gác bởi `_TIGHTNESS_GUARDS` (`src/rules/override_merger.py`) — phase layer trusted (firm-controlled), account layer chỉ được tighten, loosen sẽ raise `RuleOverrideError` ở rule-assignment time.
6. Lệnh hợp lệ → ZMQ PUB :5557 → `mt5-bridge/src/handlers/order_handler.rs` → forward đến MT5 EA qua REQ/REP :5555 → EA `OrderSend()` → result quay ngược.
7. Result → `OrderExecutionService` cập nhật `PositionTracker` (`src/orders/position_tracker.py`), tạo `Trade` record → `TradeDBWriter` (`src/orders/trade_db_writer.py`) ghi `trades` hypertable batch.
8. **Audit trail**: mỗi rule check + violation → `AuditService` (`src/audit/audit_service.py`) → `audit_logs` hypertable (180d retention, migration `007`); vi phạm cứng → `ViolationService` → `rule_violations` hypertable (180d retention, migration `008`).
9. Đồng thời publish `alerts:trade:{account_id}` / `alerts:risk:{account_id}` cho `notification`.

### 2.3 Recovery flow (cold-start sau crash)

`engine.run()` tại `src/engine.py:615` orchestrate 5 module nặng:
1. `CrashRecoveryManager` (`src/state/crash_recovery.py`, 538 LOC) — load Redis snapshot mới nhất, validate checksum, register process lock heartbeat (`_on_lock_lost` callback → emergency shutdown nếu lock mất).
2. `PositionReconciler` (`src/state/position_reconciler.py`, **1009 LOC**) — query MT5 actual positions, **trust MT5 as source of truth** (ADR-007), log discrepancy.
3. `DailyPnLRecalculator` (`src/state/daily_pnl_recalculator.py`, 432 LOC) — recompute daily P&L từ `trades` table khi snapshot stale.
4. `TradingResumer` (`src/state/trading_resumer.py`, 406 LOC) — re-arm các account task qua `AccountManager`.
5. `GracefulShutdown` (`src/state/graceful_shutdown.py`, 455 LOC) — wait SIGTERM/SIGINT, persist final state, close connections theo thứ tự.

Tổng `src/state/` ≈ **3.5K LOC** chỉ riêng cho lifecycle/recovery — gần bằng toàn bộ `src/strategies/` (3K LOC).

---

## 3. Storage architecture

### 3.1 Redis (hot, TTL'd, per-account namespacing — ADR-008)

| Key pattern | Mục đích | TTL | Producer |
|---|---|---|---|
| `tick:{symbol}:latest` | Latest bid/ask | 60s | `tv-api` |
| `candles:{symbol}:{tf}` (Sorted Set) | Bar cache 24h | 24h | `tv-api` |
| `bars:{symbol}:{tf}` (Pub/Sub) | Bar event stream | — | `tv-api` |
| `snapshot:{account_id}:latest` | Engine state snapshot 5s flush | 1h | `trading-engine` |
| `compliance:{account_id}:daily:{YYYY-MM-DD}` | Daily compliance metrics | 7d | `trading-engine` |
| `account:{account_id}:status` | active / paused / stopped / error | persistent | `trading-engine` |
| `account:{account_id}:health` | MT5 connected, heartbeat | 60s | `trading-engine` |
| `health:{service_name}` | Service heartbeat | 30s | tất cả |
| `alerts:{trade,risk,system}[:{account_id}]` | Notification fan-out | — (PubSub) | `trading-engine` |
| `emergency:stop` | Kill-switch broadcast | — (PubSub) | `notification` (Telegram cmd) |

### 3.2 TimescaleDB (cold, hypertable + retention)

`infra/timescaledb/init.sql` + 6 raw migrations (`005_state_snapshots.sql` … `010_rename_ftmo_audit_events.sql`).

**Hypertables (time-series, retention policy):**

| Hypertable | Retention | Mô tả |
|---|---|---|
| `candles` | TimescaleDB managed | Market data, indexed by `(symbol, tf, time)` UNIQUE |
| `audit_logs` | 180 ngày (migration `007`) | Mọi rule check, system event |
| `rule_violations` | 180 ngày (migration `008`) | Vi phạm cứng đã trigger action |
| `state_snapshots` | 7 ngày (migration `005`) | Cold backup Redis snapshot |

**Relational tables:**

| Table | Note |
|---|---|
| `prop_firms` | **Legacy** reference table — sẽ retire post-Epic 9 |
| `accounts` | Sau migration `009` có `firm_id + product_id + phase + rule_overrides JSONB` với CHECK "all-or-nothing firm binding" |
| `trades` | Per account, có `mt5_ticket`, slippage, commission |
| `account_snapshots` | Daily compliance, 1 row/account/day |
| `performance_metrics` | Per account/strategy/day |

**Migration debt** (ghi rõ trong `docs/epic-9-context.md` §P0.3): Alembic chưa bootstrap dù `.claude/rules/database/schema.md` mandate; toàn bộ migrations đang là raw SQL. Đã queue thành Epic 10 candidate.

### 3.3 Per-account isolation (ADR-008)

Pattern `{category}:{account_id}:{key}` áp dụng nhất quán cho mọi state per-account ở Redis. Trong DB, `account_id VARCHAR(50) REFERENCES accounts(id) ON DELETE CASCADE` xuất hiện ở `trades`, `account_snapshots`, `performance_metrics`, `audit_logs`, `rule_violations` (FK thêm sau khi tạo hypertable theo pattern bắt buộc trong TimescaleDB).

---

## 4. Trading-engine module inventory

| Subsystem | Vị trí | LOC | Files đáng chú ý |
|---|---|---|---|
| `accounts/` — multi-account lifecycle | `src/accounts/` | ~1.5K | `account_manager.py`, `signal_router.py` (298), `risk_isolation.py`, `pnl_registry.py`, `phase_promotion.py` |
| `rules/` — pluggable rule engine | `src/rules/` | ~3.3K | `engine.py`, `parser.py` (367), `override_merger.py` (282 — P0.16), `assignment_service.py`, `audit_logger.py` (299), `audit_db_writer.py` (319), `violation_db_writer.py` (237) |
| `rules/types/` | 4 file | — | `drawdown.py`, `position.py`, `consistency.py` (P0.7), `targets.py` (`profit_target`, `weekly_target`, `min_trading_days`) |
| `rules/presets/` | YAML | — | `ftmo.yaml`, `the5ers.yaml`, `wmt.yaml` — **legacy preset path** (P0.11 đã ship `configs/firms/*.yaml` mới nhưng preset YAML chưa retire) |
| `strategies/` — Nautilus strategies | `src/strategies/` | ~3K | `base_strategy.py`, `bracket_strategy.py`, 5 strategy concrete (ma_crossover, supertrend, donchian, RSI MR, Bollinger MR, ORB), 3 mixins (`atr_stop`, `risk_sized`, `session_filter`) |
| `orders/` + `execution/` | `src/orders/`, `src/execution/` | ~1.9K | `execution_service.py` (587), `order_gateway.py` (P0.12 Protocol), `position_tracker.py` (275), `validated_adapter.py` |
| `state/` — recovery & shutdown | `src/state/` | **~3.5K** | `position_reconciler.py` (1009), `crash_recovery.py` (538), `graceful_shutdown.py` (455), `daily_pnl_recalculator.py` (432), `trading_resumer.py` (406), `redis_state.py` (403), `snapshot_service.py` (276) |
| `adapters/` | `src/adapters/` | ~1.5K | `zmq_adapter.py` (595), `mt5_connection_manager.py` (430), `redis_adapter.py` (369) |
| `audit/` | `src/audit/` | ~130 | `audit_service.py` |
| `snapshots/` | `src/snapshots/` | ~700 | `daily_snapshot_service.py` (459), `daily_profit_history.py` (P0.7) |
| `config/` | `src/config/` | — | `firm_registry.py` (P0.2), `firm_profile.py` (P0.1), `loader.py`, `session_clock.py` (P0.5) |
| `cli/` | `src/cli/` | — | `main.py` (typer), `accounts.py` (`accounts promote --phase` P0.10), `audit.py`, `report.py`, `config.py` |
| `backtesting/` | `src/backtesting/` | — | `runner_facade.py`, `prop_firm_actor.py`, `commission.py` (P0.13), `parameter_sweep.py`, `walk_forward.py` |
| `indicators/` | `src/indicators/` | — | Custom Supertrend, ADX, session-anchored VWAP + re-export Nautilus built-ins |

`engine.py` = 763 LOC ở root `src/` orchestrate tất cả modules trên.

---

## 5. Findings — drift giữa docs/code, debt, risk

Severity: **CRITICAL** = blocker live trading | **HIGH** = correctness/integrity risk | **MEDIUM** = maintainability/scaling | **LOW** = housekeeping

### D1 — `TradingEngine` god object [HIGH]

**Vị trí:** `src/engine.py:54-116`
**Symptom:** Constructor nhận **9 optional dependencies** (`redis_manager`, `zmq_adapter`, `db_session_factory`, `risk_registry`, `pnl_registry`, `account_manager`, `snapshot_service`, `database_url`, `audit_service`, `firm_registry`); lazy `if TYPE_CHECKING` imports khắp nơi; class giữ ~25 thuộc tính state. Đã được Review 1 (Epic 9) flag và **Epic 9 không touch**.
**Impact:** Khó test (phải mock 9 deps), khó wire DI, mỗi feature mới có xu hướng add tham số mới.
**Fix gợi ý:** Split thành `RecoveryOrchestrator` + `LiveOrchestrator` + `EngineLifecycle`; dùng DI container (review 2 đã đề xuất `pydantic-settings` v2).

### D2 — Coexistence rule source [MEDIUM]

**Vị trí:** `src/accounts/models.py:validate_rules_source`, `src/rules/preset_loader.py` vs `src/config/firm_registry.py`
**Symptom:** 2 đường rule source song song:
- **Legacy**: `prop_firm: "ftmo"` field → `PresetLoader` đọc `src/rules/presets/ftmo.yaml`
- **Mới (P0.11)**: `firm_id + product_id + phase` → `FirmRegistry` đọc `configs/firms/ftmo.yaml`

`AccountConfig.validate_rules_source` enforce chỉ được dùng 1 nguồn nhưng cả 2 path còn live. Còn **79 mention `FTMO/ftmo`** trong `services/trading-engine/src/` (giảm từ 142 trước Epic 9, vẫn chưa zero).

**Follow-up debt** đã queue (xem `docs/epic-9-context.md` §P0.3 follow-up):
1. Bootstrap Alembic + port migrations 005-009.
2. Drop `prop_firm` field + `VALID_PROP_FIRMS` frozenset.
3. Drop `prop_firms` reference table + `accounts.prop_firm_id` FK.

**Khuyến nghị:** Làm cleanup story (3 PR nhỏ) sau khi confirm tất cả account đã chuyển sang firm-bound.

### D3 — Audit fire-and-forget [HIGH]

**Vị trí:** `audit_task_done_callback` được dùng ≥7 lần ở `src/engine.py` (lines 194, 360, 662, 697, 753) + `src/rules/audit_registry.py:116` + định nghĩa ở `src/rules/audit_logger.py:280`.
**Symptom:** Pattern `task = asyncio.create_task(audit.log_*(...)); task.add_done_callback(audit_task_done_callback)` — task không await, có thể bị cancel khi SIGTERM trước khi flush DB.
**Impact:** Vi phạm **double-entry discipline** trong `.claude/rules/database/audit.md` và `.claude/rules/common/security.md` §"All write paths to account.* tables MUST go through audit_log write first". Risk: lệnh đã gửi ZMQ, audit row chưa kịp ghi DB → ghi log mất khi crash.
**Fix gợi ý:** Thay bằng `asyncio.TaskGroup` (Python 3.11+) hoặc bounded queue + worker; ghi DB **đồng bộ trước** khi mutate state (true double-entry); graceful_shutdown drain queue trước khi exit.
**Status Epic 9:** Review 1 flag C2 — không nằm trong scope, **chưa fix**.

### D4 — MT5 multi-instance multi-port chưa có [MEDIUM]

**Vị trí:** `services/mt5-bridge/src/config.rs:25-39`
**Symptom:** Bridge config single set port `5555/5556/5557` (default + env override). Doc `architecture.md:1990-2011` mô tả "Option 1: Multiple MT5 Instances ports 5555/5565/5575" là kế hoạch, code chưa có.
**Impact:** Hiện tại chỉ chạy được **1 MT5 instance** ở 1 thời điểm. account_id chỉ là field định tuyến trong JSON message, không có physical isolation per broker.
**Khuyến nghị:** YAGNI cho đến khi có nhu cầu broker thứ 2 thật sự. Khi cần → mở rộng `Config` thành `Vec<BridgeInstance>`, mỗi instance binding riêng.

### D5 — Live orchestrator còn mỏng [HIGH → CRITICAL nếu live]

**Vị trí:** `src/engine.py:615-680` (`run()`)
**Symptom:** Đọc `engine.run()`:
```
1. _initialize_crash_recovery()
2. _initialize_cold_storage()
3. _initialize_trade_audit()
4. _initialize_violation_tracking()
5. _initialize_daily_snapshots()
6. _initialize_graceful_shutdown()
7. logger.info("running"); self._running = True
8. await self._graceful_shutdown.wait_for_shutdown_signal()
```

Tức là `engine.run()` = recovery init + chờ SIGTERM. Live event loop dựa **hoàn toàn** vào Nautilus `Strategy.on_bar` — không có module riêng giữ trách nhiệm "instantiate Nautilus engine, attach actors, wire data adapters". Review 3 (Epic 9) đã flag là **P0 production blocker #1** "Live orchestrator vắng mặt".

**Impact:** Live mode hiện đang relies on cấu hình Nautilus được wire ở đâu đó ngoài `TradingEngine`. Khi cần thêm Actor (vd `PropFirmComplianceActor` cho live, không chỉ backtest) hoặc data adapter, không có nơi rõ ràng.
**Fix gợi ý:** Tạo `LiveOrchestrator` chịu trách nhiệm: build `LiveNode`/`TradingNode`, attach `PropFirmComplianceActor` per account, wire `RedisDataClient` + `ZmqExecutionClient`, expose `start()/stop()`.

### D6 — Race validate↔send [MEDIUM]

**Vị trí:** `src/execution/validated_adapter.py` đọc `RiskStateRegistry` in-memory.
**Symptom:** `ValidatedZmqAdapter` validate rule dùng risk state in-memory; nếu 2 signal gần nhau cho cùng account, snapshot có thể chưa update giữa validate và send. Review 1 C3 đã flag.
**Fix gợi ý:** Bọc validate+send trong critical section đọc Redis snapshot atomic — Lua script hoặc WATCH/MULTI/EXEC.
**Status Epic 9:** không trong scope, **chưa fix**.

### D7 — Production readiness P0 còn thiếu [HIGH → CRITICAL nếu live]

Từ Review 3 của Epic 9, các P0 blocker chưa giải quyết (Epic 9 chỉ giải quyết #3 consistency rule):

| # | Blocker | Status |
|---|---|---|
| 1 | Live orchestrator vắng mặt | ❌ — D5 |
| 2 | Strategy gọi thẳng `order_factory.bracket()` bypass rule engine | ⚠️ partial — `BracketStrategyMixin` + `ValidatedZmqAdapter` được thêm, cần audit toàn bộ strategy có đi qua validation gate hay không |
| 3 | Consistency rule (FTMO 50%) | ✅ shipped P0.7 |
| 4 | Kill-switch CLI không flat positions | ❌ |
| 5 | News blackout | ❌ |
| 6 | Backtest zero slippage/commission | ⚠️ partial — P0.13 wire commission per-firm; spread/swap chưa (xem D8) |

**Khuyến nghị:** Mở Epic 10 "Operational Hardening" gom #1, #2 (audit), #4, #5.

### D8 — Backtest spread/swap parity chưa wire [MEDIUM]

**Vị trí:** `src/backtesting/job_config.py` — `VenueSpec`
**Symptom:** P0.13 (shipped 2026-04-28) đã wire `commission_per_lot_usd` per-firm vào Nautilus `PerContractFeeModel`. P0.13 notes ghi rõ: "spread_pips and swap fields are not yet wired into the backtest venue. This is scope for P0.14 E2E parity". P0.14 đã ship nhưng vẫn để `Future work queued`.
**Impact:** Backtest result lệch live ở mặt slippage cost — FTMO consistency/profit target fail trong backtest có thể không phản ánh đúng live (và ngược lại).
**Fix gợi ý:** Mở story riêng "Backtest venue parity v2" — `spread_pips`, `swap_long`/`swap_short` per-firm config, áp dụng qua Nautilus `MarketSimulator`.

### D9 — Untracked compliance reports [LOW]

**Vị trí:** `services/trading-engine/compliance-report-test-001-{2026-04-21,2026-04-27}.json` (theo `git status` tại thời điểm review).
**Symptom:** 3 file output reports đang untracked, có format date suffix → có vẻ là output CLI `accounts report` hoặc tương tự, không nên commit.
**Fix gợi ý:** Thêm `services/trading-engine/compliance-report-*.json` vào `.gitignore`. Hoặc redirect output về `services/trading-engine/dist/` (đã có).

### D10 — Schema double-source-of-truth `prop_firm_id` ↔ `firm_id` [LOW]

**Vị trí:** `infra/timescaledb/init.sql:30-50` + migration `009_multi_firm_account_binding.sql`
**Symptom:** `accounts` table có cả `prop_firm_id VARCHAR(50) REFERENCES prop_firms(id)` (legacy) và `firm_id + product_id + phase + rule_overrides` (mới P0.3). Cross-column CHECK enforce all-or-nothing firm binding nhưng không enforce mutual-exclusion với `prop_firm_id`.
**Impact:** Nếu ops set cả 2, validation chỉ ở app layer (`validate_rules_source`) — DB không gác.
**Fix gợi ý:** Nằm trong cleanup queue D2; sau khi drop `prop_firm` field, drop luôn cột `prop_firm_id` và bảng `prop_firms`.

---

## 6. Recommendations (priority ordered)

### Đợt 1 — Foundation hardening (CRITICAL/HIGH cho live)

1. **D5 + D1**: Tách `TradingEngine` → `RecoveryOrchestrator` + `LiveOrchestrator` + `EngineLifecycle`. DI container thay 9 optional deps. Đây là precondition cho mọi thứ còn lại. *Effort ~ L*
2. **D3**: Refactor audit pattern — TaskGroup hoặc bounded queue + worker; ghi DB sync trước khi mutate state. *Effort ~ M*
3. **D6**: Atomic validate+send qua Redis Lua hoặc WATCH/MULTI/EXEC. *Effort ~ S-M*
4. **D7 #4 + #5**: Kill-switch flat-positions + news blackout rule. Cả 2 là gating cho live thật. *Effort ~ M mỗi món*

### Đợt 2 — Cleanup và maintenance

5. **D2 + D10**: Drop `prop_firm`/`prop_firm_id`/legacy presets sau khi confirm tất cả account đã firm-bound. *Effort ~ S, 3 PR nhỏ*
6. **D8**: Backtest venue spread/swap parity. *Effort ~ M*
7. **D9**: `.gitignore` rule cho compliance reports. *Effort ~ XS*

### Đợt 3 — Infrastructure debt

8. **Bootstrap Alembic** (đã queue Epic 10): port 6 raw migrations vào revisions, kích hoạt schema versioning + rollback. *Effort ~ M*
9. **D4**: Multi-port `mt5-bridge` khi có broker thứ 2 thật sự — YAGNI cho đến lúc đó.

---

## 7. Conclusion

Sandboxed đã build được một kiến trúc trading platform có chiều sâu — đặc biệt sau Epic 9, abstraction multi-firm đã chứng minh được qua test (xem `tests/integration/test_multi_firm_e2e.py` — 22 tests, 4 RuleEngine isolated cho FTMO + 3 The5ers products). Rule engine 3-layer override với safety guard là điểm sáng về design.

Hai khoản nợ lớn nhất hiện nay đều thuộc về **operational integrity** (audit double-entry, live orchestrator) chứ không phải design abstractions. Recommend mở **Epic 10 "Operational Hardening"** trước khi triển khai live với capital, song song với cleanup story để đóng coexistence debt từ Epic 9.

Engine ước tính ~55-65% production-ready (cao hơn 45-55% Review 3 estimate trước Epic 9 nhờ rule engine + multi-firm + override merger đã solid). Cần ~1 epic nữa để chạm 80%+.

---

**End of review.**
