# MT5 Bridge Service

High-performance ZeroMQ bridge service for MetaTrader 5 communication.

## Overview

This Rust service provides:
- ZeroMQ REQ/REP server for MT5 EA commands
- ZeroMQ PUB socket for tick data distribution
- ZeroMQ SUB socket for order commands from trading-engine
- Sub-millisecond latency messaging
- Graceful shutdown handling (SIGTERM/SIGINT)

## Current Status

**Scaffold** - Service structure and modules implemented. Full ZeroMQ socket binding in Story 2.3.

## Directory Structure

```
mt5-bridge/
├── src/
│   ├── main.rs              # Entry point with tokio runtime
│   ├── lib.rs               # Library root, re-exports
│   ├── zmq_server.rs        # ZeroMQ server implementation
│   ├── protocol.rs          # Message protocol definitions
│   ├── config.rs            # Configuration loading
│   ├── error.rs             # Error types
│   ├── handlers/
│   │   ├── mod.rs           # Handler module exports
│   │   ├── tick_handler.rs  # Incoming tick handling
│   │   └── order_handler.rs # Order execution handling
│   └── models/
│       ├── mod.rs           # Model module exports
│       ├── tick.rs          # Tick data model
│       └── order.rs         # Order data model
├── tests/
│   ├── integration_tests.rs # Integration tests
│   └── protocol_tests.rs    # Protocol serialization tests
├── Dockerfile               # Multi-stage build with dependency caching
├── Cargo.toml
└── README.md
```

## Development

```bash
# Build
cargo build

# Run (starts in scaffold mode)
cargo run

# Run tests
cargo test

# Build release
cargo build --release

# Build Docker image
docker build -t mt5-bridge:latest .
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ZMQ_REQ_PORT` | 5555 | REQ/REP port for MT5 EA commands |
| `ZMQ_PUB_PORT` | 5556 | PUB port for tick data |
| `ZMQ_SUB_PORT` | 5557 | SUB port for order commands |
| `BIND_ADDRESS` | 0.0.0.0 | Address to bind sockets |
| `RUST_LOG` | info | Logging level |

## Message Protocol

### Tick Message (from MT5 EA)

```json
{
  "account_id": "ftmo-gold-001",
  "symbol": "XAUUSD",
  "bid": 1850.25,
  "ask": 1850.45,
  "timestamp": "2025-12-19T14:32:15.123Z"
}
```

### Order Command (to MT5 EA)

```json
{
  "action": "BUY",
  "symbol": "XAUUSD",
  "volume": 0.1,
  "price": 1850.45,
  "sl": 1845.00,
  "tp": 1860.00,
  "order_id": "ORDER-123",
  "account_id": "ftmo-gold-001"
}
```

### Order Result (from MT5 EA)

```json
{
  "order_id": "ORDER-123",
  "status": "filled",
  "fill_price": 1850.47,
  "slippage": 0.02,
  "timestamp": "2025-12-19T14:32:15.456Z"
}
```

## ZeroMQ Patterns

| Port | Pattern | Direction | Purpose |
|------|---------|-----------|---------|
| 5555 | REQ/REP | MT5 EA → Bridge | Tick data and heartbeats |
| 5556 | PUB | Bridge → Trading Engine | Tick distribution |
| 5557 | SUB | Trading Engine → Bridge | Order commands |

## Architecture

See [Architecture Documentation](../../docs/architecture.md) for details.

## Future Stories

- **Story 2.3**: Full ZeroMQ socket binding and message handling
- **Story 2.4**: Trading engine ZeroMQ adapter integration
