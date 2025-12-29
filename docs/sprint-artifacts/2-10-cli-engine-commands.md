# Story 2.10: CLI Engine Commands

Status: done

## Story

As a **trader**,
I want **CLI commands to control the trading engine**,
So that **I can start, stop, and monitor the system from the command line**.

## Acceptance Criteria

1. **AC1**: Given I am in the trading-engine directory, when I run `trading-engine start`, then the engine starts and loads all active accounts

2. **AC2**: Given the engine is running, when I run `trading-engine stop`, then the engine performs graceful shutdown and all state is persisted

3. **AC3**: Given the engine is running, when I run `trading-engine status`, then I see:
   - Engine status (running/stopped)
   - Number of active accounts
   - Connection status (Redis, MT5 bridge)

4. **AC4**: Given I run `trading-engine config dump`, when the command executes, then I see the resolved configuration (with secrets masked)

5. **AC5**: Given I run `trading-engine start --dry-run`, when the command executes, then configuration is validated but no trading starts

6. **AC6**: Given I run `trading-engine start --verbose`, when the command executes, then debug logging is enabled

7. **AC7**: Integration tests cover all CLI commands and edge cases

## Tasks / Subtasks

### Task 1: Enhance `start` Command (AC: 1, 5, 6)
- [x] Implement actual engine startup in `src/cli/main.py`
- [x] Add `--dry-run` flag for validation-only mode
- [x] Add `--verbose` flag to enable DEBUG logging
- [x] Load and initialize AccountManager with all configured accounts
- [x] Connect to Redis and validate connection
- [x] Start RedisAdapter for market data subscription
- [x] Initialize ZmqAdapter for MT5 bridge connection (when available)
- [x] Log startup sequence with clear status messages

**Implementation Pattern:**
```python
@app.command()
def start(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate only, don't start trading")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
) -> None:
    """Start the trading engine."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if dry_run:
        typer.echo("Dry run mode - validating configuration...")
        # Validate config, connections, then exit
    else:
        # Full startup sequence
```

### Task 2: Enhance `stop` Command (AC: 2)
- [x] Implement graceful shutdown sequence per architecture doc
- [x] Set `engine:state` → "stopping" immediately
- [x] Stop signal processing (unsubscribe from Redis pub/sub)
- [x] Wait for in-flight orders (check `ZmqAdapter.get_pending_order_count()`)
- [x] Persist final state: set `engine:state` → "stopped", delete `engine:start_time`
- [x] Close Redis and ZMQ connections cleanly
- [x] Add `--force` flag to skip confirmation
- [x] Log each shutdown step with timestamps

**Graceful Shutdown Implementation:**
```python
@app.command()
def stop(
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Stop the trading engine gracefully."""
    if not force:
        typer.confirm("Stop the trading engine? (accounts will remain paused)", abort=True)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis = RedisStateManager(redis_url)

    try:
        _run_async(redis.connect())

        # 1. Set stopping state
        typer.echo("Initiating graceful shutdown...")
        _run_async(set_engine_state(redis, "stopping"))

        # 2. Stop new signal processing (would need RedisAdapter reference)
        typer.echo("  → Stopping signal processing...")
        # await redis_adapter.disconnect() if available

        # 3. Wait for in-flight orders (with timeout)
        typer.echo("  → Waiting for pending orders...")
        # await zmq_adapter.wait_pending_orders(timeout=30) if available

        # 4. Persist final state
        typer.echo("  → Persisting final state...")
        _run_async(set_engine_state(redis, "stopped"))
        _run_async(redis.client.delete(ENGINE_START_TIME_KEY))

        # 5. Close connections
        typer.echo("  → Closing connections...")
        _run_async(redis.close())

        typer.echo(typer.style("✓ Trading engine stopped", fg=STATUS_COLORS["stopped"]))

    except Exception as e:
        typer.echo(typer.style(f"✗ Shutdown error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
```

### Task 3: Enhance `status` Command (AC: 3)
- [x] Show engine status (running/stopped/starting/stopping)
- [x] Display number of active accounts by state
- [x] Show Redis connection status (use `client.ping()`)
- [x] Show MT5 bridge connection status (`ZmqAdapter.is_connected`)
- [x] Add `--json` flag for JSON output (disable colors in JSON mode)
- [x] Color-code human-readable output using STATUS_COLORS

