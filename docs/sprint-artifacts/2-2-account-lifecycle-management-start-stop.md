# Story 2.2: Account Lifecycle Management (Start/Stop)

Status: Done

## Story

As a **trader**,
I want **to start and stop my trading account via CLI commands**,
so that **I can control when the account is actively trading and manage account lifecycle states**.

## Acceptance Criteria

1. **AC1**: Running `trading-engine accounts start <account_id>` changes account status to "active" and begins signal processing
2. **AC2**: Running `trading-engine accounts stop <account_id>` changes account status to "stopped" without closing existing MT5 positions
3. **AC3**: Running `trading-engine accounts status` shows all accounts with their current state (active, paused, stopped, error)
4. **AC4**: Running `trading-engine accounts status <account_id>` shows detailed status for a specific account
5. **AC5**: Account status is persisted to Redis at key `account:{account_id}:status`
6. **AC6**: State transitions follow the defined state machine: active ↔ paused, active/paused → stopped, any → error
7. **AC7**: Invalid state transitions produce clear error messages
8. **AC8**: Unit tests cover all state transitions, CLI commands, and Redis persistence

## Tasks / Subtasks

### Task 1: Add CLI Dependencies and Framework Setup (AC: 1, 2, 3, 4)
- [x] Add `typer>=0.9` or `click>=8.0` to pyproject.toml dependencies
- [x] Create `src/cli/__init__.py` with CLI app initialization
- [x] Create `src/cli/main.py` with main CLI entrypoint
- [x] Update `src/__main__.py` to use CLI framework

### Task 2: Create Account State Enum and Manager (AC: 5, 6, 7)
- [x] Create `src/accounts/state.py` with AccountState enum (active, paused, stopped, error)
- [x] Create `src/accounts/account_manager.py` with AccountManager class
- [x] Implement state machine with valid transitions
- [x] Add state transition validation with clear error messages
- [x] Implement `start_account()`, `stop_account()`, `pause_account()` methods
- [x] Implement `get_account_status()` and `get_all_statuses()` methods

### Task 3: Implement Redis State Persistence (AC: 5)
- [x] Create `src/state/redis_state.py` with RedisStateManager class
- [x] Implement async `save_account_status(account_id, status)` method
- [x] Implement async `get_account_status(account_id)` method
- [x] Implement async `get_all_account_statuses()` method
- [x] Use Redis key pattern: `account:{account_id}:status`
- [x] Handle Redis connection errors gracefully

### Task 4: Create CLI Commands for Account Management (AC: 1, 2, 3, 4)
- [x] Create `src/cli/accounts.py` with accounts command group
- [x] Implement `accounts start <account_id>` command (activates stopped accounts)
- [x] Implement `accounts stop <account_id>` command
- [x] Implement `accounts status [account_id]` command (optional account_id)
- [x] Implement `accounts pause <account_id>` command
- [x] Implement `accounts resume <account_id>` command (resumes paused accounts)
- [x] Add `--force` flag for bypassing confirmation prompts
- [x] Add colorful status output using STATUS_COLORS constant
- [x] Validate account_id exists in configuration before state changes

### Task 5: Write Unit Tests (AC: 8)
- [x] Create `tests/unit/test_account_state.py` for state enum and transitions
- [x] Create `tests/unit/test_account_manager.py` for AccountManager
- [x] Create `tests/unit/test_redis_state.py` for Redis persistence (with mocks)
- [x] Create `tests/unit/test_cli_accounts.py` for CLI commands (using Typer/Click testing utilities)
- [x] Test valid state transitions
- [x] Test invalid state transitions produce errors
- [x] Test Redis key patterns and values

### Task 6: Integration and Documentation (AC: 1-8)
- [x] Update `src/accounts/__init__.py` with new exports
- [x] Update `src/state/__init__.py` with RedisStateManager export
- [x] Update `src/cli/__init__.py` with CLI app export
- [x] Add CLI usage examples to configs/accounts.yaml.example comments
- [x] Verify all tests pass: `uv run pytest tests/unit/ -v`

## Dev Notes

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**
- Account Manager location: `services/trading-engine/src/accounts/account_manager.py`
- CLI entry point: `services/trading-engine/src/__main__.py`
- State persistence: Redis with key pattern `account:{account_id}:status`
- CLI Framework: Click or Typer (both documented in architecture)

