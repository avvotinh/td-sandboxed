# Tech-Spec: Epic 1 - Foundation & Project Setup

**Created:** 2025-12-03
**Status:** Ready for Development
**Epic:** 1 - Foundation & Project Setup
**Service:** trading-engine (Python/Nautilus Trader)

---

## Overview

### Problem Statement

The trading-engine service needs a properly structured Python project with configuration management, structured logging, CLI interface, and Docker deployment capability before any trading logic can be implemented.

### Solution

Create a production-ready Python project structure using:
- **Poetry** for dependency management
- **Pydantic Settings** for type-safe configuration with YAML + environment variable support
- **structlog** for JSON-formatted structured logging
- **Click** for CLI command interface
- **Docker** multi-stage build for deployment

### Scope

**In Scope:**
- Project directory structure following Architecture spec
- `pyproject.toml` with all dependencies (Nautilus Trader 1.x, redis, psycopg2, pyzmq, pydantic, structlog, click)
- Configuration system loading from YAML with environment variable overrides
- Structured JSON logging with correlation IDs
- CLI entry point with `run`, `backtest`, `validate`, `version` commands
- Multi-stage Dockerfile optimized for size (<500MB)
- Unit tests for configuration validation

**Out of Scope:**
- Actual trading strategies (Epic 4)
- External adapters - Redis, TimescaleDB, ZeroMQ (Epic 2)
- FTMO compliance engine (Epic 3)
- Backtesting logic (Epic 5)

---

## Context for Development

### Codebase Patterns

**From Architecture Document (Section: Trading-Engine Service):**

```
services/trading-engine/
├── src/
│   ├── __init__.py
│   ├── __main__.py              # CLI entry point
│   ├── config/                  # Configuration
│   │   ├── __init__.py
│   │   ├── settings.py          # Pydantic Settings models
│   │   └── loader.py            # YAML + env loading
│   ├── adapters/                # (Epic 2 - stub only)
│   ├── risk/                    # (Epic 3 - stub only)
│   ├── strategies/              # (Epic 4 - stub only)
│   ├── backtesting/             # (Epic 5 - stub only)
│   └── state/                   # (Epic 6 - stub only)
├── tests/
│   ├── unit/
│   │   └── test_config.py
│   ├── integration/
│   └── conftest.py
├── config/
│   └── settings.yaml            # Default configuration
├── pyproject.toml
├── Dockerfile
├── README.md
└── .env.example
```

### Files to Reference

| File | Purpose |
|------|---------|
| `docs/architecture.md` | Section 3: Trading-Engine Service structure |
| `docs/epics-trading-engine.md` | Stories 1.1-1.5 acceptance criteria |
| `services/tv-api/internal/config/` | Pattern reference for config loading |
| `services/tv-api/Dockerfile` | Pattern reference for multi-stage build |

### Technical Decisions

#### TD-1: Pydantic Settings v2 for Configuration

**Decision:** Use `pydantic-settings` v2 with custom YAML source

**Rationale:**
- Type-safe configuration with validation
- Environment variable override support built-in
- Nested configuration for different components
- Fail-fast on invalid configuration

**Implementation Pattern (from Context7 research):**

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class EngineConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='TRADING_',
        env_nested_delimiter='__',
    )

    redis_url: str = Field(default='redis://localhost:6379')
    timescale_url: str = Field(default='postgres://localhost:5432/trading')
    zmq_bridge_host: str = Field(default='localhost')
    zmq_pub_port: int = Field(default=5556)
    zmq_sub_port: int = Field(default=5557)
    trading_mode: Literal['backtest', 'paper', 'live'] = Field(default='paper')
    log_level: str = Field(default='INFO')
```

#### TD-2: structlog with JSON Renderer

**Decision:** Use structlog with JSONRenderer for production, ConsoleRenderer for development

**Rationale:**
- Structured logs for log aggregation systems
- Context binding for correlation IDs
- Pretty output during development
- stdlib integration for third-party libraries

**Implementation Pattern (from Context7 research):**

```python
import sys
import structlog

def configure_logging(log_level: str = "INFO", json_output: bool = True):
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output or not sys.stderr.isatty():
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

#### TD-3: Click for CLI Framework

**Decision:** Use Click with command groups

**Rationale:**
- Composable command structure
- Built-in help generation
- Environment variable support
- Context passing between commands

**Implementation Pattern (from Context7 research):**

```python
import click

@click.group()
@click.option('--config', '-c', default='config/settings.yaml', help='Config file path')
@click.option('--verbose', '-v', is_flag=True, help='Enable debug logging')
@click.pass_context
def cli(ctx, config: str, verbose: bool):
    """FTMO Trading Engine CLI"""
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config
    ctx.obj['verbose'] = verbose

@cli.command()
@click.option('--mode', type=click.Choice(['backtest', 'paper', 'live']), default='paper')
@click.pass_context
def run(ctx, mode: str):
    """Start the trading engine"""
    pass

@cli.command()
def validate():
    """Validate configuration"""
    pass

@cli.command()
def version():
    """Show version information"""
    pass
```

