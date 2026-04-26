# Epic 9: Multi-firm Foundation — Technical Context

**Created:** 2026-04-19
**Status:** Planning (pre-implementation)
**Epic:** 9 of 9+
**Stories:** 16 (P0.1 – P0.16, P0.9 dropped)
**Predecessor:** Epic 8 (Strategies & Backtesting) — 8.8/8.9 still in flight

---

## Overview

### Problem Statement

Sau 4 review (architecture / design / operational / multi-firm), trading-engine
hiện tại được xây dựng với giả định ngầm **FTMO-only**:

- `grep FTMO` ra **142 occurrences trên 40 file** — coupling leak sâu vào
  backtest actor, metrics, preset loader, report, account model.
- 3 file preset YAML tồn tại (`ftmo.yaml`, `the5ers.yaml`, `wmt.yaml`) nhưng
  chỉ dùng chung **5 rule type**; không biểu diễn được khác biệt cấu trúc
  giữa các prop firm (phase transitions, scaling plan, product variants,
  DD calculation method, session timezone).
- Naming (`FtmoComplianceActor`, `FtmoMetrics`, `ftmo_compliance` event type)
  khiến không thể thêm firm thứ 2 mà không refactor code core.

Engine đang đạt ~45-55% production-ready (xem review 3 dưới đây), nhưng vì
coupling FTMO, *mỗi firm thêm vào sẽ cần refactor core* thay vì config.

### Solution

Introduce **`FirmProfile`** abstraction làm đơn vị tổ chức first-class:
mỗi firm = tập rules + products + phases + session + commission + symbol
policy. Engine core không biết firm cụ thể nào; runtime load firm profile
từ `configs/firms/*.yaml`, resolve rule set qua `(firm_id, product_id, phase)`.

Rename 1-shot `FTMO*` → `PropFirm*` (code + event_type trong audit_logs qua
Alembic migration). Thêm 3 rule type mới (`consistency`, `weekly_target`,
DD variants) để biểu diễn The5ers products. Per-account rule overrides
cho phép siết chặt threshold (không được nới lỏng) — foundation cho ops
tuning từng account mà không đụng firm config.

### Scope (MVP)

**In Scope:**
- `FirmProfile` + `AccountProduct` + `AccountPhase` data model
- `FirmRegistry` loader từ `configs/firms/*.yaml`
- `Account` model refactor: `firm_id + product_id + phase + rule_overrides`
- Rename `FTMO*` → `PropFirm*` + Alembic migration audit_logs event_type
- 2 firm profile đầy đủ: **FTMO** + **The5ers (3 products)**
- 3 rule type mới: `consistency` (real-time warn), `weekly_target`,
  DD variants (`equity_peak` vs `balance_based`)
- Timezone-aware daily reset theo `FirmProfile.session`
- CLI `accounts promote --phase <p>` — manual transition với audit
- Per-account `rule_overrides` merge + safety guard (không cho loosen)
- `OrderGateway` Protocol interface (chuẩn bị cho futures tương lai,
  không implement non-MT5)
- `CommissionProfile` per-firm cho backtest parity
- E2E test: FTMO + 3 The5ers products cùng engine

**Out of Scope (defer):**
- Automated phase transition engine (manual only cho MVP)
- `min_holding_duration` rule + `validate_open`/`validate_close` split
  (dropped — không product nào trong MVP cần)
- Futures gateway (NinjaTrader/Rithmic) — chỉ design interface
- 3rd-party custom rule plugins qua entry points
- Per-firm payout cycle automation
- Hyper Growth scaling engine (chỉ YAML, không implement logic)

---

## Review Findings — Summary

### Review 1: Architecture (bugs/risks)

**CRITICAL:**
- **C1 — Timezone drift CET↔UTC**: `ftmo.yaml` khai `timezone: "CET"`
  nhưng `daily_snapshot_service.py:73` và `risk_state.py:71 reset_daily`
  hardcode UTC. Cửa sổ 1-2h/ngày + DST có thể fail challenge.
- **C2 — Fire-and-forget audit** vi phạm double-entry discipline
  (`database/audit.md`). `asyncio.create_task(...)` không tracked, cancel
  khi SIGTERM.
