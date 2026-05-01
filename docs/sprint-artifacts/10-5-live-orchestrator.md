# Story 10.5: LiveOrchestrator — Nautilus LiveNode + PropFirmComplianceActor per account

Status: Backlog

**Effort:** XL
**Phase:** 3 — Live trading P0 blockers
**Findings:** D5 (live orchestrator mỏng) + D7#1 (production blocker #1)
**Predecessor:** Stories 10.1, 10.2, 10.3, 10.4
**Successor:** 10.6 (validation gate audit), 10.7, 10.8

## Story

As a **trader operating Sandboxed live with prop-firm capital**,
I want **engine khởi chạy `LiveOrchestrator` build 1 Nautilus `LiveNode`
per account, attach `PropFirmComplianceActor` (cùng class hiện đang
chạy trong backtest) và wire `RedisDataClient` + `ZmqExecutionClient` cho
mỗi account**,
So that **strategy on_bar event flow chạy qua đúng rule engine
real-time, audit trail và compliance check song song với backtest, và
không có code path "live-only" bypass `PropFirmComplianceActor`**.

## Background

Architecture review 2026-04-30 §D5 + D7#1 flag đây là **P0 production
blocker #1**: `engine.run()` hiện tại = recovery init + chờ SIGTERM.
Live event loop dựa **hoàn toàn** vào Nautilus `Strategy.on_bar` được
wire ở đâu đó ngoài `TradingEngine` — không có module riêng giữ trách
nhiệm "instantiate Nautilus engine, attach actors, wire data adapters".

Backtest đã có `PropFirmComplianceActor` (rename từ `FtmoComplianceActor`
qua P0.4 Epic 9) chạy trong `BacktestNode`, subscribe order/position/bar
events, build `AccountState` qua `account_state_builder`, gọi `RuleEngine`,
cancel orders trên `RuleAction.BLOCK`, log breach. Live mode hiện
**không có actor tương đương**, nên rule check chỉ chạy qua
`ValidatedZmqAdapter` ở pre-trade — thiếu position/equity event-driven
check.

Story 10.5 build `LiveOrchestrator` đầy đủ: 1 `LiveNode` per account
(không 1 node chia sẻ), mỗi node attach `PropFirmComplianceActor` riêng
+ data + execution client riêng, expose `start()/stop()` lifecycle clean.

## Background — Why per-account `LiveNode`?

3 lý do chọn 1 node per account thay vì 1 node chia sẻ:

1. **Risk isolation** — crash của 1 strategy/actor không kéo theo cả
   engine. ADR-005 (per-account risk isolation) đã enforce ở rule engine
   level, mở rộng sang Nautilus level cho consistency.
2. **Per-account venue config** — mỗi account có MT5 broker khác nhau,
   commission/spread/swap khác (per-firm `CommissionProfile` từ Epic 9
   P0.13). `LiveNode` config bind 1 venue duy nhất, multi-venue trong 1
   node làm phức tạp routing.
3. **Phase transition** — account có thể `accounts promote --phase
   funded` runtime; restart 1 node nhẹ hơn restart cả engine.

Trade-off: tốn ~50MB heap mỗi node + ~100ms cold-start per node. Với
MAX_ACCOUNTS=5 → tổng ~250MB + 500ms cold-start, chấp nhận được.

## Acceptance Criteria

### AC1 — `LiveOrchestrator` quản lý dict[account_id, LiveNode]

`src/engine/live_orchestrator.py` (mở rộng skeleton từ 10.1):

```python
class LiveOrchestrator:
    def __init__(
        self,
        account_manager: AccountManager,
        firm_registry: FirmRegistry,
        rule_assignment_service: RuleAssignmentService,
        redis_manager: RedisManager,
        zmq_adapter: ZmqAdapter,
        audit_writer: AuditWriter,  # từ story 10.3
        snapshot_service: SnapshotService,
    ) -> None:
        self._nodes: dict[str, LiveNode] = {}
        self._actors: dict[str, PropFirmComplianceActor] = {}

    async def start(self) -> None:
        for account in self._account_manager.active_accounts():
            node = await self._build_node_for_account(account)
            await node.start_async()
            self._nodes[account.id] = node
        self._snapshot_task = asyncio.create_task(
            self._snapshot_service.flush_loop_5s()
        )

    async def stop(self) -> None:
        await asyncio.gather(*(self._stop_node(a) for a in self._nodes))
        if self._snapshot_task:
            self._snapshot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._snapshot_task

    async def add_account(self, account_id: str) -> None:
        """Hot-add account runtime (vd sau accounts promote --phase)."""
        ...

    async def remove_account(self, account_id: str) -> None: ...
```

