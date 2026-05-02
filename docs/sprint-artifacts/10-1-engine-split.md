# Story 10.1: Engine Split — RecoveryOrchestrator + LiveOrchestrator + EngineLifecycle

Status: Backlog

**Effort:** XL
**Phase:** 1 — Architectural foundation
**Findings:** D1 (god object) + D5 (live orchestrator mỏng)
**Predecessor:** Epic 9 closed (head `e9e9b5f`)
**Successor:** Story 10.2 (DI container) → Phase 2

## Story

As a **maintainer of the Sandboxed trading engine**,
I want **`TradingEngine` god-object tách thành 3 component chuyên trách
(`RecoveryOrchestrator`, `LiveOrchestrator`, `EngineLifecycle`) với
trách nhiệm riêng và dependencies tường minh**,
So that **lifecycle logic không trộn vào nhau, mỗi component test được
độc lập (≤ 3 deps mỗi class), và có chỗ rõ ràng để Phase 3 wire Nautilus
`LiveNode` + `PropFirmComplianceActor`**.

## Background

`src/engine.py` hiện ~763 LOC, constructor `TradingEngine.__init__` nhận
**9 optional dependencies** (`redis_manager`, `zmq_adapter`,
`db_session_factory`, `risk_registry`, `pnl_registry`, `account_manager`,
`snapshot_service`, `database_url`, `audit_service`, `firm_registry`),
giữ ~25 thuộc tính state, dùng lazy `if TYPE_CHECKING` imports khắp nơi
để tránh circular dependency. `engine.run()` (L615-680) bao gồm cả
recovery init lẫn shutdown wait — không có module riêng cho live event
loop.

Architecture review 2026-04-30 đánh giá đây là **HIGH severity** (D1)
chặn testability + extensibility, và **HIGH→CRITICAL** (D5) cho live
trading vì không có nơi rõ ràng để attach `PropFirmComplianceActor` cho
live (chỉ backtest đã có).

Story này tách 3 component nhưng **không** wire Nautilus `LiveNode` —
phần đó là 10.5. Story này chỉ skeleton + di chuyển logic recovery hiện
hữu vào `RecoveryOrchestrator`.

## Acceptance Criteria

### AC1 — Public API mới ở `src/engine/`

`src/engine.py` (~763 LOC) chuyển thành package `src/engine/`:

```
src/engine/
├── __init__.py              # re-export TradingEngine cho backwards compat
├── lifecycle.py             # EngineLifecycle — top coordinator
├── recovery_orchestrator.py # RecoveryOrchestrator — cold-start
├── live_orchestrator.py     # LiveOrchestrator — placeholder cho 10.5
└── config.py                # EngineConfig dataclass (mở rộng ở 10.2)
```

`__init__.py` re-export `TradingEngine` (alias cho `EngineLifecycle`) để
không phá entry point CLI hiện tại (`src/cli/main.py` import
`from engine import TradingEngine`).

### AC2 — `RecoveryOrchestrator` đảm nhận 5 module recovery

`src/engine/recovery_orchestrator.py`:

```python
@dataclass(frozen=True)
class RecoveryResult:
    recovered_accounts: list[str]
    discrepancies: list[PositionDiscrepancy]
    pnl_recomputed: bool
    snapshot_age_seconds: float

class RecoveryOrchestrator:
    def __init__(
        self,
        crash_recovery: CrashRecoveryManager,
        position_reconciler: PositionReconciler,
        pnl_recalculator: DailyPnLRecalculator,
        trading_resumer: TradingResumer,
    ) -> None: ...

    async def run(self) -> RecoveryResult:
        snapshot = await self._crash_recovery.load_latest_snapshot()
        discrepancies = await self._position_reconciler.reconcile(snapshot)
        pnl_recomputed = await self._pnl_recalculator.recompute_if_stale(snapshot)
        accounts = await self._trading_resumer.rearm_accounts(snapshot)
        return RecoveryResult(...)
```

5 module recovery hiện tại (`CrashRecoveryManager`, `PositionReconciler`,
`DailyPnLRecalculator`, `TradingResumer`, `GracefulShutdown`) **không
thay đổi public API** — chỉ wire qua `RecoveryOrchestrator`.
`GracefulShutdown` ở lại `EngineLifecycle` (vì cần gọi sau live stop).

### AC3 — `LiveOrchestrator` skeleton (full implementation in 10.5)

`src/engine/live_orchestrator.py`:

```python
class LiveOrchestrator:
    def __init__(
        self,
        account_manager: AccountManager,
        snapshot_service: SnapshotService,
        firm_registry: FirmRegistry,
    ) -> None: ...

    async def start(self) -> None:
        """Placeholder — full impl in story 10.5.
        Hiện tại chỉ gọi account_manager.start_all() + snapshot.start_flush_loop()."""
        await self._account_manager.start_all()
        self._snapshot_task = asyncio.create_task(
            self._snapshot_service.flush_loop_5s()
        )

    async def stop(self) -> None:
        await self._account_manager.stop_all()
        if self._snapshot_task:
            self._snapshot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._snapshot_task
```

Tức là 10.1 ship `LiveOrchestrator` chạy giống hành vi `engine.run()`
hiện tại (ngoại trừ recovery đã tách ra), `LiveNode` + `Actor` wiring là
scope 10.5.

### AC4 — `EngineLifecycle` orchestrate recovery → live → shutdown

`src/engine/lifecycle.py`:

```python
class EngineLifecycle:
    def __init__(
        self,
        recovery: RecoveryOrchestrator,
        live: LiveOrchestrator,
        graceful_shutdown: GracefulShutdown,
        audit_service: AuditService,
    ) -> None: ...

    async def run(self) -> None:
        recovery_result = await self._recovery.run()
        await self._audit_service.log_recovery_complete(recovery_result)
        await self._live.start()
        await self._graceful_shutdown.wait_for_shutdown_signal()
        await self._live.stop()
        await self._graceful_shutdown.persist_final_state()
```

