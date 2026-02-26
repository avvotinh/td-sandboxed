# Story 7.5: CLI Audit Query Commands

Status: Ready for Review

## Story

As a **trader**,
I want **CLI commands to query my audit history**,
So that **I can review my trading activity, rule violations, and daily account snapshots from the command line**.

## Acceptance Criteria

1. **Given** I run `trading-engine audit trades --account ftmo-gold-001 --days 7`
   **When** the command executes
   **Then** I see a formatted table:
   ```
   Trades for ftmo-gold-001 (last 7 days)
   =====================================
   Date        Symbol   Side  Size   Entry     Exit      P&L
   2025-12-03  XAUUSD   BUY   0.10   $1850.25  $1858.50  +$82.50
   2025-12-03  XAUUSD   SELL  0.10   $1858.00  $1852.00  -$60.00
   ...
   Total: 15 trades | Net P&L: +$450.00
   ```

2. **Given** I run `trading-engine audit violations --account ftmo-gold-001`
   **When** the command executes
   **Then** I see:
   ```
   Rule Violations for ftmo-gold-001
   =================================
   Date        Rule                 Value   Limit   Action
   2025-12-03  daily_loss_limit     4.8%    5.0%    BLOCKED
   2025-12-02  max_position_size    1.2     1.0     BLOCKED
   ...
   Total: 3 violations (last 30 days)
   ```

3. **Given** I run `trading-engine audit daily --account ftmo-gold-001`
   **When** the command executes
   **Then** I see daily snapshot summary:
   ```
   Daily Snapshots for ftmo-gold-001
   ==================================
   Date        Open       Close      P&L      P&L%    DD%     Trades
   2025-12-03  $100000    $99350    -$650    -0.65%   3.07%   8
   2025-12-02  $100200    $100000   -$200    -0.20%   2.44%   5
   ...
   Trading Days: 6 | Best Day: +$450.00 | Worst Day: -$650.00
   ```

4. **Given** I run any audit command with `--json`
   **When** the command executes
   **Then** I receive structured JSON output with all fields (financial values as strings for precision)

5. **Given** I run any audit command with `--export csv`
   **When** the command executes
   **Then** a CSV file is written to the current directory with appropriate filename and I see confirmation