### AC2 — `_build_node_for_account` shared với backtest

`_build_actors_for_account` helper được cả live và backtest gọi (DRY,
no divergence):

```python
def _build_actors_for_account(
    account: AccountConfig,
    rule_engine: RuleEngine,
    audit_writer: AuditWriter,
) -> list[Actor]:
    """Shared giữa LiveOrchestrator và BacktestRunner."""
    return [
        PropFirmComplianceActor(
            account_id=account.id,
            rule_engine=rule_engine,
            audit_writer=audit_writer,
        ),
        # future: NewsBlackoutActor (story 10.8) cũng wire cùng đường này
    ]
```

`BacktestRunner` (`src/backtesting/runner_facade.py`) refactor để gọi
helper này thay vì tự build actor — đảm bảo live và backtest dùng cùng
1 set actor.

### AC3 — `RedisDataClient` wire bars subscription per account

Mỗi `LiveNode` có 1 `RedisDataClient` subscribe `bars:*` (theo
`account.signal_filter.symbols`) → push `Bar` event vào node:

```python
class RedisDataClient(DataClient):
    """Nautilus DataClient adapter — đọc bars:* từ Redis Pub/Sub."""

    def __init__(self, redis_manager, symbols, timeframes): ...

    async def _start(self) -> None:
        for symbol, tf in self._symbol_tf_pairs:
            channel = f"bars:{symbol}:{tf}"
            await self._redis.subscribe(channel, self._on_bar_message)

    async def _on_bar_message(self, raw: dict) -> None:
        bar = parse_bar(raw)
        self._handle_bar(bar)  # Nautilus DataClient API
```

Filter symbols theo `account.signal_filter.symbols`. Nếu account không
filter (empty list) → subscribe wildcard `bars:*`.

### AC4 — `ZmqExecutionClient` wire order command per account

Mỗi `LiveNode` có 1 `ZmqExecutionClient` (Nautilus `ExecutionClient`
subclass) gửi order qua ZMQ :5557 → `mt5-bridge`. Wrap đường này bằng
`ValidatedZmqAdapter` (Epic 9 P0.12) để rule engine check trước khi
send:

```python
class ZmqExecutionClient(LiveExecutionClient):
    def __init__(
        self,
        validated_adapter: ValidatedZmqAdapter,  # đã có rule check
        account_id: str,
    ): ...

    async def _submit_order(self, command: SubmitOrder) -> None:
        order = command.order
        result = await self._validated_adapter.validate_and_send(
            account_id=self._account_id,
            order=convert_to_internal_order(order),
        )
        if result.action == RuleAction.BLOCK:
            self._handle_order_rejected(order, reason=result.reason)
            return
        self._handle_order_submitted(order, mt5_ticket=result.ticket)
```

Strategy `Strategy.submit_order` Nautilus path bây giờ chạy qua đúng
validation gate.

### AC5 — `PropFirmComplianceActor` per account, isolated state

```python
@dataclass(frozen=True)
class PropFirmComplianceActorConfig(ActorConfig):
    account_id: str
    rule_engine_factory: Callable[[], RuleEngine]
    audit_writer: AuditWriter

class PropFirmComplianceActor(Actor):
    def __init__(self, config: PropFirmComplianceActorConfig):
        super().__init__(config)
        self._rule_engine = config.rule_engine_factory()
        self._audit = config.audit_writer

    def on_position_event(self, event: PositionEvent) -> None: ...
    def on_order_filled(self, event: OrderFilled) -> None: ...
    def on_bar(self, bar: Bar) -> None:
        # Real-time consistency rule check (cho FTMO 50%, P0.7 Epic 9)
        ...
```

Mỗi actor bind 1 `account_id` duy nhất, dùng `RuleEngine` instance
riêng (resolved qua `RuleAssignmentService` cho `firm_id +
product_id + phase + rule_overrides`). Không share state cross account.

### AC6 — Hot account add/remove (10.10 phase transition support)

`accounts promote --phase funded` (Epic 9 P0.10) đã ship audit entry
+ DB update. Story 10.5 thêm `LiveOrchestrator.reload_account(account_id)`
hook:

```python
async def reload_account(self, account_id: str) -> None:
    """Gọi sau khi accounts promote --phase — restart node với rule
    engine mới."""
    await self.remove_account(account_id)
    await self.add_account(account_id)
```

CLI `accounts promote` sau khi DB write thành công → publish Redis
event `account:phase-changed:{account_id}` → engine subscribe → call
`reload_account()`. Reload time target < 2s (acceptable downtime).