**Status Command Implementation:**
```python
import json
from typing_extensions import Annotated

@app.command()
def status(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON for scripting")] = False,
) -> None:
    """Show trading engine status."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis = RedisStateManager(redis_url)

    try:
        _run_async(redis.connect())
        redis_status = "connected"
    except Exception:
        redis_status = "disconnected"

    # Get engine state and uptime from Redis
    engine_state = _run_async(get_engine_state(redis)) if redis_status == "connected" else "unknown"
    uptime = _run_async(get_uptime(redis)) if engine_state == "running" else "N/A"

    # Get account statuses
    statuses = _run_async(redis.get_all_account_statuses()) if redis_status == "connected" else {}
    active = sum(1 for s in statuses.values() if s == "active")
    paused = sum(1 for s in statuses.values() if s == "paused")
    stopped = sum(1 for s in statuses.values() if s == "stopped")

    # ZMQ bridge status (socket state only)
    zmq_host = os.getenv("ZMQ_BRIDGE_HOST", "localhost")
    zmq_port = os.getenv("ZMQ_PUB_PORT", "5556")
    zmq_status = "disconnected"  # Would need ZmqAdapter instance to check is_connected

    status_data = {
        "engine": {"status": engine_state, "uptime": uptime},
        "accounts": {"active": active, "paused": paused, "stopped": stopped, "total": len(statuses)},
        "connections": {
            "redis": {"status": redis_status, "url": redis_url},
            "mt5_bridge": {"status": zmq_status, "host": f"{zmq_host}:{zmq_port}"},
        },
    }

    if json_output:
        typer.echo(json.dumps(status_data, indent=2))
    else:
        # Human-readable colored output
        typer.echo("Trading Engine Status")
        typer.echo("=" * 21)
        engine_color = STATUS_COLORS.get(engine_state, STATUS_COLORS["unknown"])
        typer.echo(f"Engine:     " + typer.style(engine_state, fg=engine_color))
        typer.echo(f"Uptime:     {uptime}")
        typer.echo(f"Accounts:   {active} active, {paused} paused, {stopped} stopped")
        typer.echo("")
        typer.echo("Connections:")
        redis_color = STATUS_COLORS.get(redis_status, STATUS_COLORS["unknown"])
        typer.echo(f"  Redis:     " + typer.style(redis_status, fg=redis_color) + f" ({redis_url})")
        zmq_color = STATUS_COLORS.get(zmq_status, STATUS_COLORS["unknown"])
        typer.echo(f"  MT5 Bridge: " + typer.style(zmq_status, fg=zmq_color) + f" ({zmq_host}:{zmq_port})")

    if redis_status == "connected":
        _run_async(redis.close())
```

**Expected Human-Readable Output:**
```
Trading Engine Status
=====================
Engine:     running
Uptime:     2h 15m 32s
Accounts:   3 active, 1 paused, 0 stopped

Connections:
  Redis:     connected (redis://localhost:6379)
  MT5 Bridge: connected (localhost:5556)
```

**Expected JSON Output (`--json`):**
```json
{
  "engine": {"status": "running", "uptime": "2h 15m 32s"},
  "accounts": {"active": 3, "paused": 1, "stopped": 0, "total": 4},
  "connections": {
    "redis": {"status": "connected", "url": "redis://localhost:6379"},
    "mt5_bridge": {"status": "connected", "host": "localhost:5556"}
  }
}
```

### Task 4: Add `config` Subcommand Group (AC: 4)
- [x] Create `services/trading-engine/src/cli/config.py` with config subcommands
- [x] Implement `config dump` command with secret masking
- [x] Implement `config validate` command for standalone validation
- [x] Add `--format` option for yaml/json output
- [x] Register config_app in main.py: `app.add_typer(config_app, name="config")`