6. **Given** DATABASE_URL is not set
   **When** I run any audit command
   **Then** I see a clear error: "Database connection required. Set DATABASE_URL environment variable."

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 1 (Audit CLI subcommand group) → Task 2 (Query helpers) → Task 3 (trades command) → Task 4 (violations command) → Task 5 (daily command) → Task 6 (Export formats) → Task 7 (Tests)
```

- [x] Task 1: Create audit CLI subcommand group (AC: #1-3)
  - [x] 1.1: Create `src/cli/audit.py` with `audit_app = typer.Typer(name="audit", help="Query audit history and compliance data from TimescaleDB")`
  - [x] 1.2: Register in `src/cli/main.py`: `app.add_typer(audit_app, name="audit")` following existing `accounts_app` and `config_app` pattern
  - [x] 1.3: Add `audit_app` to `src/cli/__init__.py` exports (follow `config_app` pattern)
  - [x] 1.4: Create shared `_get_db_session_factory()` helper in `src/cli/audit.py` that creates an `async_sessionmaker` from `DATABASE_URL` env var (reuse pattern from `create_db_session_factory()` in `main.py`), returns `None` with clear error if DATABASE_URL not set

- [x] Task 2: Create audit query helper functions (AC: #1-3)
  - [x] 2.1: Create `_query_trades()` async function:
    - Parameters: `session: AsyncSession`, `account_id: str`, `since: datetime`, `until: datetime | None`, `symbol: str | None`, `limit: int`
    - Query: `SELECT * FROM trades WHERE account_id = :account_id AND entry_time >= :since [AND entry_time < :until] [AND symbol = :symbol] ORDER BY entry_time DESC LIMIT :limit`
    - Use SQLAlchemy `select(TradeRecord)` ORM pattern
    - Return: `list[TradeRecord]`
  - [x] 2.2: Create `_query_violations()` async function:
    - Parameters: `session: AsyncSession`, `account_id: str`, `since: datetime`, `rule_type: str | None`, `limit: int`
    - Query: `SELECT * FROM rule_violations WHERE account_id = :account_id AND timestamp >= :since [AND rule_type = :rule_type] ORDER BY timestamp DESC LIMIT :limit`
    - Use SQLAlchemy `select(RuleViolationModel)` ORM pattern
    - Return: `list[RuleViolationModel]`
  - [x] 2.3: Create `_query_snapshots()` async function:
    - Parameters: `session: AsyncSession`, `account_id: str`, `since_date: date | None`, `until_date: date | None`, `limit: int`
    - Query: `SELECT * FROM account_snapshots WHERE account_id = :account_id [AND snapshot_date >= :since_date] [AND snapshot_date <= :until_date] ORDER BY snapshot_date DESC LIMIT :limit`
    - Use SQLAlchemy `select(AccountSnapshotModel)` ORM pattern
    - Return: `list[AccountSnapshotModel]`
  - [x] 2.4: Create `_compute_trade_summary()` helper: takes `list[TradeRecord]`, returns dict with `total_trades`, `net_pnl`, `winning`, `losing`, `win_rate`

- [x] Task 3: Implement `audit trades` command (AC: #1, #4, #5)
  - [x] 3.1: Add `trades` command to `audit_app` with options:
    - `--account/-a` (REQUIRED): Account ID
    - `--days/-d` (default: 7): Number of days to look back
    - `--symbol/-s` (optional): Filter by symbol (e.g., XAUUSD)
    - `--since` (optional): Start datetime (ISO format), overrides --days
    - `--until` (optional): End datetime (ISO format)
    - `--json` (default: False): JSON output
    - `--export` (optional): Export format ("csv")
    - `--limit/-l` (default: 100): Max entries
  - [x] 3.2: Implement table formatting with `tabulate`:
    - Columns: Date, Symbol, Side, Size, Entry, Exit, P&L, Strategy
    - Color P&L: green for positive, red for negative using `typer.style()`
    - Footer: Total trades count, net P&L, win rate
  - [x] 3.3: Handle open trades (no exit_price): show "OPEN" in Exit column, "-" for P&L

- [x] Task 4: Implement `audit violations` command (AC: #2, #4, #5)
  - [x] 4.1: Add `violations` command to `audit_app` with options:
    - `--account/-a` (REQUIRED): Account ID
    - `--days/-d` (default: 30): Number of days to look back
    - `--rule-type/-r` (optional): Filter by rule_type (e.g., "daily_loss_limit")
    - `--json` (default: False): JSON output
    - `--export` (optional): Export format ("csv")
    - `--limit/-l` (default: 100): Max entries
  - [x] 4.2: Implement table formatting:
    - Columns: Date, Rule, Severity, Value, Limit, Action, Message
    - Color severity: red for CRITICAL/FATAL, yellow for WARNING, white for INFO
    - Color action: red for "blocked", yellow for "warned"
    - Footer: Total violations, blocks count, most triggered rule
  - [x] 4.3: Handle DECIMAL precision: display `current_value` and `threshold_value` with appropriate decimal places (4 for percentages, 2 for dollar amounts)

- [x] Task 5: Implement `audit daily` command (AC: #3, #4, #5)
  - [x] 5.1: Add `daily` command to `audit_app` with options:
    - `--account/-a` (REQUIRED): Account ID
    - `--days/-d` (optional): Number of days to show (default: all)
    - `--json` (default: False): JSON output
    - `--export` (optional): Export format ("csv")
    - `--limit/-l` (default: 100): Max entries
  - [x] 5.2: Implement table formatting:
    - Columns: Date, Open, Close, High, Low, P&L, P&L%, DD%, Trades, W/L
    - Color P&L: green positive, red negative
    - Footer: Trading days count, best day P&L, worst day P&L, total net P&L
  - [x] 5.3: Calculate summary stats from snapshot data: `trading_days = COUNT WHERE trades_count > 0`

- [x] Task 6: Implement export formats (AC: #4, #5)
  - [x] 6.1: Create `_export_json()` helper: serialize records to JSON using `to_dict()` methods, financial fields as strings, write to file or stdout
  - [x] 6.2: Create `_export_csv()` helper: use Python `csv` module (stdlib), write header + rows, generate filename from command+account+date (e.g., `trades-ftmo-gold-001-2026-02-27.csv`)
  - [x] 6.3: Display export confirmation: "Exported {n} records to {filename}"

- [x] Task 7: Add unit and integration tests (AC: #1-6)
  - [x] 7.1: Unit test: `audit trades` command with mocked DB session returns formatted table
  - [x] 7.2: Unit test: `audit trades --json` returns valid JSON with all trade fields
  - [x] 7.3: Unit test: `audit violations` command with mocked violations returns formatted table
  - [x] 7.4: Unit test: `audit daily` command with mocked snapshots returns formatted table
  - [x] 7.5: Unit test: `--export csv` writes CSV file with correct headers and data
  - [x] 7.6: Unit test: Missing DATABASE_URL shows error message and exits with code 1
  - [x] 7.7: Unit test: Empty results show "No [trades|violations|snapshots] found" message
  - [x] 7.8: Unit test: DECIMAL precision preserved in JSON output (strings, not floats)
  - [x] 7.9: Unit test: `_compute_trade_summary()` calculates correct totals, win rate
  - [x] 7.10: Unit test: `_parse_time_delta()` reuse from main.py works for all formats
  - [x] 7.11: Integration test: Full CLI invocation via `CliRunner` with `audit trades --account test-001 --days 7`
  - [x] 7.12: Integration test: Full CLI invocation via `CliRunner` with `audit violations --account test-001`
  - [x] 7.13: Integration test: Full CLI invocation via `CliRunner` with `audit daily --account test-001`

## Dev Notes

### CRITICAL: Read Before Implementation

**These items MUST be completed or the feature will not work:**

1. **CLI Framework is Typer (NOT Click)**: The project uses `typer` (which is built on Click internally). All CLI patterns must use `typer.Typer()`, `@app.command()`, `Annotated[type, typer.Option()]`, NOT raw Click decorators. See `src/cli/main.py` for the canonical patterns.

2. **Existing `logs` command queries REDIS, NOT TimescaleDB**: The current `logs` command in `src/cli/main.py:607-693` queries Redis audit logs via `_query_redis_audit_logs()`. Story 7.5's `audit` commands query **TimescaleDB** tables directly. These are completely different data sources and code paths.

3. **Database Session Factory Pattern**: Use the existing `create_db_session_factory()` from `src/cli/main.py:28-69` as your pattern. It handles:
   - Reading `DATABASE_URL` from environment
   - Converting `postgresql://` to `postgresql+asyncpg://`
   - Creating `async_sessionmaker` with `expire_on_commit=False`
   - Graceful fallback if `sqlalchemy[asyncio]` not installed