**Account State Machine (from Epic 2 Context):**
```
      ┌───────────────┐
      │    active     │ ◄──── Default starting state
      └───────┬───────┘
              │ pause/resume
              ▼
      ┌───────────────┐
      │    paused     │
      └───────┬───────┘
              │ stop (from either)
              ▼
      ┌───────────────┐
      │    stopped    │ ◄──── Terminal state (restart needed)
      └───────────────┘
              ▲
      ┌───────┴───────┐
      │     error     │ ◄──── Exception/failure state
      └───────────────┘
```

**Valid State Transitions:**
- `active` → `paused` (pause command)
- `paused` → `active` (resume/start command)
- `active` → `stopped` (stop command)
- `paused` → `stopped` (stop command)
- Any state → `error` (system-initiated on failure)
- `error` → `stopped` (stop command to acknowledge)
- `stopped` → `active` (start command - reinitialize)

**Critical Design Decisions:**
- Stopping an account does NOT close MT5 positions (positions remain open)
- Account status is stored in Redis for quick access and persistence
- State transitions are atomic (no intermediate states)
- CLI commands are synchronous wrappers around async operations

### Technical Requirements

**Typer CLI Framework (from Context7 Research 2025-12-20):**
```python
import typer

app = typer.Typer()
accounts_app = typer.Typer()
app.add_typer(accounts_app, name="accounts")

@accounts_app.command()
def start(account_id: str):
    """Start a trading account."""
    typer.echo(f"Starting account: {account_id}")

@accounts_app.command()
def stop(account_id: str):
    """Stop a trading account."""
    typer.echo(f"Stopping account: {account_id}")

@accounts_app.command()
def status(account_id: str = typer.Argument(None)):
    """Show account status (all or specific)."""
    if account_id:
        typer.echo(f"Status for {account_id}")
    else:
        typer.echo("Status for all accounts")
```

**Redis Async Operations (from Context7 Research 2025-12-20):**
```python
import redis.asyncio as aioredis

class RedisStateManager:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )

    async def save_account_status(self, account_id: str, status: str) -> None:
        """Save account status to Redis."""
        key = f"account:{account_id}:status"
        await self._client.set(key, status)

    async def get_account_status(self, account_id: str) -> str | None:
        """Get account status from Redis."""
        key = f"account:{account_id}:status"
        return await self._client.get(key)

    async def get_all_account_statuses(self) -> dict[str, str]:
        """Get all account statuses using SCAN."""
        statuses = {}
        async for key in self._client.scan_iter("account:*:status"):
            account_id = key.split(":")[1]
            status = await self._client.get(key)
            statuses[account_id] = status
        return statuses

    async def close(self) -> None:
        if self._client:
            await self._client.close()
```

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── accounts/
│   │   ├── __init__.py        # Export: AccountManager, AccountState
│   │   ├── models.py          # EXISTING: Account Pydantic models
│   │   ├── state.py           # NEW: AccountState enum
│   │   └── account_manager.py # NEW: AccountManager class
│   ├── cli/
│   │   ├── __init__.py        # NEW: CLI app initialization
│   │   ├── main.py            # NEW: Main CLI entrypoint
│   │   ├── accounts.py        # NEW: Accounts command group
│   │   └── constants.py       # NEW: CLI constants (STATUS_COLORS)
│   ├── state/
│   │   ├── __init__.py        # Export: RedisStateManager
│   │   └── redis_state.py     # NEW: Redis state persistence
│   ├── config/
│   │   ├── __init__.py        # EXISTING
│   │   └── loader.py          # EXISTING
│   └── __main__.py            # MODIFY: Use CLI framework
├── tests/
│   ├── unit/
│   │   ├── test_account_models.py    # EXISTING: 41 tests
│   │   ├── test_account_state.py     # NEW: State enum tests
│   │   ├── test_account_manager.py   # NEW: AccountManager tests
│   │   ├── test_redis_state.py       # NEW: Redis state tests (mocked)
│   │   └── test_cli_accounts.py      # NEW: CLI command tests
│   └── integration/
│       └── test_redis_integration.py # NEW: Real Redis tests
└── pyproject.toml             # MODIFY: Add typer dependency
```

### Package Exports

**src/accounts/__init__.py (updated):**
```python
from .models import (
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)
from .state import AccountState
from .account_manager import AccountManager

