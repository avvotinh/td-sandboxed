# Story 1.6: Trading Engine Service Scaffold

**Epic:** 1 - Foundation & Infrastructure
**Status:** Done
**Created:** 2025-12-19

---

## User Story

As a **developer**,
I want **a Python trading engine service scaffolded with uv and NautilusTrader**,
So that **I have the foundation for implementing multi-account trading logic in future stories**.

---

## Context

This story implements the Python trading engine scaffold for the Sandboxed multi-account trading system. The trading engine is the core service responsible for:
- Multi-account management (Epic 2+)
- Strategy execution via NautilusTrader framework
- Pluggable rule engine for FTMO compliance (Epic 4)
- Redis/ZeroMQ integration for market data and order execution

### Current State

**Existing Files:**
- `services/trading-engine/pyproject.toml` - Placeholder with empty dependencies
- `services/trading-engine/src/__init__.py` - Empty init file
- `services/trading-engine/src/__main__.py` - Placeholder with stub
- `services/trading-engine/Dockerfile` - Placeholder (alpine echo)
- `services/trading-engine/README.md` - Exists
- `services/trading-engine/.gitignore` - Exists
- `services/trading-engine/uv.lock` - Lock file from `uv build`

**Missing Items:**
- Real dependencies in pyproject.toml (nautilus_trader, redis-py, pyzmq, sqlalchemy, pydantic)
- Directory structure per architecture spec
- Multi-stage Dockerfile with uv
- Basic engine.py orchestration placeholder
- Test directory structure

### Prerequisites

- **Story 1.5 Complete:** Makefile with `build-trading-engine` command
- **Story 1.2 Complete:** Docker Compose infrastructure (Redis, TimescaleDB)
- **Story 1.4 Complete:** Environment configuration

**Previous Story:** [1-5-makefile-build-commands.md](./1-5-makefile-build-commands.md)

---

## Acceptance Criteria

### AC1: Dependencies Install Successfully
**Given** I navigate to trading-engine directory
**When** I run `uv sync`
**Then** all dependencies install without errors
**And** nautilus_trader, redis-py, pyzmq, sqlalchemy, pydantic are available

### AC2: Engine Starts and Exits Gracefully
**Given** dependencies are installed
**When** I run `uv run python -m src`
**Then** engine starts with proper logging
**And** engine exits gracefully with code 0

### AC3: Directory Structure Matches Architecture
**Given** I examine the trading-engine directory
**When** I check the structure
**Then** it matches the architecture specification (accounts/, strategies/, adapters/, rules/, backtesting/, state/, config/)

### AC4: Docker Build Succeeds
**Given** I run `docker build` in trading-engine
**When** the build completes
**Then** a working image is created with uv-based multi-stage build

### AC5: Tests Can Run
**Given** I have the test directory structure
**When** I run `uv run pytest`
**Then** pytest discovers tests (even if empty initially)
**And** test infrastructure is ready for future stories

---

## Tasks

### Task 1: Update pyproject.toml with Dependencies (AC1)
- [x] Add nautilus_trader (latest stable from PyPI)
- [x] Add redis (formerly redis-py) >=5.0
- [x] Add pyzmq >=25.0
- [x] Add sqlalchemy >=2.0
- [x] Add pydantic >=2.0
- [x] Add pydantic-settings for configuration
- [x] Update dev dependencies (pytest, pytest-asyncio, ruff)
- [x] Run `uv sync` to verify all dependencies resolve

**Note:** `asyncio` is part of Python stdlib (no pip install needed). The dependencies listed above are sufficient for the scaffold.

**pyproject.toml dependencies to add:**
```toml
dependencies = [
    "nautilus_trader>=1.200",
    "redis>=5.0",
    "pyzmq>=25.0",
    "sqlalchemy>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]
```

### Task 2: Create Directory Structure (AC3)
- [x] Create `src/engine.py` - Main engine orchestration
- [x] Create `src/accounts/` with `__init__.py`
- [x] Create `src/strategies/` with `__init__.py`
- [x] Create `src/adapters/` with `__init__.py`
- [x] Create `src/rules/` with `__init__.py`
- [x] Create `src/backtesting/` with `__init__.py`
- [x] Create `src/state/` with `__init__.py`
- [x] Create `src/config/` with `__init__.py`
- [x] Create `tests/unit/` directory
- [x] Create `tests/integration/` directory
- [x] Create `tests/fixtures/` directory
- [x] Create `tests/conftest.py` for pytest fixtures