4. **Async/Sync Bridge**: All DB queries are async (SQLAlchemy asyncpg). CLI commands are sync (Typer). Use the existing `_run_async(coro)` wrapper (line 82-91 in `main.py`) which calls `asyncio.run()`. **DO NOT** create a new event loop pattern.

5. **ORM Models Already Exist**: Do NOT re-create any ORM models. Use the existing ones:
   - `TradeRecord` at `src/orders/db_models.py` (has `to_dict()` method)
   - `RuleViolationModel` at `src/rules/violation_db_writer.py` (has `to_dict()` method)
   - `AccountSnapshotModel` at `src/snapshots/models.py` (has `to_dict()` method)

6. **Table Formatting**: Use `tabulate` library (already a dependency, imported in `main.py`). Use `tablefmt="simple"` to match existing `_format_audit_table()` pattern.

7. **DECIMAL Precision is Critical**: All financial values from TimescaleDB are `Decimal` type. When serializing to JSON, convert via `str()` - NEVER `float()`. The existing `to_dict()` methods handle this. For table display, format with appropriate decimal places (`:.2f` for dollars, `:.4f` for percentages).

8. **Retention Window Awareness**: Raw data retention policies:
   - `trades`: No retention - keeps all data
   - `audit_logs`: 90 days raw, 365 days continuous aggregate (`audit_daily_summary`)
   - `rule_violations`: 90 days raw, 365 days continuous aggregate (`violation_daily_summary`)
   - `account_snapshots`: No retention - keeps all data

   CLI commands should work within these windows. If a user queries beyond 90 days for violations, they'll get empty results for raw data. Consider querying continuous aggregates for longer time ranges (future enhancement, not required for this story).