**Secret Masking Implementation (CRITICAL):**
```python
# Fields to mask - any field name containing these substrings (case-insensitive)
SECRETS_TO_MASK = ["password", "token", "secret", "api_key", "credential"]

def mask_secrets(config_dict: dict) -> dict:
    """Recursively mask secret fields in config dictionary."""
    result = {}
    for key, value in config_dict.items():
        key_lower = key.lower()
        if any(secret in key_lower for secret in SECRETS_TO_MASK):
            result[key] = "***"
        elif isinstance(value, dict):
            result[key] = mask_secrets(value)
        elif isinstance(value, list):
            result[key] = [
                mask_secrets(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            result[key] = value
    return result
```

**Config Dump Implementation:**
```python
import json
import yaml
from typing_extensions import Annotated

config_app = typer.Typer(help="Configuration management")

@config_app.command("dump")
def dump_config(
    format: Annotated[str, typer.Option("--format", "-f", help="Output format (yaml/json)")] = "yaml",
) -> None:
    """Show resolved configuration with secrets masked."""
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        loader = ConfigLoader(config_path)
        config = loader.load()
        config_dict = config.model_dump()
        masked = mask_secrets(config_dict)

        if format == "json":
            typer.echo(json.dumps(masked, indent=2))
        else:
            typer.echo(yaml.dump(masked, default_flow_style=False))
    except FileNotFoundError:
        typer.echo(typer.style(f"✗ Config not found: {config_path}", fg="red"))
        raise typer.Exit(1)
    except ConfigValidationError as e:
        typer.echo(typer.style(f"✗ {e}", fg="red"))
        raise typer.Exit(1)

@config_app.command("validate")
def validate_config() -> None:
    """Validate configuration without starting engine."""
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        loader = ConfigLoader(config_path)
        config = loader.load()
        typer.echo(typer.style("✓ Configuration valid", fg="green"))
        typer.echo(f"  Accounts: {len(config.accounts)}")
        for acc in config.accounts:
            typer.echo(f"    - {acc.id}: {acc.name}")
    except (FileNotFoundError, ConfigValidationError) as e:
        typer.echo(typer.style(f"✗ {e}", fg="red"))
        raise typer.Exit(1)
```

### Task 5: Write Integration Tests (AC: 7)
- [x] Create `services/trading-engine/tests/integration/test_cli.py`
- [x] Test `start --dry-run` validates config, Redis, and env vars without starting
- [x] Test `start --verbose` enables DEBUG logging level
- [x] Test `stop --force` performs graceful shutdown without confirmation
- [x] Test `status` shows engine state and connection info
- [x] Test `status --json` outputs valid JSON
- [x] Test `config dump` masks all secret fields
- [x] Test `config validate` passes/fails correctly
- [x] Test error cases (missing config, connection failures, invalid config)
- [x] Use CliRunner from Typer for testing (no real Redis needed for unit tests)

**Dry-Run Validation Specification:**
The `--dry-run` flag must validate ALL of the following without starting trading:
1. Config file exists and parses (YAML syntax valid)
2. Config validates against Pydantic schema (AccountsConfig)
3. All required env vars for MT5 passwords are set (password_env fields)
4. Redis connection can be established (ping succeeds)
5. Account IDs are unique (no duplicates)

**Test Pattern with Mocks:**
```python
from typer.testing import CliRunner
from unittest.mock import patch, AsyncMock
from src.cli.main import app

runner = CliRunner()

class TestStartDryRun:
    """Tests for start --dry-run validation."""

    def test_dry_run_validates_config_exists(self):
        """Should fail gracefully when config file missing."""
        with patch.dict("os.environ", {"ACCOUNTS_CONFIG": "/nonexistent.yaml"}):
            result = runner.invoke(app, ["start", "--dry-run"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_dry_run_validates_redis_connection(self, mock_redis):
        """Should attempt Redis connection in dry-run mode."""
        mock_redis.connect = AsyncMock(side_effect=ConnectionError("Redis down"))
        result = runner.invoke(app, ["start", "--dry-run"])
        assert result.exit_code == 1
        assert "Redis" in result.output

    def test_dry_run_success_shows_validation_results(self, mock_redis, mock_config):
        """Should show what was validated on success."""
        result = runner.invoke(app, ["start", "--dry-run"])
        assert result.exit_code == 0
        assert "Configuration valid" in result.output or "Dry run" in result.output
        assert "accounts" in result.output.lower()

class TestStatusJson:
    """Tests for status --json output."""

    def test_status_json_is_valid_json(self, mock_redis):
        """--json output must be valid JSON."""
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "engine" in data
        assert "accounts" in data
        assert "connections" in data

class TestConfigDump:
    """Tests for config dump command."""

    def test_config_dump_masks_password_fields(self, mock_config):
        """Any field with 'password' in name should be masked."""
        result = runner.invoke(app, ["config", "dump"])
        assert result.exit_code == 0
        assert "***" in result.output
        # Ensure actual password values don't appear
        assert "FTMO_PASS" not in result.output  # env var name is fine
```