- **C3 — Race validate↔send**: `ValidatedZmqAdapter` đọc in-memory
  `RiskStateRegistry`, không đọc Redis snapshot atomic.

**HIGH:** God object `TradingEngine` (758 LOC, 9 optional deps, lazy imports);
`dict` context không type-safe; `trading_days_count=1` hardcode; ZMQ 5s
timeout không trigger reconcile; rule_check audit chỉ Redis TTL 24h.

### Review 2: Design (thừa/thiếu/cải thiện)

**Thừa:** 4 DB writer duplicate batch+timer pattern; 2 audit model song song
(`AuditEntry` vs `AuditLogModel`); 3 registry cùng `get_or_create` pattern;
5 engine DB riêng cho 1 Postgres; `_build_account_state` overlap
`RuleContextBuilder`; `BaseRule` Protocol runtime_checkable không enforce.

**Thiếu:** Typed `RuleContext`; error hierarchy gốc; `UnitOfWork`; event bus
nội bộ; `correlation_id` xuyên suốt; `OrderGateway`/`SignalSource`;
health/metrics surface; schema versioning.

**Cải thiện:** DI container thay 9 optional deps; `asyncio.TaskGroup` thay
`create_task` bare; unified `pydantic-settings` v2; gộp `rules/audit_*` →
`audit/`; consolidate `execution/` vs `orders/`.

### Review 3: Operational Completeness

**Production blockers P0:**
1. Live orchestrator vắng mặt — `engine.run()` scaffold chờ shutdown
2. Strategy gọi thẳng `order_factory.bracket()` bypass rule engine
3. Consistency rule (FTMO 50%) chưa có
4. Kill-switch CLI không flat positions
5. News blackout chưa có
6. Backtest zero slippage/commission

**P1:** Partial fill, order modify/cancel, swap/commission vào PnL, FX
conversion, indicator warmup persist, observability.

### Review 4: Multi-firm Reframing (session này)

142 FTMO mentions / 40 files chứng tỏ coupling. Mỗi prop firm khác nhau ở
cấu trúc (phases, DD method, scaling, session tz, symbol policy,
commission model) — preset YAML hiện tại biểu diễn được ~30%. **Decision:
multi-firm là organizing principle, không phải feature add-on**.

---

## Architectural Decisions

### 1. `FirmProfile` là đơn vị first-class, không chỉ "preset rule"

```python
@dataclass(frozen=True)
class FirmProfile:
    firm_id: str
    name: str
    version: str
    session: SessionConfig         # timezone, reset_time, reset_anchor
    products: dict[str, AccountProduct]
    report_template: ReportTemplate
    notification_template: dict

@dataclass(frozen=True)
class AccountProduct:
    product_id: str
    name: str
    rules: list[BaseRule]
    phases: list[AccountPhase]
    commission_overrides: CommissionProfile | None
    symbol_overrides: SymbolPolicy | None
    scaling_policy: ScalingPolicy | None   # YAML only; logic defer
```

File layout:
```
configs/firms/
├── ftmo.yaml                 # 1 product, 3 phases (Eval/Verif/Funded)
└── the5ers.yaml              # 3 products (Bootstrap, High Stakes, Hyper Growth)
```

### 2. Account binding: `firm_id + product_id + phase` tuple

Thay `preset_name: str` bằng:
```yaml
accounts:
  - account_id: the5ers-bootstrap-001
    firm_id: the5ers
    product_id: bootstrap
    phase: evaluation
    rule_overrides:
      consistency:
        warn_at: [35, 40]
        block_at: 45            # ≤ firm default (50)
```

Rule set resolve: `FirmRegistry.get(firm_id).products[product_id]` + merge
`account.rule_overrides`. Phase transition qua CLI manual:
`trading-engine accounts promote --account X --phase funded --reason "..."`.

### 3. Per-account rule overrides với safety guard

**Principle: siết chặt được, không được nới lỏng.**

```python
if account_override.block_at > firm_default.block_at:
    raise ConfigError(f"Account {id} cannot loosen {rule} block threshold")
```