9. **Color Output via STATUS_COLORS**: Use colors from `src/cli/constants.py`:
   - Green (`STATUS_COLORS["connected"]`): Positive P&L, successful operations
   - Red (`STATUS_COLORS["error"]`): Negative P&L, violations, errors
   - Yellow (`STATUS_COLORS["paused"]`): Warnings
   - Cyan (`STATUS_COLORS["starting"]`): Headers, info

10. **CSV Export Uses stdlib `csv` Module**: Do NOT add `pandas` or any new dependency for CSV export. Use Python's built-in `csv.writer()` or `csv.DictWriter()`. Write to current working directory with generated filename.

11. **NO New Dependencies**: This story must NOT add any new Python packages. Everything needed is already installed:
    - `typer` - CLI framework
    - `tabulate` - Table formatting
    - `sqlalchemy[asyncio]` + `asyncpg` - Database access
    - `csv` (stdlib) - CSV export
    - `json` (stdlib) - JSON output

---

### Quick Reference: What to Create/Modify

| Component | What to Do | Location |
|-----------|------------|----------|
| **audit.py** | Create audit subcommand group with trades, violations, daily commands | `src/cli/audit.py` (NEW) |
| **main.py** | Register `audit_app` subcommand group | `src/cli/main.py` (MODIFY - add import + `app.add_typer()`) |
| **__init__.py** | Add `audit_app` to exports | `src/cli/__init__.py` (MODIFY) |
| **Unit Tests** | CLI command tests with mocked DB sessions | `tests/unit/test_cli_audit.py` (NEW) |
| **Integration Tests** | Full CLI invocation tests | `tests/integration/test_cli_audit.py` (NEW) |

---

### Architecture Compliance

**Service:** `services/trading-engine/` (Python 3.11+)
**Database:** TimescaleDB (PostgreSQL 16+)
**ORM:** SQLAlchemy 2.0+ with async support (asyncpg)
**CLI Framework:** Typer with subcommand groups

**CRITICAL CONSTRAINTS from Architecture:**

Tables being queried (from [Source: infra/timescaledb/init.sql]):

```sql
-- trades (regular table)
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(18, 8) NOT NULL,
    entry_price DECIMAL(18, 5) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_price DECIMAL(18, 5),
    exit_time TIMESTAMPTZ,
    pnl_dollars DECIMAL(18, 2),
    pnl_percent DECIMAL(8, 4),
    status VARCHAR(20) DEFAULT 'open',
    ...
);
CREATE INDEX idx_trades_account_time ON trades (account_id, entry_time DESC);

-- rule_violations (hypertable, 90-day retention)
CREATE TABLE rule_violations (
    id UUID DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    rule_type VARCHAR(50) NOT NULL,
    rule_name VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    action_taken VARCHAR(50) NOT NULL,
    message TEXT,
    ...
);
CREATE INDEX idx_violations_account ON rule_violations (account_id, timestamp DESC);

-- account_snapshots (regular table, no retention)
CREATE TABLE account_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    snapshot_date DATE NOT NULL,
    opening_balance DECIMAL(18, 2),
    closing_balance DECIMAL(18, 2),
    daily_pnl DECIMAL(18, 2),
    daily_pnl_percent DECIMAL(8, 4),
    drawdown_percent DECIMAL(8, 4),
    trades_count INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    ...
    UNIQUE(account_id, snapshot_date)
);
CREATE INDEX idx_snapshots_account_date ON account_snapshots (account_id, snapshot_date DESC);
```

