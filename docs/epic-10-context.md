# Epic 10: Operational Hardening — Technical Context

**Created:** 2026-05-01
**Last updated:** 2026-05-01
**Status:** **In Progress** — Phase 1–4 (10 stories done, 5 backlog); Phase 5 gated by 10.11 ops sign-off
**Epic:** 10 of 10+
**Stories:** 15 (10.1 – 10.15)
**Predecessor:** Epic 9 (Multi-firm Foundation) — closed 2026-04-30 (head `e9e9b5f`)
**Source review:** `docs/architecture-review-2026-04-30.md`

---

## Overview

### Problem Statement

Sau khi Epic 9 đóng (multi-firm foundation), architecture review
2026-04-30 đánh giá engine **~55-65% production-ready** — đủ chắc về
abstraction nhưng còn **2 nhóm nợ vận hành** chặn việc cấp capital thật:

1. **Operational integrity gaps** — God-object `TradingEngine` (9 optional
   deps, lazy imports, ~25 thuộc tính state), audit fire-and-forget vi
   phạm double-entry discipline, race condition giữa validate↔send,
   live orchestrator vắng mặt.
2. **P0 production blockers** từ Review 3 của Epic 9 còn 3 mục chưa làm:
   live orchestrator full, news blackout rule, kill-switch flat-positions.

Đồng thời, Epic 9 để lại **coexistence debt**: legacy `prop_firm` field
+ `prop_firms` reference table + 79 mention `FTMO/ftmo` còn live trong
`services/trading-engine/src/`. Schema migrations vẫn là raw SQL, Alembic
chưa bootstrap dù `.claude/rules/database/schema.md` mandate.

Live trading với capital thật **không được phép bắt đầu** trước khi 4
mục bên dưới được giải quyết: live orchestrator, audit double-entry,
race fix, kill-switch flat + news blackout.

### Solution

Chia Epic 10 thành **5 phase tuần tự** — mỗi phase đóng 1 nhóm nợ:

1. **Phase 1 — Architectural foundation** (precondition cho mọi thứ còn
   lại): tách `TradingEngine` god-object thành 3 component chuyên biệt
   (`RecoveryOrchestrator`, `LiveOrchestrator`, `EngineLifecycle`); thay 9
   optional deps bằng DI container `pydantic-settings v2`.
2. **Phase 2 — Audit double-entry & race fix**: đổi pattern
   fire-and-forget thành bounded queue + worker, ghi DB sync trước khi
   mutate state; bọc validate+send trong critical section atomic
   (Redis Lua hoặc WATCH/MULTI/EXEC).
3. **Phase 3 — Live trading P0 blockers**: xây `LiveOrchestrator` full
   (build `LiveNode`, attach `PropFirmComplianceActor` per account, wire
   data + execution clients); audit toàn bộ strategy đi qua
   `ValidatedZmqAdapter`; kill-switch CLI flat positions; news blackout
   rule.
4. **Phase 4 — Backtest parity + infra debt**: wire spread/swap per-firm
   vào backtest venue; bootstrap Alembic và port 6 raw migrations
   (005-010) vào revisions.
5. **Phase 5 — Legacy cleanup** (gated bởi ops cutover audit): drop
   `prop_firm` field + `VALID_PROP_FIRMS`, drop preset YAML legacy +
   `PresetLoader`, migration drop `prop_firm_id` + `prop_firms` table,
   `.gitignore` compliance reports.

### Scope (MVP)

**In Scope:**

- Refactor `TradingEngine` → `RecoveryOrchestrator` + `LiveOrchestrator`
  + `EngineLifecycle`; DI container thay 9 optional deps.
- Audit fire-and-forget → bounded queue + worker; double-entry: ghi DB
  sync trước khi mutate state; drain trên graceful_shutdown.
- Atomic validate+send qua Redis Lua hoặc WATCH/MULTI/EXEC.
- `LiveOrchestrator` full: build `LiveNode`, attach `PropFirmComplianceActor`
  per account, wire `RedisDataClient` + `ZmqExecutionClient`, expose
  `start()/stop()` lifecycle.