## Dev Notes

### Quick Reference

**Key Implementation Files:**
- `src/cli/main.py` - Main CLI entrypoint (EXISTING - enhance)
- `src/cli/accounts.py` - Account management commands (EXISTING - complete)
- `src/cli/config.py` - Config commands (NEW)
- `src/cli/constants.py` - Status colors (EXISTING)
- `tests/integration/test_cli.py` - CLI tests (NEW)

**Existing CLI Structure (Typer-based):**
```
trading-engine
├── start            # ENHANCE: Add --dry-run, --verbose, real startup
├── stop             # ENHANCE: Add graceful shutdown
├── status           # ENHANCE: Add connection status, --json
├── accounts         # COMPLETE - already implemented
│   ├── start <id>
│   ├── stop <id>
│   ├── pause <id>
│   ├── resume <id>
│   └── status [id]
└── config           # NEW
    ├── dump
    └── validate
```

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**
```
CLI Command Surface:
- trading-engine start
- trading-engine start --dry-run  # Validate only
- trading-engine stop
- trading-engine status
- trading-engine accounts list/start/stop/status
- trading-engine config dump/validate
```

**Technology Stack:**
| Component | Technology | Version |
|-----------|------------|---------|
| CLI Framework | Typer | 0.9+ |
| Package Manager | uv | Latest |
| Python | Python | 3.11+ |
| Testing | pytest + CliRunner | 7.0+ |

### Technical Requirements from Context7 Typer Research (2025-12-29)

**Typer CLI Best Practices:**
- Use `typing_extensions.Annotated` for type-safe options (see Task 1-4 examples)
- Use `typer.Typer()` with `add_completion=False` to disable shell completion
- Add subcommand groups with `app.add_typer(config_app, name="config")`
- Optional: Use `rich_help_panel` parameter to organize help output into sections
- See `accounts.py` for complete working implementation patterns

### Existing Codebase Integration

**AccountManager Integration (src/accounts/account_manager.py):**
- `AccountManager.load_accounts(configs)` - Load from config
- `AccountManager.start_account(id)` - Start single account
- `AccountManager.stop_account(id)` - Stop single account
- `AccountManager.get_all_statuses()` - Get all account statuses
- `AccountManager.close()` - Cleanup connections

**RedisStateManager (src/state/redis_state.py):**
- `RedisStateManager.connect()` - Connect to Redis
- `RedisStateManager.close()` - Close connection
- `RedisStateManager.client.ping()` - Verify connection health (use via try/except)

**ConfigLoader (src/config/loader.py):**
- `ConfigLoader(path).load()` - Load and validate YAML
- Returns `AccountsConfig` with list of `AccountConfig` objects

**ZmqAdapter (src/adapters/zmq_adapter.py):**
- `ZmqAdapter.is_connected` - Check socket connection state
- `ZmqAdapter.connect()` / `ZmqAdapter.disconnect()` - Connection lifecycle

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── cli/
│   │   ├── __init__.py          # EXISTING: Export app
│   │   ├── main.py              # MODIFY: Enhance start/stop/status
│   │   ├── accounts.py          # EXISTING: Account commands (complete)
│   │   ├── config.py            # NEW: Config subcommands
│   │   └── constants.py         # MODIFY: Add new status colors
├── tests/
│   ├── integration/
│   │   └── test_cli.py          # NEW: CLI integration tests
```

### Engine State Management (CRITICAL - New Implementation Required)

**Engine state is NOT currently tracked in the codebase.** Implement via Redis keys:

```python
# Redis key patterns for engine state
ENGINE_STATE_KEY = "engine:state"        # Values: "running", "stopped", "starting", "stopping"
ENGINE_START_TIME_KEY = "engine:start_time"  # ISO timestamp for uptime calculation