**Continuous Aggregates Available** (from [Source: infra/timescaledb/migrations/007, 008]):
- `audit_daily_summary` (day, account_id, event_type, event_count, warning_count, error_count)
- `violation_daily_summary` (day, account_id, rule_type, violation_count, critical_count, warning_count, blocked_count, peak_value, min_threshold)

**Communication Patterns:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Outbound | PostgreSQL | 5432 | SELECT queries on trades, rule_violations, account_snapshots |

---

### Context from Previous Stories

**From Story 7.1 (Trade Execution Audit Logging) - Key Patterns:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| TradeRecord ORM | Full column mapping with `from_trade()` factory, `to_dict()` | `src/orders/db_models.py:27-129` |
| TradeDBWriter.session() | AsyncSession context manager for CLI queries | `src/orders/trade_db_writer.py` |
| Financial precision | `Decimal(str(value))` everywhere, never float | All DB writers |

**From Story 7.2 (Comprehensive Audit Log Table) - Integration:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| AuditDBWriter | Batch writes to audit_logs hypertable | `src/rules/audit_db_writer.py` |
| Continuous aggregate | `audit_daily_summary` materialized view | Migration 007 |

**From Story 7.3 (Rule Violation Tracking) - DB Writer:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| RuleViolationModel | Full 17-column ORM mapping with `to_dict()` | `src/rules/violation_db_writer.py` |
| ViolationDBWriter | Batch buffer with timer flush | `src/rules/violation_db_writer.py` |
| Continuous aggregate | `violation_daily_summary` materialized view | Migration 008 |

**From Story 7.4 (Daily Account Snapshots) - Current Story Context:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| AccountSnapshotModel | 17-column ORM with `from_snapshot_data()`, `to_dict()` | `src/snapshots/models.py` |
| SnapshotDBWriter | Direct write (no batch) with upsert | `src/snapshots/snapshot_db_writer.py` |
| DailySnapshotService | Midnight UTC scheduler with per-account error isolation | `src/snapshots/daily_snapshot_service.py` |

**Existing CLI Patterns (FOLLOW EXACTLY):**

| Pattern | Example | Location |
|---------|---------|----------|
| Typer app creation | `app = typer.Typer(name="trading-engine", ...)` | `src/cli/main.py:71-75` |
| Subcommand registration | `app.add_typer(accounts_app, name="accounts")` | `src/cli/main.py:78-79` |
| Async bridge | `_run_async(coro)` → `asyncio.run(coro)` | `src/cli/main.py:82-91` |
| Time parsing | `_parse_time_delta("7d")` → `timedelta(days=7)` | `src/cli/main.py:491-514` |
| Table formatting | `tabulate(rows, headers, tablefmt="simple")` | `src/cli/main.py:572-604` |
| JSON output | `json.dumps(data, indent=2, default=str)` | `src/cli/main.py:676-677` |
| Error handling | `typer.style(msg, fg=STATUS_COLORS["error"])` + `raise typer.Exit(1)` | Throughout `main.py` |
| DB session factory | `create_db_session_factory()` → `async_sessionmaker` | `src/cli/main.py:28-69` |
| Option pattern | `Annotated[str, typer.Option("--account", "-a", help="...")]` | `src/cli/main.py:609-623` |

**Testing Patterns (FOLLOW EXACTLY):**

| Pattern | Example | Location |
|---------|---------|----------|
| CliRunner | `from typer.testing import CliRunner; runner = CliRunner()` | `tests/unit/test_cli.py` |
| CLI invocation | `result = runner.invoke(app, ["audit", "trades", "--account", "test-001"])` | Test files |
| AsyncMock | `from unittest.mock import AsyncMock, MagicMock, patch` | All test files |
| DB session mock | Mock `async_sessionmaker` → `AsyncSession` → `execute()` → `scalars()` | Test pattern |
| Assert exit code | `assert result.exit_code == 0` | Test pattern |
| Assert output | `assert "Trades for" in result.output` | Test pattern |

---

### Git Intelligence (Recent Commits)