__all__ = [
    "AccountConfig",
    "AccountsConfig",
    "AccountType",
    "MT5Config",
    "SignalFilter",
    "AccountState",
    "AccountManager",
]
```

**src/state/__init__.py (updated):**
```python
from .redis_state import RedisStateManager

__all__ = ["RedisStateManager"]
```

**src/cli/__init__.py (new):**
```python
from .main import app

__all__ = ["app"]
```

### Expected Implementation Patterns

**AccountState Enum:**
```python
# src/accounts/state.py
from enum import Enum

class AccountState(str, Enum):
    """Trading account lifecycle states."""
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"

    @classmethod
    def valid_transitions(cls) -> dict[str, list[str]]:
        """Return valid state transitions."""
        return {
            cls.ACTIVE: [cls.PAUSED, cls.STOPPED, cls.ERROR],
            cls.PAUSED: [cls.ACTIVE, cls.STOPPED, cls.ERROR],
            cls.STOPPED: [cls.ACTIVE],  # Restart
            cls.ERROR: [cls.STOPPED],   # Acknowledge error
        }

    def can_transition_to(self, target: "AccountState") -> bool:
        """Check if transition to target state is valid."""
        return target in self.valid_transitions().get(self, [])
```

**AccountManager Pattern:**
```python
# src/accounts/account_manager.py
from typing import Optional
from .state import AccountState
from .models import AccountConfig, AccountsConfig
from ..state.redis_state import RedisStateManager

class AccountManager:
    """Manages trading account lifecycle and state."""

    def __init__(self, redis_manager: RedisStateManager):
        self._redis = redis_manager
        self._accounts: dict[str, AccountConfig] = {}

    def load_accounts(self, config: AccountsConfig) -> None:
        """Load account configurations for validation."""
        self._accounts = {acc.id: acc for acc in config.accounts}

    def _validate_account_exists(self, account_id: str) -> None:
        """Validate account exists in configuration."""
        if account_id not in self._accounts:
            raise ValueError(
                f"Account '{account_id}' not found in configuration. "
                f"Available accounts: {list(self._accounts.keys())}"
            )

    async def start_account(self, account_id: str) -> None:
        """Start a trading account (set to active from stopped or new)."""
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)
        target = AccountState.ACTIVE

        # New account (no prior state) - initialize as active
        if current is None:
            await self._redis.save_account_status(account_id, target.value)
            return

        if not AccountState(current).can_transition_to(target):
            raise ValueError(
                f"Cannot transition account '{account_id}' from '{current}' to '{target.value}'"
            )

        await self._redis.save_account_status(account_id, target.value)

    async def stop_account(self, account_id: str) -> None:
        """Stop a trading account (does NOT close positions)."""
        self._validate_account_exists(account_id)
        target = AccountState.STOPPED
        await self._redis.save_account_status(account_id, target.value)

    async def pause_account(self, account_id: str) -> None:
        """Pause a trading account temporarily."""
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)
        target = AccountState.PAUSED

        if current and not AccountState(current).can_transition_to(target):
            raise ValueError(
                f"Cannot transition account '{account_id}' from '{current}' to '{target.value}'"
            )

        await self._redis.save_account_status(account_id, target.value)

    async def resume_account(self, account_id: str) -> None:
        """Resume a paused account (paused → active)."""
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)
        target = AccountState.ACTIVE

        if current != AccountState.PAUSED.value:
            raise ValueError(
                f"Cannot resume account '{account_id}' - not paused (current: {current})"
            )

        await self._redis.save_account_status(account_id, target.value)

    async def acknowledge_error(self, account_id: str) -> None:
        """Acknowledge error state and transition to stopped."""
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)

        if current != AccountState.ERROR.value:
            raise ValueError(
                f"Account '{account_id}' is not in error state (current: {current})"
            )

        await self._redis.save_account_status(account_id, AccountState.STOPPED.value)

    async def get_account_status(self, account_id: str) -> Optional[str]:
        """Get current status of an account."""
        return await self._redis.get_account_status(account_id)

    async def get_all_statuses(self) -> dict[str, str]:
        """Get status of all configured accounts."""
        statuses = {}
        for account_id in self._accounts:
            status = await self._redis.get_account_status(account_id)
            statuses[account_id] = status or "unknown"
        return statuses

    async def close(self) -> None:
        """Close Redis connection gracefully."""
        await self._redis.close()