# Implementation in main.py
async def set_engine_state(redis: RedisStateManager, state: str) -> None:
    """Set engine state in Redis."""
    await redis.client.set(ENGINE_STATE_KEY, state)

async def get_engine_state(redis: RedisStateManager) -> str:
    """Get engine state from Redis."""
    return await redis.client.get(ENGINE_STATE_KEY) or "stopped"

async def get_uptime(redis: RedisStateManager) -> str:
    """Calculate engine uptime from start timestamp."""
    from datetime import datetime, timezone
    start_str = await redis.client.get(ENGINE_START_TIME_KEY)
    if not start_str:
        return "N/A"
    start = datetime.fromisoformat(start_str)
    delta = datetime.now(timezone.utc) - start
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"
```

**Start command must:**
1. Set `engine:state` → "starting"
2. Perform startup sequence
3. Set `engine:state` → "running"
4. Set `engine:start_time` → current ISO timestamp

**Stop command must:**
1. Set `engine:state` → "stopping"
2. Perform graceful shutdown
3. Set `engine:state` → "stopped"
4. Delete `engine:start_time`

### Status Colors Update (constants.py)

Add these new status colors:
```python
STATUS_COLORS: dict[str, str] = {
    "active": typer.colors.GREEN,
    "running": typer.colors.GREEN,     # NEW: Engine running
    "paused": typer.colors.YELLOW,
    "starting": typer.colors.CYAN,     # NEW: Engine starting
    "stopping": typer.colors.YELLOW,   # NEW: Engine stopping
    "stopped": typer.colors.RED,
    "error": typer.colors.RED,
    "unknown": typer.colors.WHITE,
    "connected": typer.colors.GREEN,   # NEW: Connection status
    "disconnected": typer.colors.RED,  # NEW: Connection status
}
```

### Testing Requirements

See Task 5 above for comprehensive test patterns with mocks.

**Test Execution:**
```bash
cd services/trading-engine

# Run CLI tests
uv run pytest tests/integration/test_cli.py -v

# Run all tests
uv run pytest -v

# Check code quality
uv run ruff check src/cli/
```

### Previous Story Learnings (Story 2.9)

From Story 2.9 Signal Filtering implementation:

**Key Patterns Established:**
- Use `typing_extensions.Annotated` for Typer options
- Status colors defined in `cli/constants.py`
- Async operations wrapped with `_run_async()` helper
- Error handling with `typer.Exit(1)` for failures
- Color-coded output with `typer.style()`

**Implementation Patterns from Story 2.9:**
```python
def _run_async(coro) -> Any:
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)

# Error handling pattern
try:
    manager = _get_account_manager()
    # ... do work
except ValueError as e:
    typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
    raise typer.Exit(1)
```

### Git Intelligence (Recent Commits)

From commit `b5f4ecd` (Story 2.9):
- Implemented signal filtering with DEBUG logging
- 100% test coverage on data_router.py
- 546+ total tests passing

**Pattern Continuity:**
- CLI follows same patterns as accounts.py
- Error handling consistent with existing code
- Tests use same pytest patterns

### Environment Variables Required

```bash
# Required for CLI operation
REDIS_URL=redis://localhost:6379
ACCOUNTS_CONFIG=configs/accounts.yaml