**Target Directory Structure:**
```
trading-engine/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── engine.py               # Main engine orchestration
│   ├── accounts/               # Multi-account management (Epic 2+)
│   │   └── __init__.py
│   ├── strategies/             # Trading strategies
│   │   └── __init__.py
│   ├── adapters/               # External integrations (Redis, ZeroMQ)
│   │   └── __init__.py
│   ├── rules/                  # Pluggable rule engine (Epic 4+)
│   │   └── __init__.py
│   ├── backtesting/            # Backtest framework
│   │   └── __init__.py
│   ├── state/                  # State management
│   │   └── __init__.py
│   └── config/                 # Configuration
│       └── __init__.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── conftest.py
├── Dockerfile
├── pyproject.toml
├── uv.lock
└── README.md
```

**Subdirectory `__init__.py` Template:**
Each subdirectory should have an `__init__.py` with a docstring describing the module's purpose:
```python
"""Accounts module - Multi-account management.

This module handles:
- Account lifecycle management
- Signal routing per account
- Account state persistence

Full implementation in Epic 2+.
"""
```

**Note on `risk/` vs `rules/` directories:** Architecture shows both `risk/` (position sizing, FTMO rules) and `rules/` (rule engine). For this scaffold, we create `rules/` only. The `risk/` directory will be added in Epic 2 when actual trading logic implementation begins. The rule engine in `rules/` will incorporate risk management functionality.

### Task 3: Implement Basic Engine Entry Point (AC2)
- [x] Update `src/__main__.py` with proper logging setup
- [x] Create `src/engine.py` with TradingEngine class placeholder
- [x] Implement graceful startup with version logging
- [x] Implement graceful shutdown with signal handling (SIGTERM, SIGINT)
- [x] Add basic asyncio event loop structure

**__main__.py structure:**
```python
"""Trading Engine Entry Point."""
import asyncio
import logging
import signal
import sys

from src.engine import TradingEngine

def setup_logging() -> None:
    """Configure structured logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

def main() -> None:
    """Main entry point for the trading engine."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Trading Engine starting...")

    engine = TradingEngine()

    # Graceful shutdown handling
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Platform-safe signal handling (add_signal_handler is Unix-only)
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.shutdown()))
    # On Windows, KeyboardInterrupt is caught in the try/except below

    try:
        loop.run_until_complete(engine.run())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        loop.run_until_complete(engine.shutdown())
        loop.close()
        logger.info("Trading Engine stopped")

if __name__ == "__main__":
    main()
```

**Note:** Signal handlers use Unix-only `add_signal_handler()` API. On Windows, graceful shutdown is handled via the `KeyboardInterrupt` exception fallback.

**engine.py structure:**
```python
"""Trading Engine Core Orchestration."""
import asyncio
import logging

logger = logging.getLogger(__name__)


class TradingEngine:
    """Main trading engine orchestrator.

    This is a scaffold placeholder. Actual trading logic
    implementation begins in Epic 2.

    Responsibilities (future):
    - Multi-account management
    - Strategy execution via NautilusTrader
    - Rule engine integration for compliance
    - Redis/ZeroMQ adapter coordination
    """

    def __init__(self) -> None:
        """Initialize the trading engine."""
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def run(self) -> None:
        """Start the trading engine main loop.

        This placeholder demonstrates the async pattern that will be
        used for the actual implementation.
        """
        logger.info("Trading Engine v0.1.0 initialized")
        self._running = True

        # Placeholder: Wait for shutdown signal
        # In Epic 2+, this will run the NautilusTrader event loop
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Engine run loop cancelled")

        logger.info("Trading Engine run loop exited")

    async def shutdown(self) -> None:
        """Gracefully shutdown the trading engine.

        Ensures all resources are properly released and state is persisted.
        """
        if not self._running:
            return

        logger.info("Initiating graceful shutdown...")
        self._running = False
        self._shutdown_event.set()

        # Future: Close adapters, persist state, cleanup resources
        logger.info("Shutdown complete")
```

### Task 4: Create Multi-Stage Dockerfile (AC4)
- [x] Create multi-stage Dockerfile with uv
- [x] Stage 1: Install dependencies with uv
- [x] Stage 2: Copy source and configure runtime
- [x] Use Python 3.11+ slim base image
- [x] Configure health check endpoint (placeholder)
- [x] Set proper environment variables

**Dockerfile template:**
```dockerfile
# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-editable

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY src/ ./src/

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# Health check - verifies the module can be imported
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "from src.engine import TradingEngine; print('ok')" || exit 1

# Run the application
CMD ["python", "-m", "src"]
```