### AC7 — Health surface

`LiveOrchestrator.health()` returns:

```python
@dataclass(frozen=True)
class LiveOrchestratorHealth:
    accounts_running: int
    accounts_failed: list[tuple[str, str]]  # (account_id, last_error)
    redis_connected: bool
    zmq_connected: bool
    last_bar_received_at: dict[str, datetime]
    last_order_sent_at: dict[str, datetime]
```

Push lên `health:trading-engine` Redis key (TTL 30s) mỗi 5s. CLI `health`
(/health slash command) đọc từ đây.

### AC8 — Crash isolation

Nếu 1 `LiveNode` crash (vd MT5 disconnect persistent, broker reject N
lần):

- Node đó mark `failed`, log audit `EventType.NODE_CRASHED`.
- Account đó pause (`account_manager.pause(account_id, reason="node_crash")`).
- Other nodes **không bị ảnh hưởng** — engine tiếp tục chạy.
- Telegram alert `alerts:system:critical` published.

Test: kill 1 MT5 mock connection runtime → assert other 4 accounts
continue trading.

### AC9 — E2E test

`tests/integration/engine/test_live_orchestrator_e2e.py`:

1. **Build live orchestrator** với 2 account (1 FTMO, 1 The5ers
   Bootstrap), mock Redis bars feed + mock ZMQ MT5 bridge.
2. **Inject bar event** `bars:XAUUSD:H1` → assert cả 2 account's
   strategy receive bar (qua `RedisDataClient`).
3. **Strategy submit order** → assert đi qua `ValidatedZmqAdapter` →
   ZMQ send to mock bridge → assert order received với correct account_id.
4. **Position event** từ mock bridge → assert
   `PropFirmComplianceActor` nhận event, build `AccountState`, gọi
   `RuleEngine.validate`.
5. **Daily loss breach** simulate → assert `RuleAction.BLOCK` →
   `validated_adapter` reject next order + audit log.
6. **Graceful shutdown** → assert all nodes stopped, snapshot persisted,
   audit drained.

### AC10 — Backtest parity check

E2E backtest test (`test_multi_firm_e2e.py` 22 tests) chạy lại sau
10.5 — kết quả PnL trade-by-trade phải khớp 100% với baseline trước 10.5
(vì shared `_build_actors_for_account` không thay đổi backtest logic).

Nếu PnL drift > 0.001% → block ship, phân tích divergence.

## Out of Scope

- News blackout actor — story 10.8 (sẽ wire qua cùng
  `_build_actors_for_account`).
- Multi-MT5 instance support (account A → bridge instance 1, account B
  → bridge instance 2) — D4, defer Epic 11+.
- Observability surface (Prometheus/OpenTelemetry) — defer Epic 11+.
- Order modify/cancel mid-flight — defer Epic 11+.

## Test Plan

- [ ] Unit tests: `uv run pytest tests/unit/engine/test_live_orchestrator.py`
      ≥ 80% coverage.
- [ ] Integration: `uv run pytest tests/integration/engine/test_live_orchestrator_e2e.py`
      pass.
- [ ] Backtest parity: `uv run pytest tests/integration/test_multi_firm_e2e.py`
      kết quả khớp 100% với baseline.
- [ ] Cold-start time: 5 account `LiveOrchestrator.start()` complete <
      3s (benchmark).
- [ ] Hot reload: `reload_account()` complete < 2s (benchmark).
- [ ] Crash isolation: kill 1 mock MT5 → other 4 accounts vẫn submit
      order successfully trong 30s sau.
- [ ] Memory: 5 account RSS < 500MB (vs baseline ~150MB pre-Epic 10).
- [ ] Health surface: `redis-cli GET health:trading-engine` returns
      valid JSON sau 5s start.

## References

- **Epic context:** `docs/epic-10-context.md` §Architectural Decisions §1
- **Source review:** `docs/architecture-review-2026-04-30.md` D5 + D7#1
- **Predecessor stories:** 10.1 (engine split skeleton), 10.2 (DI),
  10.3 (`AuditWriter`), 10.4 (atomic validate+send)
- **Backtest reference:** `src/backtesting/runner_facade.py`
  (existing `PropFirmComplianceActor` wiring)
- **Validation adapter:** `src/execution/validated_adapter.py` (Epic 9
  P0.12 `ValidatedZmqAdapter`)
- **Phase transition:** `src/cli/accounts.py` `promote` command (Epic 9
  P0.10)
- **NautilusTrader docs:** Live trading guide via `mcp__context7__query-docs`
  (`/nautilus-trader/nautilus-trader` topic "live trading node")