# Optional
LOG_LEVEL=INFO  # or DEBUG with --verbose
ZMQ_BRIDGE_HOST=localhost
ZMQ_PUB_PORT=5556
```

### Dependencies (pyproject.toml)

```toml
dependencies = [
    "typer>=0.9",      # CLI framework (EXISTING)
    "redis>=5.0",      # Redis connection (EXISTING)
    "pydantic>=2.0",   # Config validation (EXISTING)
    "pyyaml>=6.0",     # Config dump YAML output (VERIFY - may need to add)
    # ... other deps
]
```

**Note:** Verify `pyyaml` is in dependencies for `config dump --format yaml`. If not present, add it.

### Project Structure Notes

- CLI already scaffolded in `src/cli/` with Typer
- Account commands are complete (`accounts.py`)
- Main commands (`start`, `stop`, `status`) need full implementation
- Need to add `config` subcommand group
- Integration tests needed for all CLI paths

### References

- [Source: docs/architecture.md#CLI-Command-Surface] - CLI requirements
- [Source: docs/epic-2-context.md#Story-2.10] - Technical context
- [Source: docs/epics.md#Story-2.10] - Original story definition
- [Source: docs/prd.md#Developer-Tool-Requirements] - CLI command specifications
- [Source: docs/sprint-artifacts/2-9-signal-filtering-by-symbol.md] - Previous story patterns
- [Source: Context7 Typer 2025-12-29] - Latest Typer CLI patterns (Annotated, rich_help_panel)
- [Source: services/trading-engine/src/cli/main.py] - Existing CLI scaffold
- [Source: services/trading-engine/src/cli/accounts.py] - Account command patterns

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`
- Previous Story: `docs/sprint-artifacts/2-9-signal-filtering-by-symbol.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Story created with comprehensive analysis of existing codebase
- **KEY FINDING**: CLI is already scaffolded using Typer 0.9+ in `src/cli/`
- Account commands (`accounts.py`) are fully implemented
- Main commands (`start`, `stop`, `status`) are placeholders needing full implementation
- Need to add `config` subcommand group (dump, validate)
- Context7 MCP research: Latest Typer patterns with `Annotated`, `rich_help_panel` (2025-12-29)
- Integration tests pattern using `typer.testing.CliRunner`
- Environment variable handling via `os.getenv()` already established

**Implementation Completed (2025-12-29):**
- Implemented full `start` command with `--dry-run` and `--verbose` flags
- `--dry-run` validates config file, MT5 password env vars, unique account IDs, and Redis connection
- `--verbose` enables DEBUG logging level
- Start command sets engine state to "starting" -> "running" with timestamp
- Implemented graceful `stop` command with `--force` flag
- Stop command sets state to "stopping" -> "stopped" and cleans up start_time
- Implemented comprehensive `status` command with `--json` flag
- Status shows engine state, uptime, account counts by state, Redis and MT5 bridge connection status
- Created `config.py` with `dump` and `validate` subcommands
- Secret masking implemented for password, token, secret, api_key, credential fields
- Updated `constants.py` with new status colors (running, starting, stopping, connected, disconnected)
- Added ENGINE_STATE_KEY and ENGINE_START_TIME_KEY constants
- Updated `__init__.py` to export config_app
- Created 31 comprehensive integration tests covering all CLI commands
- All 574 non-integration tests pass (9 integration tests require Redis)
- Ruff code quality checks pass

### File List

**Files Modified:**
- `services/trading-engine/src/cli/main.py` - Enhanced start/stop/status with full implementation, added engine state functions
- `services/trading-engine/src/cli/__init__.py` - Added config_app export
- `services/trading-engine/src/cli/constants.py` - Added new status colors (running, starting, stopping, connected, disconnected), ENGINE_STATE_KEY, ENGINE_START_TIME_KEY
- `services/trading-engine/src/cli/config.py` - Fixed secret masking for camelCase, added format validation, renamed parameter
- `services/trading-engine/tests/unit/test_cli_accounts.py` - Updated tests for new CLI structure
- `docs/sprint-artifacts/sprint-status.yaml` - Updated sprint status

**Files Created:**
- `services/trading-engine/src/cli/config.py` - Config subcommands (dump, validate) with secret masking
- `services/trading-engine/tests/integration/test_cli.py` - 46 CLI integration tests with mocks (15 new tests added in code review)

**Existing Files (Reference Only):**
- `services/trading-engine/src/cli/accounts.py` - Complete, used as pattern for error handling
- `services/trading-engine/src/state/redis_state.py` - Used for engine state persistence
- `services/trading-engine/src/adapters/zmq_adapter.py` - Reference for bridge status check

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies
uv sync

# 3. Test CLI help
uv run python -m src --help

# 4. Test start dry-run
uv run python -m src start --dry-run

# 5. Test status command
uv run python -m src status

# 6. Test config dump
uv run python -m src config dump

# 7. Run CLI tests
uv run pytest tests/integration/test_cli.py -v

# 8. Check code quality
uv run ruff check src/cli/
```

### Acceptance Criteria Verification