### Task 5: Create Test Infrastructure (AC5)
- [x] Create `tests/conftest.py` with basic pytest fixtures
- [x] Create `tests/unit/__init__.py`
- [x] Create `tests/integration/__init__.py`
- [x] Create sample `tests/unit/test_engine.py` placeholder
- [x] Verify `uv run pytest` discovers tests

**tests/conftest.py structure:**
```python
"""Pytest configuration and shared fixtures."""
import pytest


@pytest.fixture
def trading_engine():
    """Create a TradingEngine instance for testing.

    Returns:
        TradingEngine: A fresh engine instance for each test.
    """
    from src.engine import TradingEngine
    return TradingEngine()
```

**tests/unit/test_engine.py structure:**
```python
"""Unit tests for TradingEngine."""
import pytest


class TestTradingEngine:
    """Test suite for TradingEngine class."""

    def test_engine_initializes(self, trading_engine):
        """Engine should initialize without errors."""
        assert trading_engine is not None
        assert trading_engine._running is False

    def test_engine_not_running_initially(self, trading_engine):
        """Engine should not be running after initialization."""
        assert trading_engine._running is False

    @pytest.mark.asyncio
    async def test_engine_starts_and_stops(self, trading_engine):
        """Engine should start and stop gracefully."""
        import asyncio

        # Start engine in background task
        task = asyncio.create_task(trading_engine.run())

        # Give it time to start
        await asyncio.sleep(0.1)
        assert trading_engine._running is True

        # Shutdown
        await trading_engine.shutdown()
        await task
        assert trading_engine._running is False

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self, trading_engine):
        """Calling shutdown multiple times should be safe."""
        # Shutdown without starting should not error
        await trading_engine.shutdown()
        await trading_engine.shutdown()  # Second call should be no-op
```

### Task 6: Update README.md
- [x] Document service purpose and architecture role
- [x] Document dependency installation with uv
- [x] Document running locally vs Docker
- [x] Document test execution
- [x] Link to architecture documentation

### Task 7: Verify All Commands Work
- [x] Test `uv sync` installs dependencies
- [x] Test `uv run python -m src` starts engine
- [x] Test `uv run pytest` runs tests
- [x] Test `docker build .` builds image
- [x] Test `make build-trading-engine` from project root

---

## Technical Specifications

### NautilusTrader Integration Notes (2025)

Based on Context7 research of latest NautilusTrader documentation:

**Installation:**
```bash
# Standard installation from PyPI
pip install -U nautilus_trader

# Or with uv
uv add nautilus_trader
```

**Python Version:** Python 3.11+ required (matches project requirements)

**Package Manager:** NautilusTrader development uses `uv` - aligns with our choice

**Key Configuration Patterns:**
- Use `pydantic` for all configuration classes (NautilusTrader migrated to pydantic v2)
- `TradingNodeConfig` for live trading configuration
- `BacktestEngineConfig` for backtesting
- `LoggingConfig` for structured logging
- Configuration classes are serializable

**Adapter Development:**
- Custom adapters extend `LiveMarketDataClient` and `LiveExecClient`
- Use async patterns (`async def _connect`, `async def _disconnect`)
- Configuration via `LiveDataClientConfig` / `LiveExecClientConfig` subclasses

**Example TradingNode Configuration:**
```python
from nautilus_trader.config import TradingNodeConfig, LoggingConfig
from nautilus_trader.model.identifiers import TraderId

config = TradingNodeConfig(
    trader_id=TraderId("TRADING-001"),
    logging=LoggingConfig(
        log_level="INFO",
        log_level_file="DEBUG",
    ),
    # Data and exec clients added in Epic 2
)
```

### Dependencies Rationale

| Dependency | Version | Purpose |
|------------|---------|---------|
| nautilus_trader | >=1.200 | Core trading framework with Nautilus Trader |
| redis | >=5.0 | Redis client for state/pub-sub (renamed from redis-py) |
| pyzmq | >=25.0 | ZeroMQ for MT5 bridge communication |
| sqlalchemy | >=2.0 | Database ORM for TimescaleDB |
| pydantic | >=2.0 | Configuration validation and serialization |
| pydantic-settings | >=2.0 | Environment-based configuration |

**Version Pinning Strategy:** The `>=X.Y` constraints allow compatible updates while `uv.lock` ensures reproducible builds. For production stability, the lock file is the source of truth. If stricter pinning is needed later, update constraints to `~=X.Y` (compatible release) or exact `==X.Y.Z`.