Audit entry ghi `effective_threshold` (merge result), không chỉ default,
để compliance verify sau.

### 4. Consistency rule — real-time warning, không chờ payout

Context cần `daily_profits_history` inject mỗi validate call. Implementation:
- `DailyProfitHistory` service load 30-60 ngày gần nhất từ `account_snapshot`
  hypertable khi account start.
- Rolling in-memory dict `date → daily_pnl`, update khi
  `daily_snapshot_service` flush cuối ngày.
- Precompute `sum_positive_days` để rule validate O(1), không O(N).
- Rule trigger: `current_day_pnl / (current_day_pnl + sum_positive_days)`
  so với `warn_at`/`block_at` (per-account configurable).

Backtest parity: `PropFirmComplianceActor` gọi cùng rule real-time trong
backtest, record vào `firm_compliance` (renamed từ `ftmo_compliance`).

### 5. Rename `FTMO*` → `PropFirm*` — 1-shot hard cutover

**Không dual-write, không compat alias.** Maintenance window ~30 phút:
1. Stop engine
2. `alembic upgrade head` — migration UPDATE `audit_logs.event_type`
   theo mapping (`ftmo_compliance_check` → `prop_firm_compliance_check`,
   `ftmo_daily_loss_block` → `daily_loss_block`, …)
3. Deploy code mới
4. Start engine

Audit retention 180 ngày → toàn bộ record migrate. Reverse migration
provided trong `downgrade()`.

### 6. `OrderGateway` Protocol (design only, không implement)

Define interface cho futures-ready tương lai, MVP chỉ `ZmqOrderGateway`:

```python
class OrderGateway(Protocol):
    async def send_order_and_wait(self, order: Order, timeout: float) -> OrderResult
    async def send_order(self, order: Order) -> None
    async def cancel_order(self, order_id: str) -> None
    async def modify_order(self, order_id: str, **changes) -> None
```

`FirmProfile.instrument_class: Literal["FOREX_CFD", "FUTURES"]` — MVP chỉ
FOREX_CFD. Khi thêm Apex/TopStep → implement `RithmicOrderGateway` không
phá `OrderExecutionService`.

### 7. Session config generic — `midnight` vs `market_close` anchor

```yaml
session:
  timezone: "CET"           # FTMO
  reset_time: "00:00"
  reset_anchor: "midnight"
# vs
session:
  timezone: "America/New_York"
  reset_time: "17:00"
  reset_anchor: "market_close"   # Futures firms
```

MVP chỉ implement `midnight`; field có sẵn cho futures.

---

## Phase 0 Task Breakdown

| # | Task | Effort | Notes |
|---|------|--------|-------|
| P0.1 | `FirmProfile` + `AccountProduct` + `AccountPhase` frozen dataclasses | S | |
| P0.2 | `FirmRegistry` load từ `configs/firms/*.yaml` | S | |
| P0.3 | `Account` model: `firm_id` + `product_id` + `phase` + `rule_overrides` + Alembic | S | |
| P0.4 | Rename `FTMO*` → `PropFirm*` code + enum + Alembic migration audit_logs | M | Hard cutover 30 phút |
| P0.5 | Timezone-aware daily reset theo `FirmProfile.session` | S | Fix review 1 C1 generic |
| P0.6 | DD calculation variant `equity_peak` vs `balance_based` | S | |
| P0.7 | `consistency` rule real-time + `DailyProfitHistory` service + rolling cache | L | Per-account threshold |
| P0.8 | `weekly_target` rule (Monday UTC rolling) | S | The5ers Bootstrap |
| ~~P0.9~~ | ~~`min_holding_duration` + validate split~~ | ~~M~~ | **DROPPED** |
| P0.10 | CLI `accounts promote --phase` với audit entry | S | Manual transition |
| P0.11 | Migrate `ftmo.yaml` + viết `the5ers.yaml` với 3 products | L | |
| P0.12 | `OrderGateway` Protocol (interface only) + retrofit `ZmqOrderGateway` | S | Design only |
| P0.13 | `CommissionProfile` per-firm + backtest venue config | S | |
| P0.14 | E2E test: FTMO + 3 The5ers products trong 1 engine | L | |
| P0.15 | Integration test: consistency rule latency < 10ms | M | SLO check |
| P0.16 | Per-account `rule_overrides` merge + safety guard | M | |