#### TD-4: Nautilus Trader Strategy Base Class

**Decision:** Prepare for FTMOBaseStrategy extending Nautilus Strategy

**Rationale (from Context7 research):**
- Nautilus provides event-driven Strategy base class
- Configuration via StrategyConfig dataclass
- Built-in lifecycle hooks: `on_start`, `on_stop`, `on_bar`, `on_event`
- Access to cache, portfolio, and order factory

**Pattern Preview (actual implementation in Epic 4):**

```python
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig

class FTMOBaseStrategy(Strategy):
    """Base strategy with FTMO compliance built-in"""

    def __init__(self, config: StrategyConfig) -> None:
        super().__init__(config=config)
        # Compliance engine injection point (Epic 3)
```

---

## Implementation Plan

### Tasks

#### Story 1.1: Initialize Project Structure

- [ ] **Task 1.1.1:** Create `services/trading-engine/` directory structure per Architecture spec
- [ ] **Task 1.1.2:** Create `pyproject.toml` with Poetry configuration
- [ ] **Task 1.1.3:** Add dependencies:
  - `nautilus_trader >= 1.200.0`
  - `redis >= 5.0.0`
  - `psycopg2-binary >= 2.9.0`
  - `pyzmq >= 25.0.0`
  - `pydantic >= 2.5.0`
  - `pydantic-settings >= 2.1.0`
  - `structlog >= 24.1.0`
  - `click >= 8.1.0`
  - `pyyaml >= 6.0.0`
- [ ] **Task 1.1.4:** Add dev dependencies: `pytest`, `pytest-asyncio`, `ruff`, `mypy`
- [ ] **Task 1.1.5:** Create stub `__init__.py` files for all packages
- [ ] **Task 1.1.6:** Create `.env.example` with all environment variables
- [ ] **Task 1.1.7:** Create `README.md` for the service

#### Story 1.2: Configuration System with Validation

- [ ] **Task 1.2.1:** Create `src/config/settings.py` with Pydantic Settings models
- [ ] **Task 1.2.2:** Implement `EngineConfig` with all fields from Architecture
- [ ] **Task 1.2.3:** Implement nested configs: `RedisConfig`, `TimescaleConfig`, `ZMQConfig`
- [ ] **Task 1.2.4:** Create `src/config/loader.py` for YAML + env loading
- [ ] **Task 1.2.5:** Create `config/settings.yaml` with default values
- [ ] **Task 1.2.6:** Add validation rules (positive ports, valid URLs, etc.)
- [ ] **Task 1.2.7:** Write unit tests for configuration validation

#### Story 1.3: Structured Logging Setup

- [ ] **Task 1.3.1:** Create `src/logging.py` with structlog configuration
- [ ] **Task 1.3.2:** Implement JSON logging for production
- [ ] **Task 1.3.3:** Implement pretty logging for development (TTY detection)
- [ ] **Task 1.3.4:** Add correlation ID support via context binding
- [ ] **Task 1.3.5:** Configure log levels from config
- [ ] **Task 1.3.6:** Add service name and version to all log entries

#### Story 1.4: CLI Entry Point

- [ ] **Task 1.4.1:** Create `src/__main__.py` with Click CLI
- [ ] **Task 1.4.2:** Implement `cli` group with `--config` and `--verbose` options
- [ ] **Task 1.4.3:** Implement `run` command with `--mode` option
- [ ] **Task 1.4.4:** Implement `validate` command to check configuration
- [ ] **Task 1.4.5:** Implement `version` command showing version info
- [ ] **Task 1.4.6:** Add proper exit codes (0 success, 1 config error, 2 runtime error)

#### Story 1.5: Docker Configuration

- [ ] **Task 1.5.1:** Create multi-stage `Dockerfile`
- [ ] **Task 1.5.2:** Stage 1: Builder with Poetry and dev dependencies
- [ ] **Task 1.5.3:** Stage 2: Runtime with only production dependencies
- [ ] **Task 1.5.4:** Use `python:3.11-slim` as base image
- [ ] **Task 1.5.5:** Set proper `ENTRYPOINT` and `CMD`
- [ ] **Task 1.5.6:** Add health check
- [ ] **Task 1.5.7:** Verify image size < 500MB

---

### Acceptance Criteria

#### Story 1.1: Initialize Project Structure

- [ ] **AC 1.1.1:** Given I clone the repository, When I navigate to `services/trading-engine`, Then I see the directory structure matching Architecture spec
- [ ] **AC 1.1.2:** Given `pyproject.toml` exists, When I run `poetry install`, Then all dependencies install successfully
- [ ] **AC 1.1.3:** Given dependencies are installed, When I run `poetry run python -c "import nautilus_trader"`, Then no import errors occur

#### Story 1.2: Configuration System with Validation

- [ ] **AC 1.2.1:** Given `config/settings.yaml` exists, When the engine starts, Then configuration loads from YAML
- [ ] **AC 1.2.2:** Given environment variable `TRADING_REDIS_URL` is set, When the engine starts, Then it overrides the YAML value
- [ ] **AC 1.2.3:** Given a required field is missing, When the engine starts, Then it fails with `ConfigurationError: Missing required field 'X'`
- [ ] **AC 1.2.4:** Given an invalid value (e.g., negative port), When the engine starts, Then it fails with `ValidationError`