- Audit strategy validation gate: tất cả strategy trong
  `services/trading-engine/src/strategies/` đi qua `ValidatedZmqAdapter`,
  không bypass `order_factory.bracket()`.
- Kill-switch CLI flat positions: `emergency:stop` Redis broadcast đóng
  vị thế mở qua `OrderGateway.cancel_order` + `flatten_position`.
- News blackout rule: rule type mới + ForexFactory/economic-calendar feed,
  block lệnh trong N phút quanh high-impact event.
- Backtest venue spread/swap parity: `spread_pips`, `swap_long`,
  `swap_short` per-firm vào Nautilus `MarketSimulator`.
- Bootstrap Alembic; port 6 raw migrations (`005_state_snapshots.sql` …
  `010_rename_ftmo_audit_events.sql`) vào revisions với `upgrade()` +
  `downgrade()` đầy đủ.
- Migration audit + production cutover gating script (10.11).
- Drop `prop_firm` field từ `AccountConfig`, drop `VALID_PROP_FIRMS` frozenset,
  drop `validate_prop_firm_preset` validator.
- Drop `src/rules/presets/*.yaml` + `PresetLoader`.
- Migration drop `accounts.prop_firm_id` + `prop_firms` table.
- `.gitignore` rule cho `services/trading-engine/compliance-report-*.json`.

**Out of Scope (defer):**

- **Multi-port `mt5-bridge`** (D4): chỉ cần khi có broker thứ 2 thật sự.
  YAGNI cho đến lúc đó. Khi cần → mở rộng `Config` thành
  `Vec<BridgeInstance>`, mỗi instance binding riêng.
- Automated phase transition engine (vẫn manual qua CLI).
- Futures gateway (NinjaTrader/Rithmic) — interface đã có ở Epic 9.
- 3rd-party custom rule plugins qua entry points.
- Per-firm payout cycle automation.
- Hyper Growth scaling engine.
- Partial fill, order modify/cancel, swap/commission vào PnL, FX
  conversion, indicator warmup persist (P1 từ Review 3 — defer Epic 11+).

---

## Review Findings — Summary

Tất cả 10 finding (D1–D10) đến từ `docs/architecture-review-2026-04-30.md`.

### CRITICAL (blocker live trading)

Chỉ thành CRITICAL nếu engine được khởi chạy với capital thật. Trước
đó là HIGH.

- **D5 — Live orchestrator còn mỏng**: `engine.run()` = recovery init +
  chờ SIGTERM. Live event loop dựa hoàn toàn vào Nautilus `Strategy.on_bar`,
  không có module riêng giữ trách nhiệm "instantiate Nautilus engine,
  attach actors, wire data adapters". Không có nơi rõ ràng để thêm
  `PropFirmComplianceActor` cho live (chỉ backtest).
- **D7 #4 — Kill-switch CLI không flat positions**: Telegram emergency:stop
  hiện chỉ pause trading, không đóng vị thế mở. FTMO/The5ers compliance
  fail nếu vị thế giữ qua daily reset trong khi engine đã pause.
- **D7 #5 — News blackout rule chưa có**: trading vào high-impact news
  (NFP, FOMC, CPI) — risk slippage + spread widening dẫn đến violate
  daily loss limit.

### HIGH (correctness/integrity risk)

- **D1 — `TradingEngine` god object**: constructor 9 optional deps, ~25
  thuộc tính state, lazy `if TYPE_CHECKING` imports khắp nơi. Khó test
  (mock 9 deps), khó wire DI, mỗi feature mới có xu hướng add tham số.
- **D3 — Audit fire-and-forget**: `audit_task_done_callback` dùng ≥7 lần
  trong `src/engine.py` + `src/rules/audit_registry.py:116`. Pattern
  `asyncio.create_task(audit.log_*(...))` không await, có thể bị cancel
  khi SIGTERM trước khi flush DB. Vi phạm double-entry discipline trong
  `.claude/rules/database/audit.md` và `.claude/rules/common/security.md`
  §"All write paths to account.* tables MUST go through audit_log write
  first".