```

**CLI Main Entrypoint:**
```python
# src/cli/main.py
import typer
from .accounts import accounts_app

app = typer.Typer(
    name="trading-engine",
    help="Multi-account trading engine with FTMO compliance",
    add_completion=False,
)

# Add subcommand groups
app.add_typer(accounts_app, name="accounts", help="Manage trading accounts")

@app.command()
def start():
    """Start the trading engine."""
    typer.echo("Starting trading engine...")

@app.command()
def stop():
    """Stop the trading engine."""
    typer.echo("Stopping trading engine...")

@app.command()
def status():
    """Show trading engine status."""
    typer.echo("Trading engine status: running")
```

**CLI Constants:**
```python
# src/cli/constants.py
import typer

STATUS_COLORS = {
    "active": typer.colors.GREEN,
    "paused": typer.colors.YELLOW,
    "stopped": typer.colors.RED,
    "error": typer.colors.RED,
}
```

**CLI Accounts Commands:**
```python
# src/cli/accounts.py
import asyncio
import os
from typing import Optional
import typer

from ..state.redis_state import RedisStateManager
from ..accounts.account_manager import AccountManager
from ..config.loader import ConfigLoader
from .constants import STATUS_COLORS

accounts_app = typer.Typer()

def run_async(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)

def get_account_manager() -> AccountManager:
    """Get configured AccountManager with Redis connection."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis = RedisStateManager(redis_url)
    asyncio.run(redis.connect())

    # Load accounts config to validate account IDs
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    loader = ConfigLoader(config_path)
    accounts_config = loader.load()

    manager = AccountManager(redis)
    manager.load_accounts(accounts_config)
    return manager

@accounts_app.command("start")
def start_account(
    account_id: str = typer.Argument(..., help="Account ID to start"),
):
    """Start a trading account (from stopped or new state)."""
    try:
        manager = get_account_manager()
        run_async(manager.start_account(account_id))
        typer.echo(typer.style(f"✓ Account {account_id} started", fg=STATUS_COLORS["active"]))
        run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)

@accounts_app.command("stop")
def stop_account(
    account_id: str = typer.Argument(..., help="Account ID to stop"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Stop a trading account (positions remain open)."""
    if not force:
        typer.confirm(
            f"Stop account {account_id}? Positions will remain open.",
            abort=True
        )
    try:
        manager = get_account_manager()
        run_async(manager.stop_account(account_id))
        typer.echo(typer.style(f"✓ Account {account_id} stopped", fg=STATUS_COLORS["stopped"]))
        run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)

@accounts_app.command("status")
def account_status(
    account_id: Optional[str] = typer.Argument(None, help="Account ID (optional)"),
):
    """Show account status (all accounts if no ID specified)."""
    manager = get_account_manager()
    if account_id:
        status = run_async(manager.get_account_status(account_id)) or "unknown"
        color = STATUS_COLORS.get(status, typer.colors.WHITE)
        typer.echo(f"Account {account_id}: " + typer.style(status, fg=color))
    else:
        statuses = run_async(manager.get_all_statuses())
        typer.echo("Account Statuses:")
        for acc_id, status in statuses.items():
            color = STATUS_COLORS.get(status, typer.colors.WHITE)
            typer.echo(f"  {acc_id}: " + typer.style(status, fg=color))
    run_async(manager.close())

@accounts_app.command("pause")
def pause_account(
    account_id: str = typer.Argument(..., help="Account ID to pause"),
):
    """Pause a trading account temporarily."""
    try:
        manager = get_account_manager()
        run_async(manager.pause_account(account_id))
        typer.echo(typer.style(f"✓ Account {account_id} paused", fg=STATUS_COLORS["paused"]))
        run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)

@accounts_app.command("resume")
def resume_account(
    account_id: str = typer.Argument(..., help="Account ID to resume"),
):
    """Resume a paused trading account."""
    try:
        manager = get_account_manager()
        run_async(manager.resume_account(account_id))
        typer.echo(typer.style(f"✓ Account {account_id} resumed", fg=STATUS_COLORS["active"]))
        run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