`EngineLifecycle` **không nhận** 9 deps như god-object cũ — chỉ nhận 4
(recovery, live, graceful_shutdown, audit_service). DI wiring chuyển
sang factory function `build_engine(config: EngineConfig)` ở
`src/engine/__init__.py` (full DI container shipping ở 10.2).

### AC5 — Backwards compat shim cho CLI

`src/cli/main.py` và `src/cli/accounts.py` hiện gọi `TradingEngine(...)`
trực tiếp. Để không phá CLI:

`src/engine/__init__.py`:

```python
from engine.lifecycle import EngineLifecycle as TradingEngine

def build_engine(config: EngineConfig) -> TradingEngine:
    """Factory — tạm thời ở đây, di chuyển sang DI container ở 10.2."""
    recovery = RecoveryOrchestrator(
        crash_recovery=CrashRecoveryManager(...),
        position_reconciler=PositionReconciler(...),
        pnl_recalculator=DailyPnLRecalculator(...),
        trading_resumer=TradingResumer(...),
    )
    live = LiveOrchestrator(
        account_manager=config.account_manager,
        snapshot_service=config.snapshot_service,
        firm_registry=config.firm_registry,
    )
    graceful = GracefulShutdown(...)
    return TradingEngine(recovery, live, graceful, config.audit_service)

__all__ = ["TradingEngine", "EngineLifecycle", "RecoveryOrchestrator",
           "LiveOrchestrator", "EngineConfig", "build_engine"]
```

CLI vẫn dùng `from engine import TradingEngine` — không thay đổi import
path.

### AC6 — `engine.py` package giảm còn ≤ 250 LOC tổng

Sau split, tổng LOC trong `src/engine/` (4 file mới) ≤ 250 (vs 763 LOC
hiện tại). Logic recovery/live/lifecycle phân về đúng class; lazy
imports được loại bỏ (3 class chuyên biệt → import thẳng).

### AC7 — Test isolation

Mỗi class mới có unit test riêng, mock ≤ 3 deps:

- `tests/unit/engine/test_recovery_orchestrator.py` — mock 4 modules,
  assert sequence call + RecoveryResult fields.
- `tests/unit/engine/test_live_orchestrator.py` — mock 3 deps, assert
  start/stop không leak task.
- `tests/unit/engine/test_lifecycle.py` — mock 4 deps, assert
  recovery → live.start → wait → live.stop → persist sequence.

Coverage ≥ 80% cho mỗi file mới. Mock count per test ≤ 3.

### AC8 — Regression test E2E

Chạy được full suite hiện tại không thay đổi:

- `tests/integration/state/test_crash_recovery_e2e.py` — recovery flow
  end-to-end (ghi snapshot → kill → restart → verify positions
  reconciled).
- `tests/integration/state/test_graceful_shutdown_e2e.py` — SIGTERM →
  drain → final snapshot persist.
- `tests/integration/test_multi_firm_e2e.py` (Epic 9, 22 tests, FTMO
  + 3 The5ers) — vẫn pass.

Nếu integration test fail → block 10.1 ship. Recovery flow là cao
risk, không tolerable regression.

### AC9 — Migration plan trong CHANGELOG / commit body

Commit message body ghi rõ:

- `TradingEngine` từ `src/engine.py` → `src/engine/__init__.py` (alias
  cho `EngineLifecycle`).
- Public API không đổi cho consumer ngoài (CLI, test fixtures, docs).
- Internal: 9 optional deps tạm còn ở `build_engine` factory; 10.2 sẽ
  thay bằng `EngineConfig` DI container.

### AC10 — No new feature — pure refactor

Story 10.1 KHÔNG add feature mới (không wire Nautilus, không thêm rule,
không sửa audit). Mọi behavior phải khớp 100% với `e9e9b5f` baseline.
Nếu test fail trên baseline behavior, rollback và phân tích lại trước
khi proceed.

## Out of Scope

- DI container `EngineConfig` đầy đủ — story 10.2.
- Wire Nautilus `LiveNode` + `PropFirmComplianceActor` per account —
  story 10.5.
- Audit pattern refactor (fire-and-forget → bounded queue) — story 10.3.
- Atomic validate+send — story 10.4.

## Test Plan

- [ ] Unit tests pass: `uv run pytest tests/unit/engine/`
- [ ] Integration tests pass: `uv run pytest tests/integration/state/`
- [ ] Multi-firm E2E pass: `uv run pytest tests/integration/test_multi_firm_e2e.py`
- [ ] Coverage ≥ 80% for new files: `uv run pytest --cov=src/engine
      --cov-report=term-missing`
- [ ] LOC budget: `wc -l src/engine/*.py` ≤ 250 total
- [ ] Mock count per unit test ≤ 3 (manual review)
- [ ] CLI smoke: `trading-engine accounts status` returns same output
      pre/post refactor
- [ ] No new lazy imports: `grep -rn "if TYPE_CHECKING" src/engine/`
      returns 0 lines

## References

- **Epic context:** `docs/epic-10-context.md` §Architectural Decisions §1
- **Source review:** `docs/architecture-review-2026-04-30.md` D1 + D5
- **Predecessor:** `src/engine.py` (763 LOC, head `e9e9b5f`)
- **State modules:** `src/state/crash_recovery.py`,
  `src/state/position_reconciler.py`, `src/state/daily_pnl_recalculator.py`,
  `src/state/trading_resumer.py`, `src/state/graceful_shutdown.py`