- **D7 #2 — Strategy bypass rule engine** (partial): `BracketStrategyMixin`
  + `ValidatedZmqAdapter` đã thêm Epic 9, nhưng cần audit toàn bộ strategy
  (`src/strategies/` 5 concrete strategies) có thật sự đi qua validation
  gate không, không gọi thẳng `order_factory.bracket()`.

### MEDIUM (maintainability/scaling)

- **D6 — Race validate↔send**: `ValidatedZmqAdapter` validate dùng
  in-memory `RiskStateRegistry`. Nếu 2 signal gần nhau cho cùng account,
  snapshot có thể chưa update giữa validate và send.
- **D2 — Coexistence rule source**: 2 đường rule source song song:
  - **Legacy**: `prop_firm: "ftmo"` field → `PresetLoader` đọc
    `src/rules/presets/ftmo.yaml`
  - **Mới (P0.11)**: `firm_id + product_id + phase` → `FirmRegistry` đọc
    `configs/firms/ftmo.yaml`

  `AccountConfig.validate_rules_source` enforce 1 nguồn nhưng cả 2 path
  còn live; còn 79 mention `FTMO/ftmo`.
- **D8 — Backtest spread/swap parity chưa wire**: P0.13 ship
  `commission_per_lot_usd` per-firm vào `PerContractFeeModel`, nhưng
  `spread_pips`/`swap_long`/`swap_short` vẫn để "Future work queued"
  trong P0.14 notes.

### LOW (housekeeping)

- **D9 — Untracked compliance reports**: 3 file
  `services/trading-engine/compliance-report-*.json` đang untracked.
- **D10 — Schema double-source `prop_firm_id` ↔ `firm_id`**: `accounts`
  table có cả `prop_firm_id` (legacy) và `firm_id + product_id + phase`
  (mới). DB không enforce mutual-exclusion, chỉ app layer
  `validate_rules_source` gác.

---

## Architectural Decisions

### 1. Tách `TradingEngine` thành 3 component chuyên trách

```python
@dataclass(frozen=True)
class EngineConfig:
    # DI container — single source of truth, không 9 optional deps
    redis_manager: RedisManager
    zmq_adapter: ZmqAdapter
    db_session_factory: DbSessionFactory
    risk_registry: RiskStateRegistry
    pnl_registry: PnLRegistry
    account_manager: AccountManager
    snapshot_service: SnapshotService
    audit_service: AuditService
    firm_registry: FirmRegistry

class RecoveryOrchestrator:
    """Cold-start sau crash. Chạy 1 lần khi engine start."""
    async def run(self) -> RecoveryResult:
        # 1. CrashRecoveryManager.load_snapshot
        # 2. PositionReconciler.reconcile (trust MT5)
        # 3. DailyPnLRecalculator.recompute_if_stale
        # 4. TradingResumer.rearm_accounts
        ...

class LiveOrchestrator:
    """Live event loop. Chịu trách nhiệm Nautilus lifecycle."""
    async def start(self) -> None:
        # 1. Build LiveNode/TradingNode
        # 2. Attach PropFirmComplianceActor per account
        # 3. Wire RedisDataClient (bars:*) + ZmqExecutionClient
        # 4. node.start(); register strategies
        ...
    async def stop(self) -> None: ...

class EngineLifecycle:
    """Top-level coordinator: recovery → live → graceful shutdown."""
    async def run(self) -> None:
        await recovery.run()
        await live.start()
        await graceful.wait_for_shutdown_signal()
        await live.stop()
        await graceful.persist_final_state()
```

`engine.py` giảm từ 763 LOC → ~200 LOC (thin wrapper). Logic phân về 3
class trên + `EngineConfig` DI container.

### 2. Audit double-entry — bounded queue + worker, sync DB trước mutation