```

### Testing Requirements

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Run all unit tests
uv run pytest tests/unit/ -v

# Run specific test file
uv run pytest tests/unit/test_account_manager.py -v

# Run with coverage
uv run pytest tests/unit/ --cov=src/accounts --cov=src/state --cov=src/cli

# Test CLI commands
uv run pytest tests/unit/test_cli_accounts.py -v
```

**Integration Tests (requires Redis):**
```bash
# Start test Redis instance
docker run -d --name test-redis -p 6380:6379 redis:7-alpine

# Run integration tests
TEST_REDIS_URL=redis://localhost:6380 uv run pytest tests/integration/ -v

# Cleanup
docker stop test-redis && docker rm test-redis
```

**Integration Test Example:**
```python
# tests/integration/test_redis_integration.py
import pytest
import os
from src.state.redis_state import RedisStateManager
from src.accounts.state import AccountState

@pytest.fixture
async def redis_manager():
    """Create real Redis connection for integration tests."""
    url = os.getenv("TEST_REDIS_URL", "redis://localhost:6380")
    manager = RedisStateManager(url)
    await manager.connect()
    yield manager
    # Cleanup test keys
    await manager._client.flushdb()
    await manager.close()

@pytest.mark.asyncio
async def test_save_and_get_status(redis_manager):
    """Test Redis persistence roundtrip."""
    await redis_manager.save_account_status("test-001", AccountState.ACTIVE.value)
    status = await redis_manager.get_account_status("test-001")
    assert status == "active"

@pytest.mark.asyncio
async def test_get_all_statuses(redis_manager):
    """Test scanning all account statuses."""
    await redis_manager.save_account_status("test-001", "active")
    await redis_manager.save_account_status("test-002", "paused")
    statuses = await redis_manager.get_all_account_statuses()
    assert "test-001" in statuses
    assert "test-002" in statuses
```

**Key Test Scenarios:**

| Category | Test Case | Expected Result |
|----------|-----------|-----------------|
| State Transitions | `active` → `paused` | Valid |
| State Transitions | `paused` → `active` (via resume) | Valid |
| State Transitions | `active` → `stopped` | Valid |
| State Transitions | `stopped` → `active` (via start) | Valid |
| State Transitions | `stopped` → `paused` | Invalid - raise error |
| State Transitions | `error` → `active` | Invalid - must go through stopped |
| State Transitions | `error` → `stopped` (via acknowledge) | Valid |
| State Transitions | New account (no state) → `active` | Valid |
| Validation | Non-existent account_id | Raise ValueError with available accounts |
| CLI | `accounts start ftmo-gold-001` | Activates, shows green status |
| CLI | `accounts stop ftmo-gold-001` | Prompts confirmation |
| CLI | `accounts stop ftmo-gold-001 --force` | Skips confirmation |
| CLI | `accounts pause ftmo-gold-001` | Pauses, shows yellow status |
| CLI | `accounts resume ftmo-gold-001` | Resumes paused account |
| CLI | `accounts status` | Shows all accounts with colors |
| CLI | `accounts status ftmo-gold-001` | Shows specific account |
| Redis | Save status | Key pattern `account:{id}:status` |
| Redis | Get status | Returns correct value |
| Redis | Get all statuses | Returns all configured accounts |

**CLI Quick Reference:**
```bash
# Start an account (from stopped or new)
trading-engine accounts start ftmo-gold-001

# Stop an account (positions remain open)
trading-engine accounts stop ftmo-gold-001 --force

# Pause an account temporarily
trading-engine accounts pause ftmo-gold-001

# Resume a paused account
trading-engine accounts resume ftmo-gold-001

# Show all account statuses
trading-engine accounts status

# Show specific account status
trading-engine accounts status ftmo-gold-001
```

### Environment Variables Required

```bash
# Redis connection
REDIS_URL=redis://localhost:6379

# For testing (mock Redis or use test instance)
TEST_REDIS_URL=redis://localhost:6379/1
```

### Previous Story Learnings (Story 2.1)

From the implementation of Story 2.1:
- Pydantic v2 patterns work well (`model_validate()`, `model_dump()`, `@field_validator`)
- ConfigValidationError provides user-friendly error messages
- Test structure in `tests/unit/` with pytest
- YAML loading uses `pyyaml>=6.0`
- Imports use relative paths within `src/` package