### uv Package Manager (2025)

**Key Commands:**
- `uv sync` - Install/update dependencies from lock file
- `uv add <package>` - Add new dependency
- `uv run <command>` - Run command in project environment
- `uv build` - Build distribution packages

**Lock File:** `uv.lock` should be committed for reproducible builds

**Docker Integration:** Copy uv binary from official image:
```dockerfile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
```

---

## Architecture Compliance

This story implements:
- **Architecture - Trading Engine Structure:** Directory layout from docs/architecture.md
- **Architecture - Polyglot Stack:** Python 3.11+ with uv package manager
- **Architecture - Docker Compose:** Multi-stage Dockerfile for service

**Referenced Sections:**
- [Source: docs/architecture.md#trading-engine-service-python]
- [Source: docs/architecture.md#monorepo-structure]
- [Source: docs/epic-1-context.md#story-16-trading-engine-service-scaffold]

---

## Previous Story Intelligence

### From Story 1.5 (Completed)

**Key Learnings:**
- `make build-trading-engine` uses `cd services/trading-engine && uv build`
- `uv.lock` generated by build process - should be committed
- Test targets use `|| true` to handle empty test directories

**Files Created:**
- `Makefile` - Full implementation with trading-engine targets
- `services/trading-engine/uv.lock` - Lock file for reproducible builds
- `services/trading-engine/dist/` - Build artifacts

**Verification Commands:**
```bash
# From project root
make build-trading-engine  # Build package
cd services/trading-engine && uv sync  # Install deps
cd services/trading-engine && uv run pytest  # Run tests
```

### Git Recent Commits

```
d6e55b7 Implement spec 1 story 1.5
7c5dad4 Implement spec 1 story 1.4
82328cb Implement spec 1 story 1.3
e6ed42f Implement epec 1 story 1.1 1.2
```

**Code Patterns Established:**
- Docker Compose uses `docker compose` (v2 syntax)
- Environment variables with `${VAR:-default}` pattern
- Container health checks for all services

---

## Dev Agent Guardrails

### MUST DO:

1. **Use Python 3.11+** as required by NautilusTrader and architecture spec
2. **Use uv as package manager** - not poetry, pip, or pipenv
3. **Follow architecture directory structure** exactly as specified
4. **Implement graceful shutdown** with SIGTERM/SIGINT handling (use platform-safe pattern)
5. **Add pydantic for configuration** - NautilusTrader uses pydantic v2
6. **Create proper __init__.py** in all packages for import resolution (with docstrings)
7. **Use asyncio** for async operations - NautilusTrader is event-driven
8. **Multi-stage Dockerfile** with uv for smaller images
9. **Commit uv.lock** for reproducible builds
10. **Use platform-safe signal handling** - `add_signal_handler()` is Unix-only; Windows uses KeyboardInterrupt fallback

### DO NOT:

1. **Do NOT implement trading logic** - this is scaffold only (Epic 2+)
2. **Do NOT add Redis/ZeroMQ connection code** - adapters come in Epic 2
3. **Do NOT add NautilusTrader strategy code** - strategies come in Epic 2
4. **Do NOT use deprecated redis-py** - package is now named `redis`
5. **Do NOT skip graceful shutdown** - critical for production reliability
6. **Do NOT use pip directly** - use uv for all package operations
7. **Do NOT add complex configuration** - basic logging config only
8. **Do NOT modify docker-compose.yml** - that's Story 1.9

### File Modifications:

**Files to Modify:**
- `services/trading-engine/pyproject.toml` - Add dependencies
- `services/trading-engine/src/__main__.py` - Implement entry point
- `services/trading-engine/Dockerfile` - Multi-stage with uv
- `services/trading-engine/README.md` - Update documentation

**Files to Create:**
- `services/trading-engine/src/engine.py` - TradingEngine class
- `services/trading-engine/src/accounts/__init__.py`
- `services/trading-engine/src/strategies/__init__.py`
- `services/trading-engine/src/adapters/__init__.py`
- `services/trading-engine/src/rules/__init__.py`
- `services/trading-engine/src/backtesting/__init__.py`
- `services/trading-engine/src/state/__init__.py`
- `services/trading-engine/src/config/__init__.py`
- `services/trading-engine/tests/unit/__init__.py`
- `services/trading-engine/tests/integration/__init__.py`
- `services/trading-engine/tests/fixtures/.gitkeep`
- `services/trading-engine/tests/conftest.py`
- `services/trading-engine/tests/unit/test_engine.py`

**Files NOT to Modify:**
- `infra/docker/docker-compose.yml` - Updated in Story 1.9
- `Makefile` - Already has trading-engine targets
- Any other service directories

---

## Testing Verification

### Manual Test Steps

```bash
# 1. Navigate to trading-engine
cd /home/hopdev/Dev/Sandboxed/services/trading-engine

# 2. Install dependencies
uv sync
# Expected: All dependencies install successfully

# 3. Test engine starts and exits
uv run python -m src
# Expected: Logs "Trading Engine starting...", runs briefly, exits cleanly

# 4. Run tests
uv run pytest
# Expected: pytest discovers test files (may be empty)

# 5. Build Docker image
docker build -t trading-engine:test .
# Expected: Multi-stage build completes successfully

# 6. Test Docker image
docker run --rm trading-engine:test
# Expected: Same output as local run

# 7. From project root
cd /home/hopdev/Dev/Sandboxed
make build-trading-engine
# Expected: Package builds to dist/
```

### Verification Checklist

- [x] `uv sync` installs nautilus_trader, redis, pyzmq, sqlalchemy, pydantic
- [x] `uv run python -m src` starts engine with logging
- [x] Engine exits gracefully (no errors, exit code 0)
- [x] All directories created per architecture spec
- [x] `uv run pytest` runs without configuration errors
- [x] Docker build creates working image
- [x] `make build-trading-engine` works from project root

---

## Dependencies

- **Prerequisites:** Story 1.5 (Makefile) - DONE
- **Blocks:**
  - Story 1.9 (Full Stack Docker Compose) - needs service to add
  - Story 2.1 (Account Model) - needs scaffold
  - Epic 2+ (All trading functionality) - needs scaffold

---

## Definition of Done

- [x] pyproject.toml has all required dependencies
- [x] `uv sync` installs all dependencies without errors
- [x] Directory structure matches architecture specification
- [x] `src/engine.py` has TradingEngine class with start/stop
- [x] `src/__main__.py` has proper logging and signal handling
- [x] Dockerfile uses multi-stage build with uv
- [x] Docker build creates working image
- [x] Test infrastructure ready (conftest.py, test directories)
- [x] `uv run pytest` can discover and run tests
- [x] README.md updated with service documentation
- [x] All verification tests pass
- [x] Story status updated to `review` in sprint-status.yaml

---

## File List

**Files to Modify:**
- `services/trading-engine/pyproject.toml` - Add ~6 dependencies
- `services/trading-engine/src/__main__.py` - ~40 lines entry point
- `services/trading-engine/Dockerfile` - ~30 lines multi-stage
- `services/trading-engine/README.md` - Update documentation
- `services/trading-engine/uv.lock` - Updated by `uv sync`

**Files to Create:**
- `services/trading-engine/src/engine.py` - ~50 lines placeholder
- `services/trading-engine/src/accounts/__init__.py` - Empty with docstring
- `services/trading-engine/src/strategies/__init__.py` - Empty with docstring
- `services/trading-engine/src/adapters/__init__.py` - Empty with docstring
- `services/trading-engine/src/rules/__init__.py` - Empty with docstring
- `services/trading-engine/src/backtesting/__init__.py` - Empty with docstring
- `services/trading-engine/src/state/__init__.py` - Empty with docstring
- `services/trading-engine/src/config/__init__.py` - Empty with docstring
- `services/trading-engine/tests/unit/__init__.py`
- `services/trading-engine/tests/integration/__init__.py`
- `services/trading-engine/tests/fixtures/.gitkeep`
- `services/trading-engine/tests/conftest.py` - ~15 lines
- `services/trading-engine/tests/unit/test_engine.py` - ~20 lines placeholder

---

## References

- [Architecture - Trading Engine](../architecture.md#trading-engine-service-python)
- [Architecture - Monorepo Structure](../architecture.md#monorepo-structure)
- [Epic 1 Context - Story 1.6](../epic-1-context.md#story-16-trading-engine-service-scaffold)
- [Story 1.5 - Makefile Commands](./1-5-makefile-build-commands.md)
- [NautilusTrader Documentation](https://nautilustrader.io/docs/)
- [NautilusTrader GitHub](https://github.com/nautechsystems/nautilus_trader)
- [uv Documentation](https://docs.astral.sh/uv/)

---

## Dev Agent Record

### Context Reference

- Epic 1 Context: `docs/epic-1-context.md` (Story 1.6 section)
- Architecture: `docs/architecture.md` (Trading Engine, Monorepo sections)
- Previous Story: `docs/sprint-artifacts/1-5-makefile-build-commands.md`
- NautilusTrader docs via Context7 MCP

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- No debug issues encountered - all tasks completed successfully

### Completion Notes List

- ✅ All 6 core dependencies installed (nautilus_trader 1.221.0, redis 7.1.0, pyzmq 27.1.0, sqlalchemy 2.0.45, pydantic 2.12.5, pydantic-settings 2.12.0)
- ✅ Directory structure created per architecture spec (accounts, strategies, adapters, rules, backtesting, state, config)
- ✅ TradingEngine class implemented with async run/shutdown pattern and public `is_running` property
- ✅ Platform-safe signal handling (SIGTERM/SIGINT on Unix, KeyboardInterrupt on Windows) with factory function pattern
- ✅ Multi-stage Dockerfile with uv (builder + runtime stages)
- ✅ 7 unit tests passing (engine initialization, property tests, start/stop, shutdown idempotency, signal handler)
- ✅ Docker image builds and runs successfully
- ✅ All verification commands pass (uv sync, uv run python -m src, uv run pytest, docker build, make build-trading-engine)

### File List

**Files Modified:**
- `services/trading-engine/pyproject.toml` - Added 6 core dependencies
- `services/trading-engine/src/__main__.py` - Implemented entry point with logging and signal handling (48 lines)
- `services/trading-engine/Dockerfile` - Multi-stage uv-based build (37 lines)
- `services/trading-engine/README.md` - Comprehensive service documentation
- `services/trading-engine/uv.lock` - Updated by `uv sync`

**Files Created:**
- `services/trading-engine/src/engine.py` - TradingEngine class with async run/shutdown (55 lines)
- `services/trading-engine/src/accounts/__init__.py` - Module docstring
- `services/trading-engine/src/strategies/__init__.py` - Module docstring
- `services/trading-engine/src/adapters/__init__.py` - Module docstring
- `services/trading-engine/src/rules/__init__.py` - Module docstring
- `services/trading-engine/src/backtesting/__init__.py` - Module docstring
- `services/trading-engine/src/state/__init__.py` - Module docstring
- `services/trading-engine/src/config/__init__.py` - Module docstring
- `services/trading-engine/tests/unit/__init__.py`
- `services/trading-engine/tests/integration/__init__.py`
- `services/trading-engine/tests/fixtures/.gitkeep`
- `services/trading-engine/tests/conftest.py` - Pytest fixtures (14 lines)
- `services/trading-engine/tests/unit/test_engine.py` - 4 unit tests (38 lines)

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-19 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-19 | NautilusTrader latest documentation researched via Context7 MCP |
| 2025-12-19 | **Validation improvements applied:** (1) Added `engine.py` code skeleton with TradingEngine class; (2) Added platform-safe signal handling for Windows compatibility; (3) Updated Dockerfile health check to verify module import; (4) Added `conftest.py` and `test_engine.py` templates; (5) Added subdirectory `__init__.py` docstring template; (6) Clarified `risk/` vs `rules/` directory decision; (7) Clarified asyncio stdlib note; (8) Added version pinning strategy documentation; (9) Added pre-commit and dev agent record notes |
| 2025-12-19 | **Story implemented by dev-story workflow:** All 7 tasks completed - pyproject.toml dependencies, directory structure, engine.py, __main__.py, Dockerfile, test infrastructure, README.md. 4 unit tests passing. Docker build verified. |
| 2025-12-19 | **Code review fixes applied:** (1) Added public `is_running` property to TradingEngine; (2) Updated tests to use public API instead of private `_running`; (3) Refactored signal handler to use factory function instead of lambda; (4) Added 3 new tests (is_running property, signal handler creation, integration marker); (5) Updated File List to include uv.lock; (6) Checked verification checklist. 7 tests now passing. |

---

## Notes

- This story is **scaffold only** - no trading logic implementation
- NautilusTrader requires Python 3.11+ with Rust components (pre-built wheels available)
- The engine placeholder should demonstrate async patterns for future development
- Focus on clean, extensible structure that Epic 2+ can build upon
- Test infrastructure is more important than test coverage at this stage
- **Pre-commit (optional):** For local development, consider running `uv run ruff check . && uv run ruff format .` before commits
- **Dev Agent Record:** Ensure the `{{agent_model_name_version}}` placeholder is filled with the actual model name/version used during implementation