**Principle: ghi DB xong mới mutate state.**

```python
class AuditWriter:
    def __init__(self, session_factory, queue_size=10_000):
        self._queue: asyncio.Queue[AuditEntry] = asyncio.Queue(queue_size)
        self._session_factory = session_factory

    async def log_sync(self, entry: AuditEntry) -> None:
        """Ghi DB đồng bộ — block caller cho đến khi commit."""
        async with self._session_factory() as session:
            session.add(entry.to_model())
            await session.commit()

    async def log_async(self, entry: AuditEntry) -> None:
        """Enqueue cho worker; back-pressure nếu queue full."""
        await self._queue.put(entry)  # block nếu full

    async def worker(self) -> None:
        """Drain queue → batch INSERT → commit."""
        while True:
            batch = await self._drain_batch(max_size=100, timeout=0.5)
            await self._batch_insert(batch)

    async def drain(self) -> None:
        """Gọi từ graceful_shutdown — đợi queue empty trước khi exit."""
        while not self._queue.empty():
            await asyncio.sleep(0.05)
```

**Hot path** (mọi write `account.*` table): dùng `log_sync` ghi DB
trước khi update Redis state hoặc gửi ZMQ. **Cold path** (telemetry,
metrics): dùng `log_async`.

`graceful_shutdown.persist_final_state()` MUST gọi `audit.drain()` trước
khi close DB connection.

### 3. Atomic validate+send qua Redis Lua

Race window hiện tại:

```
T0: validate_adapter.validate(signal)  → đọc snapshot (balance=10k, used=2k)
T1: another signal validate(signal_2)  → đọc snapshot (balance=10k, used=2k)
T2: validate_adapter.send(signal)      → ZMQ → MT5 fill (used=2k+1k=3k)
T3: validate_adapter.send(signal_2)    → ZMQ → MT5 fill (used=3k+1k=4k)
```

Cả 2 signal đều pass rule check vì đọc cùng 1 snapshot, nhưng tổng exposure
có thể vượt limit.

**Fix:** Atomic compare-and-set qua Lua script trên Redis:

```lua
-- atomic_reserve.lua
-- KEYS[1] = snapshot:{account_id}:latest
-- ARGV[1] = required_margin
-- ARGV[2] = max_exposure
local snapshot = cjson.decode(redis.call('GET', KEYS[1]))
local new_used = snapshot.used + tonumber(ARGV[1])
if new_used > tonumber(ARGV[2]) then
  return {0, snapshot.used, snapshot.exposure}  -- reject
end
snapshot.used = new_used
redis.call('SET', KEYS[1], cjson.encode(snapshot))
return {1, new_used, snapshot.exposure}  -- accept
```

`ValidatedZmqAdapter.validate_and_send` flow:

1. Compute `required_margin` từ signal.
2. EVAL `atomic_reserve.lua` — nếu reject → BLOCK + audit log.
3. Nếu accept → ZMQ send_order_and_wait.
4. Trên fail (timeout/reject từ MT5) → EVAL `atomic_release.lua` để
   rollback reservation.

### 4. Kill-switch flat positions — Telegram emergency:stop

Hiện tại `notification` service publish `emergency:stop` → engine subscribe
chỉ để set `_running = False`. Cần thêm flat-positions logic:

```python
async def on_emergency_stop(self, payload: EmergencyStopPayload) -> None:
    audit.log_sync(EventType.EMERGENCY_STOP_TRIGGERED, payload)
    for account in self._account_manager.active_accounts():
        positions = await self._mt5_query_open_positions(account)
        for pos in positions:
            await self._order_gateway.flatten_position(
                account_id=account.id, position_id=pos.id, reason="emergency_stop"
            )
        await self._account_manager.pause(account.id, reason="emergency_stop")
    audit.log_sync(EventType.EMERGENCY_STOP_COMPLETE, ...)
```

### 5. News blackout rule

`NewsBlackoutRule(BaseRule)`:

```python
@dataclass(frozen=True)
class NewsBlackoutConfig:
    blackout_minutes_before: int = 5      # firm-configurable
    blackout_minutes_after: int = 5
    impact_levels: frozenset[str] = frozenset({"high"})
    symbols_filter: frozenset[str] | None = None  # None = all symbols
```

Calendar source: `EconomicCalendarService` (background task fetch
ForexFactory weekly XML 1×/day, cache vào Redis
`calendar:events:{YYYY-MM-DD}` TTL 26h, fallback static file nếu fetch
fail).

Rule check O(log N) qua interval tree built on cache load.

### 6. Bootstrap Alembic — port 6 raw migrations

`alembic/` dir trong `services/trading-engine/`:

- `alembic.ini` — config trỏ `sqlalchemy.url` từ `DATABASE_URL` env
- `alembic/env.py` — autogenerate disabled (manual revisions only)
- `alembic/versions/` — 6 revision file:
  - `005_state_snapshots.py`
  - `006_audit_logs.py`
  - `007_audit_logs_retention_180d.py`
  - `008_rule_violations.py`
  - `009_multi_firm_account_binding.py`
  - `010_rename_ftmo_audit_events.py`

Mỗi revision:

- `upgrade()` thực thi SQL từ file `infra/timescaledb/migrations/0XX*.sql`
  hiện có (port nguyên văn, không refactor).
- `downgrade()` provide reverse — nếu không reversible (drop hypertable
  với data), `raise NotImplementedError("manual restore required")`.

**Bootstrap path:** trên DB hiện tại (đã apply 6 raw migrations bằng tay),
chạy `alembic stamp 010` để mark head mà không re-run. Test trên fresh
DB: `alembic upgrade head` chạy hết.

### 7. Phase 5 cleanup gating — migration audit script

Story 10.11 ship CLI:

```
trading-engine accounts audit-rules-source --strict
```

Output:

- Per-account: `account_id`, `rules_source` ∈ {`firm_bound`, `preset_legacy`,
  `personal_rules_file`}, `firm_id` (nếu applicable).
- Aggregate: count per source.
- Exit code: 0 nếu mọi prop_firm-type account đã `firm_bound`, 1 nếu
  còn account nào dùng `prop_firm` legacy.

Ops chạy command này trên config production, output sign-off vào
`docs/sprint-artifacts/migration-audit-2026-XX-XX.md`. Sign-off này là
precondition cho story 10.12, 10.13, 10.14. Đồng thời cập nhật
`configs/accounts.yaml.example` để chỉ show firm-bound style, mark legacy
section là `[DEPRECATED — removed in Epic 10.12]`.

---

## Story Breakdown

### Phase 1 — Architectural foundation

| # | Story | Effort | Findings | Status | Spec doc |
|---|------|--------|----------|--------|----------|
| 10.1 | Split `TradingEngine` → `RecoveryOrchestrator` + `LiveOrchestrator` + `EngineLifecycle` | XL | D1 + D5 | done (41b54a3) | `10-1-engine-split.md` |
| 10.2 | DI container `EngineConfig` thay 9 optional deps | M | D1 | done (67f60cd) | — |

### Phase 2 — Audit double-entry & race fix

| # | Story | Effort | Findings | Status | Spec doc |
|---|------|--------|----------|--------|----------|
| 10.3 | `AuditWriter` bounded queue + worker; sync DB trước mutation; drain trên graceful_shutdown | L | D3 | done (4e0c76d) | — |
| 10.4 | Atomic validate+send qua Redis Lua (`atomic_reserve.lua` + `atomic_release.lua`) | M | D6 | done (6bfd547) | — |

### Phase 3 — Live trading P0 blockers