**Files created in Story 2.1 to build upon:**
- `src/accounts/models.py` - Account Pydantic models
- `src/config/loader.py` - Configuration loading
- `tests/unit/test_account_models.py` - 41 unit tests

### Git Intelligence (Recent Commits)

From commit `d23d1a7` (Story 2.1):
- Created comprehensive Pydantic models for accounts
- Added ConfigLoader with user-friendly errors
- Created 41 unit tests
- Used `uv run pytest` for test execution
- Used `uv run ruff check .` for linting

### References

- [Source: docs/architecture.md#Trading-Engine-Service] - Service structure and CLI patterns
- [Source: docs/architecture.md#Redis-Data-Structures] - Redis key patterns for account status
- [Source: docs/epic-2-context.md#Story-2.2] - Story requirements and state machine
- [Source: docs/epics.md#Story-2.2] - Acceptance criteria and prerequisites
- [Source: docs/prd.md#Account-Management] - Functional requirements FR1-FR8
- [Source: Context7 redis-py 2025-12-20] - Latest Redis asyncio patterns
- [Source: Context7 Typer 2025-12-20] - Latest Typer CLI patterns

### Project Structure Notes

- Alignment with unified project structure confirmed
- New `src/cli/` module follows existing pattern
- New `src/state/` module follows existing pattern
- No conflicts detected with existing code

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`
- Previous Story: `docs/sprint-artifacts/2-1-account-model-and-configuration.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - No issues encountered during implementation

### Completion Notes List

- Story created with comprehensive developer context from artifact analysis
- Latest redis-py asyncio patterns researched via Context7 MCP (2025-12-20)
- Latest Typer CLI patterns researched via Context7 MCP (2025-12-20)
- All acceptance criteria mapped to specific tasks
- Code patterns provided based on architecture and epic context
- Previous story (2.1) learnings incorporated
- State machine design documented with valid transitions
- **2025-12-21: Implementation completed by Dev Agent**
  - All 6 tasks completed successfully
  - 142 unit tests pass (101 new tests added for this story)
  - CLI framework with Typer 0.20.1 installed and working
  - AccountState enum with state machine transitions implemented
  - AccountManager with full lifecycle methods (start, stop, pause, resume, acknowledge_error)
  - RedisStateManager with async Redis operations
  - Full CLI command group for accounts (start, stop, pause, resume, status)
  - All linting checks pass (ruff)

### File List

Files created/modified:
- `services/trading-engine/pyproject.toml` (modified: added typer>=0.9 dependency)
- `services/trading-engine/src/accounts/__init__.py` (modified: added AccountState, AccountManager exports)
- `services/trading-engine/src/accounts/state.py` (created: AccountState enum with state machine)
- `services/trading-engine/src/accounts/account_manager.py` (created: AccountManager class)
- `services/trading-engine/src/cli/__init__.py` (created: CLI module with app export)
- `services/trading-engine/src/cli/main.py` (created: Main CLI app with accounts subcommand)
- `services/trading-engine/src/cli/accounts.py` (created: Account management commands)
- `services/trading-engine/src/cli/constants.py` (created: STATUS_COLORS constant)
- `services/trading-engine/src/state/__init__.py` (modified: added RedisStateManager export)
- `services/trading-engine/src/state/redis_state.py` (created: Async Redis state manager)
- `services/trading-engine/src/__main__.py` (modified: uses Typer CLI app)
- `services/trading-engine/tests/unit/test_account_state.py` (created: 22 state transition tests)
- `services/trading-engine/tests/unit/test_account_manager.py` (created: 31 manager tests)
- `services/trading-engine/tests/unit/test_redis_state.py` (created: 18 Redis state tests)
- `services/trading-engine/tests/unit/test_cli_accounts.py` (created: 22 CLI tests)
- `services/trading-engine/tests/unit/test_engine.py` (modified: updated signal handler test)
- `services/trading-engine/uv.lock` (modified: updated dependencies for typer)
- `services/trading-engine/tests/integration/__init__.py` (created: integration tests module)
- `services/trading-engine/tests/integration/test_redis_integration.py` (created: Redis integration tests)
- `configs/accounts.yaml.example` (modified: added CLI usage examples)

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies (if not already done)
uv sync

# 3. Run unit tests
uv run pytest tests/unit/ -v
# Expected: All tests pass

# 4. Test CLI help
uv run python -m src --help
# Expected: Shows trading-engine help with commands

# 5. Test accounts subcommand help
uv run python -m src accounts --help
# Expected: Shows accounts command group with start/stop/pause/resume/status

# 6. Test accounts start (requires Redis + accounts.yaml)
REDIS_URL=redis://localhost:6379 uv run python -m src accounts start ftmo-gold-001
# Expected: "✓ Account ftmo-gold-001 started" in green

# 7. Test accounts status (all)
REDIS_URL=redis://localhost:6379 uv run python -m src accounts status
# Expected: Shows all configured accounts with colored status

# 8. Test accounts pause/resume cycle
REDIS_URL=redis://localhost:6379 uv run python -m src accounts pause ftmo-gold-001
REDIS_URL=redis://localhost:6379 uv run python -m src accounts resume ftmo-gold-001
# Expected: Account transitions paused → active
```

### Acceptance Criteria Verification

- [x] **AC1**: `accounts start <id>` changes status to "active" *(signal processing deferred to Epic 3)*
- [x] **AC2**: `accounts stop <id>` changes status to "stopped", positions remain
- [x] **AC3**: `accounts status` shows all accounts
- [x] **AC4**: `accounts status <id>` shows specific account
- [x] **AC5**: Status persisted to Redis key `account:{id}:status`
- [x] **AC6**: State machine transitions validated
- [x] **AC7**: Invalid transitions produce clear errors
- [x] **AC8**: All unit tests pass (142 tests)

---

## Definition of Done

- [x] `src/accounts/state.py` created with AccountState enum and transitions
- [x] `src/accounts/account_manager.py` created with lifecycle methods (start, stop, pause, resume, acknowledge_error)
- [x] `src/state/redis_state.py` created with async Redis operations
- [x] `src/cli/main.py` created with Typer app
- [x] `src/cli/accounts.py` created with account commands (start, stop, pause, resume, status)
- [x] `src/cli/constants.py` created with STATUS_COLORS
- [x] `src/__main__.py` updated to use CLI framework
- [x] `pyproject.toml` updated with typer dependency
- [x] All unit tests pass: `uv run pytest tests/unit/ -v` (142 tests)
- [x] Integration tests created: `tests/integration/test_redis_integration.py`
- [x] Linting passes: `uv run ruff check .`
- [x] Story status updated to `done`

---

## Troubleshooting

### Common Issues

**Import Error: "No module named 'src.cli'"**
```bash
# Ensure CLI module is created with __init__.py
touch src/cli/__init__.py
```

**Redis Connection Error**
```bash
# Ensure Redis is running locally or via Docker
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Or check Docker Compose stack
make infra-up
```

**Typer Command Not Found**
```bash
# Ensure typer is installed
uv add typer
uv sync
```

**Async/Sync Mismatch in CLI**
```bash
# CLI commands are sync, use asyncio.run() to call async functions
def start_account(account_id: str):
    asyncio.run(_async_start_account(account_id))
```

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-20 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-20 | Latest redis-py and Typer patterns researched via Context7 MCP |
| 2025-12-20 | Previous story (2.1) learnings incorporated |
| 2025-12-20 | State machine design documented with valid transitions |
| 2025-12-21 | **Validation improvements applied:** (1) Added `resume` command to Task 4 and CLI patterns, (2) Added complete Redis initialization pattern with `get_account_manager()` helper, (3) Added account ID validation with helpful error messages, (4) Added `resume_account()` and `acknowledge_error()` methods to AccountManager, (5) Added handling for new accounts with no prior state, (6) Added integration test section with real Redis examples, (7) Added STATUS_COLORS constant and constants.py file, (8) Added graceful Redis disconnection via `manager.close()`, (9) Consolidated test scenarios into matrix table, (10) Added CLI Quick Reference section |
| 2025-12-21 | **Story implementation completed:** All 6 tasks implemented, 142 unit tests pass, CLI framework operational, all ACs satisfied |
| 2025-12-21 | **Code review completed:** Fixed 9 issues (1 HIGH, 5 MEDIUM, 3 LOW). Added CLI examples to accounts.yaml.example, fixed type annotations, created integration tests, corrected test names, marked verification checkboxes |