**Tổng effort:** 5 S + 4 M + 4 L ≈ **3 sprint** (6 tuần) 1 dev FT, hoặc
4-5 tuần với 1 senior + 1 dev hỗ trợ test.

---

## Scope Decisions (confirmed session 2026-04-19)

| Decision | Choice | Rationale |
|---|---|---|
| MVP firms | FTMO + The5ers | Futures sau |
| The5ers products | **Cả 3** (Bootstrap, High Stakes, Hyper Growth) — mỗi product rule set riêng | |
| Phase transition | **Manual** qua CLI | Ops bấm nút khi nhận email verification |
| Consistency rule | **Real-time warn**, không chỉ payout-time | Phát hiện vi phạm sớm |
| Consistency threshold | **Per-account configurable** qua `rule_overrides` | Ops tune từng account |
| `min_holding_duration` | **Drop** | Không product nào trong MVP cần |
| Event type rename | **1-shot hard cutover** (Alembic migration) | Tránh compat shim phức tạp cho audit nội bộ |
| Futures support | **Design door open, không implement** | `OrderGateway` Protocol + `instrument_class` field |

---

## Open Questions (proposed defaults)

1. **Audit migration window**: default **hard cutover 30 phút maintenance**.
   Dual-write không justify cho audit nội bộ. *Cần xác nhận trước khi lên
   lịch deploy.*

2. **Backtest parity cho consistency rule**: default **YES warn real-time**
   trong `PropFirmComplianceActor`. *Xác nhận nếu muốn khác.*

3. **Consistency warn/block threshold mặc định**: đề xuất warn
   `[40, 45, 48]`, block `50` (FTMO spec). Account override có thể siết
   chặt hơn, không được nới.

4. **Order of operations**: Phase 0 nên chạy **trước** review 1 bug fixes
   (timezone, race, fire-and-forget audit) để bug fixes implement trên nền
   abstractions mới (effort giảm ~30%). *Nếu có bug blocker urgent thì
   fix point-fix trước.*

---

## References

- Review 1 (architecture): session 2026-04-18, transcript not persisted
- Review 2 (design): session 2026-04-18
- Review 3 (operational completeness): session 2026-04-19
- Review 4 (multi-firm reframing): session 2026-04-19
- `configs/firms/` layout — TBD lần implementation
- Alembic migration: `versions/xxx_rename_ftmo_to_propfirm_events.py` — TBD

## Next Steps

1. Chốt 4 open questions ở trên với stakeholder.
2. Viết story docs chi tiết cho **P0.7** và **P0.11** (L effort, XL-ish
   per-story doc theo docs policy Option C).
3. Implement P0.1 (`FirmProfile` dataclass) — foundation, unblock mọi
   story khác.
4. Re-visit Review 1 bug fixes sau khi P0.1-P0.5 xong — fix trên nền
   abstractions mới rẻ hơn.

---

## Implementation Notes (updated as stories ship)

### P0.3 — Coexistence strategy (shipped 2026-04-21)

Original plan said "+ Alembic" migration. Reality on landing:

- Alembic is not bootstrapped in this repo (`.claude/rules/database/schema.md`
  mandates it, but there are no Alembic revisions — only raw SQL under
  `infra/timescaledb/migrations/`). Bootstrapping Alembic is out of P0.3's
  "S" effort envelope and out of Epic 9's scope.
- Trading-engine is YAML-config driven for accounts; the `accounts` DB
  table is a reporting convenience, not the source of truth.
- Implementation chose **coexistence** instead of hard cutover:
  - `AccountConfig` adds nullable `firm_id + product_id + phase +
    rule_overrides` fields alongside the existing `prop_firm` / `rules_file`.
  - `validate_rules_source` enforces exactly one rule source per account.
  - `RuleAssignment` grows a new `"firm"` assignment type; `RuleAssignmentService`
    accepts an optional `FirmRegistry` and routes firm-bound accounts
    through it. Legacy `prop_firm` preset path is unchanged.
  - Raw-SQL migration `009_multi_firm_account_binding.sql` adds nullable
    columns + cross-column CHECK constraints (all-or-nothing firm binding,
    rule_overrides-only-on-firm-bound).