| # | Story | Effort | Findings | Status | Spec doc |
|---|------|--------|----------|--------|----------|
| 10.5a | `LiveAccountSession` state machine + per-account lifecycle + crash isolation | part of XL | D5 | done (69694a1) | `10-5-live-orchestrator.md` |
| 10.5b | `RedisDataClient` Nautilus subclass + `bar_translator` + pubsub drain | part of XL | D5 AC3 | done (9f67854) | — |
| 10.5c | `ZmqExecutionClient` Nautilus subclass + `order_translator` + `submit_dispatcher` | part of XL | D5 AC4 | done (b548238) | — |
| 10.5d | Per-account `PropFirmComplianceActor` in live mode | part of XL | D5 AC5 | backlog | — |
| 10.5e1 | Orchestrator wiring: `_build_session_components` + health surface push to Redis | part of XL | D5 AC7 | done (1348253) | — |
| 10.5e2 | `TradingNode` per account + strategy registration + reload subscriber | part of XL | D5 AC1/6/8 | backlog | — |
| 10.5f | Backtest parity baseline diff verification + E2E live test | part of XL | D5 AC9/10 | backlog | — |
| 10.6 | Audit toàn bộ strategy đi qua `ValidatedZmqAdapter` (không bypass `order_factory.bracket()`) | S | D7#2 | done (ff280e0) | — |
| 10.7 | Kill-switch CLI flat positions — `emergency:stop` đóng vị thế mở qua `OrderGateway` | M | D7#4 | done (e462fe0) | — |
| 10.8 | News blackout rule + `EconomicCalendarService` (ForexFactory feed) | M | D7#5 | done (12242a6) | — |

### Phase 4 — Backtest parity + infra debt

| # | Story | Effort | Findings | Status | Spec doc |
|---|------|--------|----------|--------|----------|
| 10.9 | Backtest venue spread parity per-firm (`SpreadAwareFeeModel`); swap deferred to 10.9b | M | D8 | done (ef2ac8b) | — |
| 10.9b | Swap accrual via Nautilus `SimulationModule` rollover | — | D8 follow-up | backlog | — |
| 10.10 | Bootstrap Alembic + port 6 raw migrations (005–010) | M | Epic 9 carry-over | done (dd6702a) | — |

### Phase 5 — Legacy cleanup (gated bởi 10.11 ops cutover)

| # | Story | Effort | Findings | Status | Spec doc |
|---|------|--------|----------|--------|----------|
| 10.11 | Migration audit CLI + production cutover sign-off | S | Pre-Phase 5 gate | backlog | — |
| 10.12 | Drop `prop_firm` field + `VALID_PROP_FIRMS` + `validate_prop_firm_preset` | S | D2 | backlog | — |
| 10.13 | Drop preset YAML legacy (`src/rules/presets/*.yaml`) + `PresetLoader` | S | D2 | backlog | — |
| 10.14 | Migration drop `accounts.prop_firm_id` + `prop_firms` table | S | D2 + D10 | backlog | — |
| 10.15 | `.gitignore` compliance reports (`compliance-report-*.json`) | XS | D9 | backlog | — |

**Total effort:** 1 XS + 5 S + 6 M + 1 L + 2 XL ≈ **3-4 sprint** (6-8
tuần) 1 dev FT.

---

## Dependencies & Sequencing

```
Phase 1: 10.1 → 10.2
                  ↓
Phase 2: 10.3, 10.4 (parallel after 10.2)
                  ↓
Phase 3: 10.5 → 10.6 (parallel) → 10.7, 10.8 (parallel)
                  ↓
Phase 4: 10.9, 10.10 (parallel — independent)
                  ↓
Phase 5: 10.11 → ops sign-off → 10.12, 10.13 (parallel) → 10.14 → 10.15
```

**10.15 (`.gitignore`)** không phụ thuộc ai, có thể ship sớm bất cứ lúc
nào — đặt cuối Phase 5 chỉ vì là cleanup nhất.

**10.10 (Alembic bootstrap)** không thực sự phụ thuộc Phase 1-3 nhưng
giữ ở Phase 4 vì sequence "live trading ready" → "infra debt" hợp lý
khi prioritize live readiness.

---

## Risks & Mitigations

### R1 — Refactor 10.1 break recovery flow