Last 5 commits are all Epic 7 implementations:
```
a1a1694 Implement spec 7 story 7.4  (daily account snapshots)
fe5004b Implement spec 7 story 7.3  (rule violation tracking)
67cf9cc Implement spec 7 story 7.2  (comprehensive audit log table)
13fca35 Implement spec 7 story 7.1  (trade execution audit logging)
9ea9da7 Implement spec 6 story 6.6  (resume trading command)
```

**Files created/modified in Epic 7 (stories 7.1-7.4):**
- `src/audit/` - AuditService, AuditDBWriter
- `src/orders/db_models.py` - TradeRecord ORM model
- `src/orders/trade_db_writer.py` - Trade persistence with session() context manager
- `src/rules/violation_db_writer.py` - Violation persistence
- `src/rules/violation_service.py` - Violation service facade
- `src/snapshots/` - AccountSnapshotModel, SnapshotDBWriter, DailySnapshotService
- `src/engine.py` - Service lifecycle integration
- `infra/timescaledb/migrations/006-008` - Indexes, retention, compression, aggregates

---

### Latest Technical Documentation (Context7 Research)

**SQLAlchemy 2.1 Async Query Patterns (from Context7 /websites/sqlalchemy_en_21):**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

engine = create_async_engine("postgresql+asyncpg://...", echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async with async_session() as session:
    # Standard buffered query (good for <1000 rows)
    stmt = select(TradeRecord).where(
        TradeRecord.account_id == account_id,
        TradeRecord.entry_time >= since
    ).order_by(TradeRecord.entry_time.desc()).limit(limit)
    result = await session.scalars(stmt)
    records = result.all()

    # For large result sets, use streaming:
    result = await session.stream(stmt)
    async for row in result.scalars():
        process(row)
```

**Key Points:**
- Use `session.scalars(stmt)` for buffered results (appropriate for CLI with --limit)
- Use `session.stream(stmt)` for server-side cursors on large result sets
- `expire_on_commit=False` prevents lazy-load issues in async context
- Use `select()` 2.0-style queries, NOT legacy `session.query()`

**TimescaleDB time_bucket() for Future Aggregated Views (from Context7 /timescale/docs):**

```sql
-- Can be used for aggregated audit queries (future enhancement)
SELECT
    time_bucket('1 day', timestamp) AS bucket,
    account_id,
    COUNT(*) as event_count
FROM audit_logs
GROUP BY bucket, account_id;
```

**Typer CLI Patterns (from Context7 /pallets/click - Typer is built on Click):**

```python
import typer
from typing_extensions import Annotated

audit_app = typer.Typer(name="audit", help="Query audit history")

@audit_app.command()
def trades(
    account: Annotated[str, typer.Option("--account", "-a", help="Account ID")],
    days: Annotated[int, typer.Option("--days", "-d", help="Days to look back")] = 7,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
):
    """Query trade history for an account."""
    ...
```

---

### Implementation Guide

**Step 1: Create `src/cli/audit.py`**

```python
"""Audit CLI commands - Query audit history from TimescaleDB."""

from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from tabulate import tabulate
from typing_extensions import Annotated

from .constants import STATUS_COLORS

# Lazy imports for DB models (only when DATABASE_URL is set)
# from ..orders.db_models import TradeRecord
# from ..rules.violation_db_writer import RuleViolationModel
# from ..snapshots.models import AccountSnapshotModel

audit_app = typer.Typer(
    name="audit",
    help="Query audit history and compliance data from TimescaleDB",
    add_completion=False,
)
```

**Step 2: Register in `src/cli/main.py`**

```python
# Add import
from .audit import audit_app

# Add after existing app.add_typer lines
app.add_typer(audit_app, name="audit")
```

**Step 3: Implement DB session helper in audit.py**

```python
def _get_db_session_factory():
    """Create async DB session factory from DATABASE_URL."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        typer.echo(typer.style(
            "Database connection required. Set DATABASE_URL environment variable.",
            fg=STATUS_COLORS["error"]
        ))
        raise typer.Exit(1)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

**Step 4: Implement async query functions**

Each query function follows the same pattern:
- Accept `AsyncSession` + filter parameters
- Build `select()` statement with `.where()` clauses
- Execute with `await session.scalars(stmt)`
- Return `.all()` list

**Step 5: Implement CLI commands**

Each command follows the same pattern:
1. Get session factory (exits on failure)
2. Parse time range from --days or --since
3. Run async query via `_run_async()`
4. Format output (table, JSON, or CSV)
5. Display results with summary footer

---

### Project Structure Notes

- All new code goes in `services/trading-engine/src/cli/audit.py` (single new file)
- Only 2 existing files modified: `main.py` (2 lines), `__init__.py` (1 line)
- Tests in `services/trading-engine/tests/unit/test_cli_audit.py` and `tests/integration/test_cli_audit.py`
- No new directories needed - `src/cli/` already exists

### References

- [Source: docs/epics.md#Epic-7-Story-7.5] - Acceptance criteria and user story
- [Source: docs/architecture.md#Monorepo-Structure] - Service layout and CLI location
- [Source: infra/timescaledb/init.sql#trades] - Trade table schema (lines 136-165)
- [Source: infra/timescaledb/init.sql#rule_violations] - Violations table schema (lines 176-194)
- [Source: infra/timescaledb/init.sql#account_snapshots] - Snapshots table schema (lines 60-82)
- [Source: infra/timescaledb/migrations/007_audit_retention_and_aggregate.sql] - Audit retention and continuous aggregate
- [Source: infra/timescaledb/migrations/008_violations_retention_and_aggregate.sql] - Violations retention and continuous aggregate
- [Source: services/trading-engine/src/cli/main.py] - Existing CLI patterns, _run_async, _parse_time_delta
- [Source: services/trading-engine/src/orders/db_models.py] - TradeRecord ORM model
- [Source: services/trading-engine/src/rules/violation_db_writer.py] - RuleViolationModel ORM
- [Source: services/trading-engine/src/snapshots/models.py] - AccountSnapshotModel ORM
- [Source: services/trading-engine/src/snapshots/snapshot_db_writer.py] - SnapshotDBWriter session pattern
- [Source: docs/sprint-artifacts/7-4-daily-account-snapshots.md] - Previous story patterns and dev notes

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

Claude Opus 4.6

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created
- Context7 MCP research completed for SQLAlchemy 2.1, TimescaleDB, and Click/Typer latest documentation
- All 4 previous Epic 7 stories analyzed for implementation patterns
- Git history analyzed: 26 files changed across stories 7.1-7.4 establishing clear conventions
- Implemented all 3 audit CLI commands (trades, violations, daily) with table, JSON, and CSV output formats
- All 26 tests pass (16 unit + 10 integration), 0 regressions in full 1683-test unit suite
- Ruff linting passes clean on all new/modified files
- Used `_run_async(asyncio.run())` pattern matching existing CLI, SQLAlchemy 2.0 `select()` ORM queries
- DECIMAL precision preserved: `str()` serialization in JSON, `:.2f`/`:.4f` formatting in tables
- Note on Task 7.10: Audit commands use `--days` (int) + `--since` (ISO datetime) instead of `_parse_time_delta()` string format. This is a cleaner API for the audit use case; the "7d"/"24h" format is specific to the Redis `logs` command.

### File List

| Action | File |
|--------|------|
| NEW | `services/trading-engine/src/cli/audit.py` |
| MODIFIED | `services/trading-engine/src/cli/main.py` |
| MODIFIED | `services/trading-engine/src/cli/__init__.py` |
| MODIFIED | `services/trading-engine/src/rules/violation_db_writer.py` |
| NEW | `services/trading-engine/tests/unit/test_cli_audit.py` |
| NEW | `services/trading-engine/tests/integration/test_cli_audit.py` |
| MODIFIED | `docs/sprint-artifacts/sprint-status.yaml` |

### Change Log

- **2026-02-27**: Implemented Story 7.5 - CLI Audit Query Commands. Created `audit` subcommand group with `trades`, `violations`, and `daily` commands. All 3 commands support table output (with colored P&L and severity), `--json` output (DECIMAL as strings), and `--export csv` to file. Registered `audit_app` in main CLI. Added 16 unit tests and 10 integration tests covering all ACs.