- [x] **AC1**: `trading-engine start` starts engine and loads accounts
- [x] **AC2**: `trading-engine stop` performs graceful shutdown with state persistence
- [x] **AC3**: `trading-engine status` shows engine state, accounts, and connections
- [x] **AC4**: `trading-engine config dump` shows config with secrets masked
- [x] **AC5**: `trading-engine start --dry-run` validates without starting
- [x] **AC6**: `trading-engine start --verbose` enables DEBUG logging
- [x] **AC7**: Integration tests cover all CLI commands

---

## Definition of Done

- [x] `start` command fully implemented with --dry-run and --verbose flags
- [x] `stop` command performs graceful shutdown
- [x] `status` command shows engine state, accounts, and connection health
- [x] `config dump` command shows masked configuration
- [x] All integration tests pass
- [x] Code quality passes: `uv run ruff check src/cli/`
- [x] Story status updated to `done` after code review

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-29 | Story created by create-story workflow with Context7 MCP Typer research |
| 2025-12-29 | Analyzed existing CLI scaffold in `src/cli/` |
| 2025-12-29 | Identified account commands as complete, main commands as placeholders |
| 2025-12-29 | Added comprehensive dev notes with Typer patterns from Context7 |
| 2025-12-29 | **Story Validation (validate-create-story)**: Applied 5 critical fixes, 4 enhancements, 3 optimizations |
| 2025-12-29 | Fixed: Removed non-existent `RedisStateManager.health_check()` reference - use `client.ping()` instead |
| 2025-12-29 | Added: Engine State Management section with Redis key patterns (`engine:state`, `engine:start_time`) |
| 2025-12-29 | Added: Uptime tracking implementation with `get_uptime()` helper function |
| 2025-12-29 | Added: Secret Masking implementation with `SECRETS_TO_MASK` list and recursive `mask_secrets()` function |
| 2025-12-29 | Added: Complete `status --json` implementation with structured JSON output |
| 2025-12-29 | Added: Complete `config validate` command specification |
| 2025-12-29 | Added: Graceful Shutdown implementation detail with state transitions |
| 2025-12-29 | Added: New STATUS_COLORS for running/starting/stopping/connected/disconnected states |
| 2025-12-29 | Added: Dry-run validation specification (5 validation steps) |
| 2025-12-29 | Enhanced: Test patterns with mocks for unit testing without real Redis |
| 2025-12-29 | Updated: File paths to use full `services/trading-engine/` prefix for clarity |
| 2025-12-29 | **Implementation Complete**: All 5 tasks implemented, 31 integration tests created |
| 2025-12-29 | Created: `src/cli/config.py` with dump and validate subcommands, secret masking |
| 2025-12-29 | Modified: `src/cli/main.py` with full start/stop/status implementation |
| 2025-12-29 | Modified: `src/cli/constants.py` with new status colors and engine state keys |
| 2025-12-29 | Created: `tests/integration/test_cli.py` with 31 comprehensive tests |
| 2025-12-29 | All 574 non-integration tests pass, ruff checks pass |
| 2025-12-29 | Story status: Ready for Review |
| 2025-12-29 | **Code Review Completed**: Fixed 9 issues (3 HIGH, 5 MEDIUM, 1 LOW) |
| 2025-12-29 | Fixed H1: Secret masking now handles camelCase (apiKey, authToken) |
| 2025-12-29 | Fixed H2: Redis resource leak in dry-run validation - added try/finally cleanup |
| 2025-12-29 | Fixed H3: config dump --format now validates input (yaml/json only) |
| 2025-12-29 | Fixed M1: Logging configuration order corrected (basicConfig before setLevel) |
| 2025-12-29 | Fixed M3: get_uptime() handles corrupt timestamps gracefully |
| 2025-12-29 | Fixed M5: Renamed 'format' parameter to 'output_format' (avoid shadowing) |
| 2025-12-29 | Fixed L1: Standardized error messages to use ✓/✗ symbols |
| 2025-12-29 | Added 15 new unit tests for validation helpers, secret masking, uptime calc |
| 2025-12-29 | Updated File List to include sprint-status.yaml |
| 2025-12-29 | All 46 integration tests pass, all ruff checks pass |
| 2025-12-29 | Story status: done |
