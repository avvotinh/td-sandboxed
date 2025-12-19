# Trading Engine Service

NautilusTrader-based trading engine with FTMO compliance.

## Overview

This Python service provides the core trading infrastructure for the Sandboxed multi-account trading system:

- **NautilusTrader Integration** - Algorithmic trading framework
- **FTMO Rule Compliance** - Pluggable rule engine for trading constraints
- **Multi-Account Management** - Coordinate multiple trading accounts
- **Strategy Execution** - Execute trading strategies with signal routing
- **Redis/ZeroMQ Integration** - Market data and order execution adapters

## Architecture Role

The trading engine is the central orchestrator that:
1. Receives market data via Redis pub/sub
2. Executes strategies using NautilusTrader
3. Validates trades against FTMO compliance rules
4. Routes orders through ZeroMQ to MT5 bridge
5. Persists state for crash recovery

## Development

### Prerequisites

- Python 3.11+ (required by NautilusTrader)
- [uv](https://docs.astral.sh/uv/) package manager

### Install Dependencies

```bash
# Navigate to trading-engine directory
cd services/trading-engine

# Install all dependencies (including dev)
uv sync --all-extras
```

### Run Locally

```bash
# Start the engine (will wait for shutdown signal)
uv run python -m src

# Or use Ctrl+C to trigger graceful shutdown
```

### Run Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/unit/test_engine.py
```

### Lint & Format

```bash
# Check for linting issues
uv run ruff check .

# Auto-fix linting issues
uv run ruff check . --fix

# Format code
uv run ruff format .
```

## Docker

### Build Image

```bash
# Build from trading-engine directory
docker build -t trading-engine:latest .

# Or from project root using Makefile
make build-trading-engine
```

### Run Container

```bash
# Run interactively
docker run --rm trading-engine:latest

# Run with environment variables
docker run --rm \
  -e REDIS_URL=redis://localhost:6379 \
  trading-engine:latest
```

## Project Structure

```
trading-engine/
├── src/
│   ├── __init__.py          # Package init
│   ├── __main__.py          # Entry point with signal handling
│   ├── engine.py            # TradingEngine orchestrator
│   ├── accounts/            # Multi-account management (Epic 2+)
│   ├── strategies/          # Trading strategies (Epic 2+)
│   ├── adapters/            # Redis/ZeroMQ adapters (Epic 2+)
│   ├── rules/               # FTMO compliance rules (Epic 4+)
│   ├── backtesting/         # Backtest framework (future)
│   ├── state/               # State persistence (Epic 5+)
│   └── config/              # Configuration (Epic 2+)
├── tests/
│   ├── unit/                # Unit tests
│   ├── integration/         # Integration tests
│   ├── fixtures/            # Test fixtures
│   └── conftest.py          # Pytest configuration
├── Dockerfile               # Multi-stage uv-based build
├── pyproject.toml           # Project dependencies
├── uv.lock                  # Locked dependencies
└── README.md
```

## Dependencies

| Package | Purpose |
|---------|---------|
| nautilus_trader | Trading framework with backtesting |
| redis | Redis client for state/pub-sub |
| pyzmq | ZeroMQ for MT5 bridge communication |
| sqlalchemy | TimescaleDB ORM |
| pydantic | Configuration validation |
| pydantic-settings | Environment-based configuration |

## Configuration

Configuration is managed via environment variables (implementation in Epic 2+):

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `DATABASE_URL` | TimescaleDB connection | `postgresql://...` |
| `LOG_LEVEL` | Logging level | `INFO` |

## References

- [Architecture Documentation](../../docs/architecture.md)
- [NautilusTrader Docs](https://nautilustrader.io/docs/)
- [uv Documentation](https://docs.astral.sh/uv/)