**Risk:** Tách `TradingEngine` ảnh hưởng `state/` modules (~3.5K LOC).
Recovery flow đang được test bởi 5 module nặng (`crash_recovery`,
`position_reconciler`, `daily_pnl_recalculator`, `trading_resumer`,
`graceful_shutdown`).

**Mitigation:**

- 10.1 không thay đổi public API của các state module — chỉ wire lại
  qua `RecoveryOrchestrator`.
- Regression suite: chạy `tests/integration/state/test_crash_recovery_e2e.py`
  + `test_graceful_shutdown_e2e.py` trước/sau mỗi commit của 10.1.
- Spec doc `10-1-engine-split.md` liệt kê đầy đủ contract giữa 3
  orchestrator + lifecycle.

### R2 — Audit sync DB write làm tăng latency hot path

**Risk:** `audit.log_sync` thay `create_task` có thể tăng latency
order-execution path ~10-50ms (DB INSERT + commit).

**Mitigation:**

- Benchmark trước/sau: target p99 latency `validate_and_send` không vượt
  +20ms.
- Nếu vượt: dùng `INSERT … RETURNING` async với connection pool warm,
  hoặc giảm xuống "log_sync only for safety-critical events" (rule
  block, account pause, emergency stop) — non-critical (rule warn,
  metrics) vẫn `log_async`.
- Không đánh đổi correctness lấy latency: order send phải đợi audit
  flush nếu là safety-critical.

### R3 — Atomic reserve.lua làm tăng Redis load

**Risk:** Mỗi `validate_and_send` thêm 1 EVAL roundtrip + JSON serde trên
snapshot.

**Mitigation:**

- Snapshot size ≤ 4KB → JSON serde < 1ms.
- Redis EVAL latency ~0.5ms localhost.
- Nếu Redis CPU > 50% baseline → chuyển sang in-memory `asyncio.Lock`
  per account_id (single-engine assumption — multi-engine deferred).

### R4 — Phase 5 cleanup phá runtime nếu config chưa migrate

**Risk:** Drop `prop_firm` field/`prop_firms` table trước khi mọi
account thực tế chuyển sang firm-bound → engine fail load.

**Mitigation:**

- 10.11 gating story chạy CLI audit trước khi mở khóa 10.12/13/14.
- Audit CLI exit code 1 nếu còn account legacy → CI fail trên branch
  Phase 5.
- Migration 10.14 viết với `IF EXISTS` guard và verify
  `SELECT COUNT(*) FROM accounts WHERE prop_firm_id IS NOT NULL` = 0
  trước khi drop.

### R5 — News blackout calendar feed unavailable

**Risk:** ForexFactory XML feed có thể down hoặc rate-limit.

**Mitigation:**

- Cache 26h trên Redis (1 day overlap).
- Fallback static file `configs/calendar/economic-events-{YYYY}.json`
  manually curated cho week ahead.
- Rule check fail-safe: nếu cả Redis cache và fallback file đều miss →
  log WARN (không BLOCK). Operational responsibility on ops to refresh
  fallback file weekly.

### R6 — Live orchestrator backtest divergence

**Risk:** `LiveOrchestrator` build `LiveNode` khác cách backtest build
`BacktestNode` → strategy behavior khác giữa backtest và live.

**Mitigation:**

- 10.5 spec yêu cầu shared `_build_actors_for_account()` helper được
  cả live và backtest gọi.
- E2E test: 1 strategy chạy backtest 1000 bars + live replay cùng 1000
  bars qua mocked tick stream → kết quả PnL trade-by-trade khớp.

---

## Success Criteria