#### Story 1.3: Structured Logging Setup

- [ ] **AC 1.3.1:** Given the engine is running, When any event occurs, Then a JSON log entry is written with timestamp, level, event, service name
- [ ] **AC 1.3.2:** Given `LOG_LEVEL=DEBUG`, When running, Then debug logs are visible
- [ ] **AC 1.3.3:** Given running in a terminal, When `--verbose` is not set, Then pretty logs are shown (development mode)

#### Story 1.4: CLI Entry Point

- [ ] **AC 1.4.1:** Given I run `python -m src --help`, Then I see available commands: run, backtest, validate, version
- [ ] **AC 1.4.2:** Given I run `python -m src validate`, Then configuration is validated and reported
- [ ] **AC 1.4.3:** Given I run `python -m src version`, Then version information is displayed

#### Story 1.5: Docker Configuration

- [ ] **AC 1.5.1:** Given the Dockerfile exists, When I run `docker build -t trading-engine .`, Then the image builds successfully
- [ ] **AC 1.5.2:** Given the image is built, When I run `docker run trading-engine --help`, Then I see the CLI help output
- [ ] **AC 1.5.3:** Given the image is built, When I check its size, Then it is < 500MB

---

## Additional Context

### Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| nautilus_trader | >= 1.200.0 | Trading framework, strategy base class |
| redis | >= 5.0.0 | Redis client for data adapter |
| psycopg2-binary | >= 2.9.0 | PostgreSQL client for TimescaleDB |
| pyzmq | >= 25.0.0 | ZeroMQ for MT5 bridge communication |
| pydantic | >= 2.5.0 | Data validation |
| pydantic-settings | >= 2.1.0 | Configuration management |
| structlog | >= 24.1.0 | Structured logging |
| click | >= 8.1.0 | CLI framework |
| pyyaml | >= 6.0.0 | YAML configuration parsing |

### Testing Strategy

1. **Unit Tests (Story 1.2):**
   - Test configuration loading from YAML
   - Test environment variable override
   - Test validation error messages
   - Test nested configuration

2. **Integration Tests (Story 1.5):**
   - Docker build success
   - CLI commands work in container
   - Configuration loads correctly in container

### Configuration Schema

```yaml
# config/settings.yaml
engine:
  trading_mode: paper  # backtest | paper | live
  log_level: INFO

redis:
  url: redis://localhost:6379

timescale:
  url: postgres://trading:password@localhost:5432/trading

zmq:
  bridge_host: localhost
  pub_port: 5556
  sub_port: 5557

ftmo:
  challenge_type: phase1
  max_daily_loss_percent: 5.0
  max_drawdown_percent: 10.0
```

### Environment Variables

```bash
# .env.example
TRADING_ENGINE__TRADING_MODE=paper
TRADING_ENGINE__LOG_LEVEL=INFO
TRADING_REDIS__URL=redis://localhost:6379
TRADING_TIMESCALE__URL=postgres://trading:password@localhost:5432/trading
TRADING_ZMQ__BRIDGE_HOST=localhost
TRADING_ZMQ__PUB_PORT=5556
TRADING_ZMQ__SUB_PORT=5557
```

### Notes

- **Python Version:** 3.11+ is required by Nautilus Trader
- **Poetry:** Use Poetry 1.7+ for proper lock file handling
- **src Layout:** Using src layout for proper package imports (`from src.config import settings`)
- **Stub Packages:** Create empty `__init__.py` files in adapters/, risk/, strategies/, backtesting/, state/ for future epics
- **Docker Base:** Use `python:3.11-slim` to minimize image size while maintaining compatibility

---

## File Structure Summary

```
services/trading-engine/
├── src/
│   ├── __init__.py              # Package init with version
│   ├── __main__.py              # CLI entry point (Click)
│   ├── logging.py               # structlog configuration
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py          # Pydantic Settings models
│   │   └── loader.py            # YAML + env config loader
│   ├── adapters/
│   │   └── __init__.py          # Stub for Epic 2
│   ├── risk/
│   │   └── __init__.py          # Stub for Epic 3
│   ├── strategies/
│   │   └── __init__.py          # Stub for Epic 4
│   ├── backtesting/
│   │   └── __init__.py          # Stub for Epic 5
│   └── state/
│       └── __init__.py          # Stub for Epic 6
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Pytest fixtures
│   └── unit/
│       ├── __init__.py
│       └── test_config.py       # Configuration tests
├── config/
│   └── settings.yaml            # Default configuration
├── pyproject.toml               # Poetry configuration
├── Dockerfile                   # Multi-stage build
├── README.md                    # Service documentation
└── .env.example                 # Environment variables template
```

---

_Tech-Spec generated via YOLO mode workflow execution._
_Source: Epic 1 from docs/epics-trading-engine.md_
_Research: Context7 documentation for Nautilus Trader, Pydantic Settings, structlog, Click_