**Follow-up debt carried forward:**
1. Bootstrap Alembic and port migrations 005–009 into revisions. Own story,
   likely Epic 10 (infra hardening).
2. After P0.11 migrates presets → firm profiles, deprecate and drop the
   `prop_firm` field + `VALID_PROP_FIRMS` frozenset. Own story, post-Epic 9.
3. Drop the legacy `prop_firms` reference table + `accounts.prop_firm_id`
   FK after (2) ships. Own story.

### P0.4 — FTMO → PropFirm rename (shipped 2026-04-21)

Hard cutover per Open Question 1 default.

**Code symbols renamed (no alias kept):**
| Old | New |
|---|---|
| `FtmoPreset` / `load_ftmo_preset` / `DEFAULT_FTMO_PRESET_PATH` | `PropFirmPreset` / `load_prop_firm_preset` / `DEFAULT_PROP_FIRM_PRESET_PATH` |
| `FtmoComplianceActor` / `FtmoComplianceActorConfig` | `PropFirmComplianceActor` / `PropFirmComplianceActorConfig` |
| `FtmoMetricsSchema` / `FtmoComplianceMetrics` | `PropFirmMetricsSchema` / `PropFirmComplianceMetrics` |
| `FtmoSpec` (`BacktestJobConfig.ftmo`) | `PropFirmSpec` (`BacktestJobConfig.prop_firm`) |
| `BacktestRunner.attach_ftmo_compliance()` / `.ftmo_actor` / `._ftmo_actor` | `attach_prop_firm_compliance()` / `.prop_firm_actor` / `._prop_firm_actor` |
| JSON field `ftmo_compliance` in metrics schema | `prop_firm_compliance` |

**Files renamed (git mv preserves history):**
`src/backtesting/ftmo_preset.py` → `prop_firm_preset.py`;
`src/backtesting/ftmo_actor.py` → `prop_firm_actor.py`;
`src/backtesting/metrics/ftmo_metrics.py` → `prop_firm_metrics.py`;
plus four test file renames.

**audit_logs migration** (`010_rename_ftmo_audit_events.sql`): safety-net
`REPLACE(event_type, 'ftmo_', 'prop_firm_')` + same for `event_subtype`.
The production `AuditEventType` enum never held `ftmo_*` values — this
rewrite updates zero rows in steady state and is kept as insurance
against stray values written by operator scripts or in-flight feature
branches. Per `.claude/rules/database/audit.md`, this migration touches
a financial-integrity audit table and required `database-reviewer` +
`security-reviewer` sign-off before shipping.

**Compatibility preserved:**
- Preset YAMLs (`src/rules/presets/ftmo.yaml`, `the5ers.yaml`, `wmt.yaml`)
  stay under the same names and keep `"ftmo"` as the preset identifier
  string — P0.11 migrates them into `configs/firms/*.yaml`.
- `VALID_PROP_FIRMS = frozenset({"ftmo", "the5ers", "wmt"})` stays — the
  `prop_firm` field on `AccountConfig` is the legacy coexistence path
  until P0.11 retires it.
- The `prop_firms` DB reference table and `accounts.prop_firm_id` FK
  stay for backward-compat; drop is queued as a post-Epic 9 follow-up.

2192 unit tests green; 44 backtest integration tests green; unrelated
TimescaleDB-dependent integration tests require live infra.

### P0.2 — Rule overrides validation deferred to P0.16 (shipped 2026-04-21)

`FirmRegistry` stores `rule_overrides` dicts as-is (no key/value validation
against known rule types). A typo like `profit_taret` would silently be
ignored. The validation + safety guard (no loosening of block thresholds)
lands in P0.16 with the merge logic. Tracked via `TODO(P0.16)` comments in
`firm_registry.py` and `accounts/models.py`.