1. **Live trading gating clear** — sau khi Phase 1-3 đóng, engine có thể
   khởi chạy live với capital thật mà không vi phạm:
   - Audit double-entry (mọi write `account.*` có audit row trước).
     **Verified: 10.3 done (4e0c76d); 2465+ tests passing.**
   - Race condition validate↔send (tổng exposure ≤ limit dù concurrent
     signal). **Verified: 10.4 done (6bfd547); atomic Lua scripts + 29 tests.**
   - Emergency stop response time < 5s từ Telegram cmd → tất cả
     position closed. **Verified: 10.7 done (e462fe0); 30 tests.**
   - News blackout: 0 lệnh send trong 5min trước/sau high-impact event
     (verified bằng integration test với mock calendar).
     **Verified: 10.8 done (12242a6); 74 tests.**
   - Live orchestrator: per-account session lifecycle + health surface + client wiring.
     **Partial: 10.5a/b/c/e1 done; 10.5d/e2/f backlog (TradingNode + E2E).**
2. **Test coverage** — Phase 1-3 mỗi story có integration test E2E +
   unit test ≥ 80% coverage. Phase 4 stories có migration test trên
   fresh DB. Phase 5 stories có audit log verifying rows migrated/dropped.
   **Phase 1–4 shipped: full unit suite 2747 passing as of 10.9 (ef2ac8b).**
3. **Schema versioning** — `alembic upgrade head` chạy được trên fresh
   DB, kết quả schema giống hệt `infra/timescaledb/init.sql` post-migration.
   **Verified: 10.10 done (dd6702a); 24 chain-integrity tests.**
4. **Coupling baseline** — sau Phase 5, `grep -ri "FTMO\|ftmo"
   services/trading-engine/src/` returns ≤ 5 occurrences (test fixtures
   only). Hiện tại 79. **Phase 5 not started — gated by 10.11 ops sign-off.**
5. **No regression** — full test suite (`uv run pytest`) green sau mỗi
   story. Backtest E2E `test_multi_firm_e2e.py` (22 tests, FTMO + 3
   The5ers products) vẫn pass.
6. **Engine production-ready** — sau Epic 10 đóng, architecture review
   gen lần kế đánh giá ≥ 80% production-ready (target từ
   `architecture-review-2026-04-30.md` §7 conclusion).
   **Current estimate: Phase 1–4 done raises readiness ~55-65% → ~70-75%;
   full gate requires Phase 5 + 10.5d/e2/f.**

---

## Out-of-Scope Notes

### D4 — Multi-port `mt5-bridge`

Architecture review §6 Đợt 3 #9 đánh giá YAGNI. Hiện tại single MT5
instance ở 1 thời điểm là đủ cho FTMO + The5ers (cả 2 chia sẻ MT5
broker khác nhau nhưng mỗi account chỉ thuộc 1 broker tại một thời
điểm). Khi cần broker thứ 2 thật sự (vd thêm Apex/TopStep với MT5
gateway riêng), mở story riêng:

- Mở rộng `mt5-bridge/src/config.rs` `Config` thành `Vec<BridgeInstance>`.
- Mỗi instance binding port set riêng (5555+10*N pattern).
- `trading-engine` `MT5ConnectionManager` resolve `account_id → bridge_instance`
  từ config.

Defer cho Epic 11+.

### Review 3 P1 items (deferred Epic 11+)

- Partial fill handling (FOK/IOC semantics)
- Order modify/cancel mid-flight
- Swap/commission accumulation vào realized PnL
- FX conversion cho cross-currency accounts
- Indicator warmup persist qua restart
- Observability surface (Prometheus metrics, OpenTelemetry tracing)

---

## References

- **Architecture review:** `docs/architecture-review-2026-04-30.md` (10
  findings D1-D10)
- **Predecessor epic context:** `docs/epic-9-context.md` (Epic 9 closed
  2026-04-30, P0.3 follow-up debt queued)
- **Architecture doc:** `docs/architecture.md` v3.0 (2025-12-07,
  communication matrix L697-708)
- **Source rules:** `.claude/rules/database/audit.md` (double-entry
  discipline), `.claude/rules/common/security.md` (audit_log first
  policy)
- **Spec docs:** `docs/sprint-artifacts/10-1-engine-split.md`,
  `docs/sprint-artifacts/10-5-live-orchestrator.md`

---

**End of Epic 10 context.**
