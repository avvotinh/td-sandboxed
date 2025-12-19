# Story 1.7: MT5 Bridge Service Scaffold

**Epic:** 1 - Foundation & Infrastructure
**Status:** Ready for Review
**Created:** 2025-12-19

---

## User Story

As a **developer**,
I want **the mt5-bridge Rust service scaffolded**,
So that **I can develop the low-latency ZeroMQ bridge**.

---

## Context

This story implements the Rust mt5-bridge service scaffold for the Sandboxed multi-account trading system. The mt5-bridge is a **performance-critical** service responsible for:
- Receiving tick data from MT5 EAs via ZeroMQ REQ/REP
- Publishing tick data to trading-engine via ZeroMQ PUB
- Receiving order commands from trading-engine via ZeroMQ SUB
- Forwarding orders to MT5 EAs for execution
- Sub-millisecond latency messaging

### Why Rust?

Per Architecture ADR-002:
- Zero-cost abstractions for latency-critical messaging
- Memory safety without GC pauses
- Excellent ZeroMQ ecosystem
- Bridge runs 24/7 - reliability is paramount

### Current State

**Existing Files (Placeholders):**
- `services/mt5-bridge/Cargo.toml` - Package definition, empty dependencies
- `services/mt5-bridge/src/main.rs` - Placeholder with println
- `services/mt5-bridge/src/lib.rs` - Exists (empty)
- `services/mt5-bridge/Dockerfile` - Placeholder (alpine echo)
- `services/mt5-bridge/README.md` - Exists
- `services/mt5-bridge/.gitignore` - Exists

**Missing Items:**
- Real dependencies in Cargo.toml (tokio, zeromq, serde, serde_json, tracing)
- Directory structure per architecture spec
- Multi-stage Dockerfile with cargo-chef
- Basic zmq_server.rs placeholder
- Protocol definitions
- Config module
- Handler stubs
- Model definitions
- Test infrastructure

### Prerequisites

- **Story 1.1 Complete:** Project structure and monorepo setup
- **Story 1.5 Complete:** Makefile with `build-mt5-bridge` command

**Previous Story:** [1-6-trading-engine-service-scaffold.md](./1-6-trading-engine-service-scaffold.md)

---

## Acceptance Criteria

### AC1: Project Compiles Successfully
**Given** I navigate to `services/mt5-bridge`
**When** I run `cargo build`
**Then** the project compiles without errors
**And** all dependencies resolve correctly

### AC2: Directory Structure Matches Architecture
**Given** I examine the mt5-bridge directory
**When** I check the structure
**Then** it matches the architecture specification:
```
mt5-bridge/
├── src/
│   ├── main.rs
│   ├── lib.rs
│   ├── zmq_server.rs
│   ├── protocol.rs
│   ├── config.rs
│   ├── handlers/
│   │   ├── mod.rs
│   │   ├── tick_handler.rs
│   │   └── order_handler.rs
│   └── models/
│       ├── mod.rs
│       ├── tick.rs
│       └── order.rs
├── tests/
│   ├── integration_tests.rs
│   └── protocol_tests.rs
├── Dockerfile
├── Cargo.toml
└── README.md
```

### AC3: Service Starts and Listens
**Given** I run `cargo run`
**Then** the bridge starts with proper logging
**And** the service logs configured ZeroMQ ports
**And** exits gracefully on SIGTERM/SIGINT

### AC4: Docker Build Succeeds
**Given** I run `docker build .` in mt5-bridge directory
**When** the build completes
**Then** a working image is created with multi-stage cargo-chef build

### AC5: Tests Can Run
**Given** I have the test directory structure
**When** I run `cargo test`
**Then** cargo discovers tests (even if minimal initially)
**And** test infrastructure is ready for future stories

---

## Tasks

> ⚠️ **KEY CONSTRAINTS (Quick Reference)**
> 1. **This is SCAFFOLD ONLY** - Do NOT implement actual ZeroMQ socket binding (that's Story 2.3)
> 2. **Use `zeromq` crate** (zmq.rs) - NOT libzmq bindings
> 3. **Use `tracing` for logging** - NOT println! or log crate
> 4. **Do NOT modify docker-compose.yml** - that's Story 1.9
>
> See full guardrails in "Dev Agent Guardrails" section below.

### Task 1: Update Cargo.toml with Dependencies (AC1)

Update `services/mt5-bridge/Cargo.toml`:

```toml
[package]
name = "mt5-bridge"
version = "0.1.0"
edition = "2021"
description = "MT5 Bridge service for ZeroMQ communication with MetaTrader 5"
authors = ["Sandboxed Team"]
rust-version = "1.75"

[dependencies]
# Async runtime
tokio = { version = "1.40", features = ["full", "signal"] }

# ZeroMQ - native Rust implementation
zeromq = { version = "0.4", default-features = true }

# Serialization
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"

# Logging/tracing
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }

# Configuration
config = "0.14"

# Error handling
thiserror = "1.0"
anyhow = "1.0"

# Date/time handling
chrono = { version = "0.4", features = ["serde"] }

[dev-dependencies]
tokio-test = "0.4"

[profile.release]
lto = true
codegen-units = 1
strip = true
```

**Dependency Rationale:**

| Dependency | Purpose |
|------------|---------|
| tokio | Async runtime with signal handling |
| zeromq | Native Rust ZeroMQ implementation (zmq.rs) |
| serde/serde_json | JSON message serialization |
| tracing | Structured async-aware logging |
| tracing-subscriber | Log output with env-filter |
| config | Configuration file loading |
| thiserror/anyhow | Error handling patterns |
| chrono | Timestamp generation for order results |

### Task 2: Create Directory Structure (AC2)

Create the following directory structure:

```
services/mt5-bridge/
├── src/
│   ├── main.rs              # Entry point with tokio runtime
│   ├── lib.rs               # Library root, re-exports
│   ├── zmq_server.rs        # ZeroMQ server implementation
│   ├── protocol.rs          # Message protocol definitions
│   ├── config.rs            # Configuration loading
│   ├── handlers/
│   │   ├── mod.rs           # Handler module exports
│   │   ├── tick_handler.rs  # Incoming tick handling
│   │   └── order_handler.rs # Order execution handling
│   └── models/
│       ├── mod.rs           # Model module exports
│       ├── tick.rs          # Tick data model
│       └── order.rs         # Order data model
├── tests/
│   ├── integration_tests.rs # Integration test placeholder
│   └── protocol_tests.rs    # Protocol serialization tests
├── Dockerfile
├── Cargo.toml
└── README.md
```

### Task 3: Implement Entry Point with Tokio Runtime (AC3)

**src/main.rs:**

```rust
//! MT5 Bridge Service - Entry Point
//!
//! High-performance ZeroMQ bridge for MetaTrader 5 communication.
//! This service handles tick data forwarding and order execution.

use mt5_bridge::{config::Config, zmq_server::ZmqServer};
use tracing::{info, error, Level};
use tracing_subscriber::{fmt, EnvFilter};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::from_default_env()
                .add_directive(Level::INFO.into())
        )
        .json()
        .init();

    info!(
        version = env!("CARGO_PKG_VERSION"),
        "MT5 Bridge starting"
    );

    // Load configuration
    let config = Config::load()?;
    info!(
        req_port = config.zmq_req_port,
        pub_port = config.zmq_pub_port,
        sub_port = config.zmq_sub_port,
        "Configuration loaded"
    );

    // Create and run server
    let server = ZmqServer::new(config)?;

    // Handle shutdown signals (SIGINT and SIGTERM)
    let shutdown = async {
        let ctrl_c = tokio::signal::ctrl_c();

        #[cfg(unix)]
        let terminate = async {
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("Failed to install SIGTERM handler")
                .recv()
                .await;
        };

        #[cfg(not(unix))]
        let terminate = std::future::pending::<()>();

        tokio::select! {
            _ = ctrl_c => info!("SIGINT received"),
            _ = terminate => info!("SIGTERM received"),
        }
        info!("Shutdown signal received");
    };

    tokio::select! {
        result = server.run() => {
            if let Err(e) = result {
                error!(error = %e, "Server error");
                return Err(e);
            }
        }
        _ = shutdown => {
            info!("Initiating graceful shutdown");
        }
    }

    info!("MT5 Bridge stopped");
    Ok(())
}
```

### Task 4: Implement Core Modules

**src/lib.rs:**

```rust
//! MT5 Bridge Library
//!
//! Provides ZeroMQ bridge functionality for MT5 communication.

pub mod config;
pub mod error;
pub mod handlers;
pub mod models;
pub mod protocol;
pub mod zmq_server;

pub use config::Config;
pub use error::BridgeError;
pub use zmq_server::ZmqServer;
```

**src/config.rs:**

```rust
//! Configuration module for MT5 Bridge.

use serde::Deserialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("Environment variable {0} not set")]
    MissingEnv(String),
    #[error("Invalid port number: {0}")]
    InvalidPort(String),
}

/// MT5 Bridge configuration.
///
/// NOTE: This scaffold supports single-port configuration.
/// For multi-account support (Epic 2+), this will be extended to support
/// multiple port ranges per MT5 instance (e.g., 5555/5565/5575 for FTMO/5ers/Personal).
/// See Architecture docs: Multi-Account MT5 Deployment (Option 1).
#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    /// ZeroMQ REQ/REP port for MT5 EA commands (default: 5555)
    pub zmq_req_port: u16,
    /// ZeroMQ PUB port for tick data (default: 5556)
    pub zmq_pub_port: u16,
    /// ZeroMQ SUB port for order commands (default: 5557)
    pub zmq_sub_port: u16,
    /// Bind address (default: 0.0.0.0)
    pub bind_address: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            zmq_req_port: 5555,
            zmq_pub_port: 5556,
            zmq_sub_port: 5557,
            bind_address: "0.0.0.0".to_string(),
        }
    }
}

impl Config {
    /// Load configuration from environment variables.
    pub fn load() -> anyhow::Result<Self> {
        let config = Self {
            zmq_req_port: std::env::var("ZMQ_REQ_PORT")
                .unwrap_or_else(|_| "5555".to_string())
                .parse()?,
            zmq_pub_port: std::env::var("ZMQ_PUB_PORT")
                .unwrap_or_else(|_| "5556".to_string())
                .parse()?,
            zmq_sub_port: std::env::var("ZMQ_SUB_PORT")
                .unwrap_or_else(|_| "5557".to_string())
                .parse()?,
            bind_address: std::env::var("BIND_ADDRESS")
                .unwrap_or_else(|_| "0.0.0.0".to_string()),
        };
        Ok(config)
    }

    /// Get REQ/REP endpoint string.
    pub fn req_endpoint(&self) -> String {
        format!("tcp://{}:{}", self.bind_address, self.zmq_req_port)
    }

    /// Get PUB endpoint string.
    pub fn pub_endpoint(&self) -> String {
        format!("tcp://{}:{}", self.bind_address, self.zmq_pub_port)
    }

    /// Get SUB endpoint string.
    pub fn sub_endpoint(&self) -> String {
        format!("tcp://{}:{}", self.bind_address, self.zmq_sub_port)
    }
}
```

**src/error.rs:**

```rust
//! Bridge error types.
//!
//! Defines error types for the MT5 Bridge service.
//! Full error handling implementation in Story 2.3.

use thiserror::Error;

/// Bridge-level errors.
///
/// These errors represent failures in bridge operations.
/// Used for error propagation and logging.
#[derive(Debug, Error)]
pub enum BridgeError {
    /// ZeroMQ connection was lost
    #[error("Connection lost: {0}")]
    ConnectionLost(String),

    /// Message timeout occurred
    #[error("Message timeout after {0}ms")]
    MessageTimeout(u64),

    /// Invalid message received
    #[error("Invalid message: {0}")]
    InvalidMessage(String),

    /// Account disconnected from MT5
    #[error("Account {0} disconnected")]
    AccountDisconnected(String),

    /// Configuration error
    #[error("Configuration error: {0}")]
    Config(#[from] crate::config::ConfigError),

    /// Serialization error
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}

/// Result type alias for bridge operations.
pub type BridgeResult<T> = Result<T, BridgeError>;
```

**src/protocol.rs:**

```rust
//! Message protocol definitions for MT5 Bridge.
//!
//! Defines the JSON message format for communication between
//! MT5 EAs and the trading engine.

use serde::{Deserialize, Serialize};

/// Message type identifier.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum MessageType {
    Tick,
    Order,
    OrderResult,
    Heartbeat,
    Ack,
    Error,
}

/// Incoming message from MT5 EA or trading engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IncomingMessage {
    #[serde(rename = "type")]
    pub msg_type: MessageType,
    #[serde(flatten)]
    pub payload: serde_json::Value,
}

/// Acknowledgment response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AckResponse {
    #[serde(rename = "type")]
    pub msg_type: MessageType,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

impl AckResponse {
    pub fn ok() -> Self {
        Self {
            msg_type: MessageType::Ack,
            status: "ok".to_string(),
            message: None,
        }
    }

    pub fn error(message: impl Into<String>) -> Self {
        Self {
            msg_type: MessageType::Error,
            status: "error".to_string(),
            message: Some(message.into()),
        }
    }
}
```

**src/models/mod.rs:**

```rust
//! Data models for MT5 Bridge.

pub mod order;
pub mod tick;

pub use order::{Order, OrderResult, OrderSide, OrderStatus};
pub use tick::Tick;
```

**src/models/tick.rs:**

```rust
//! Tick data model.
//!
//! NOTE: This model includes `account_id` which extends the base architecture
//! message protocol to support multi-account routing. The architecture shows
//! tick messages without account_id, but this enhancement is required for
//! the multi-account trading system to route ticks to the correct account context.

use serde::{Deserialize, Serialize};

/// Market tick data from MT5.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tick {
    /// Account identifier for multi-account support
    pub account_id: String,
    /// Trading symbol (e.g., "XAUUSD")
    pub symbol: String,
    /// Bid price
    pub bid: f64,
    /// Ask price
    pub ask: f64,
    /// Timestamp in ISO 8601 format
    pub timestamp: String,
}

impl Tick {
    /// Calculate spread in price units.
    pub fn spread(&self) -> f64 {
        self.ask - self.bid
    }

    /// Get PUB topic for this tick.
    pub fn topic(&self) -> String {
        format!("tick:{}", self.symbol)
    }
}
```

**src/models/order.rs:**

```rust
//! Order data models.

use serde::{Deserialize, Serialize};

/// Order side (direction).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "UPPERCASE")]
pub enum OrderSide {
    Buy,
    Sell,
}

/// Order command to MT5.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    /// Order action type
    pub action: OrderSide,
    /// Trading symbol
    pub symbol: String,
    /// Volume in lots
    pub volume: f64,
    /// Requested price
    pub price: f64,
    /// Stop loss price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sl: Option<f64>,
    /// Take profit price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tp: Option<f64>,
    /// Unique order identifier
    pub order_id: String,
    /// Account identifier
    pub account_id: String,
}

/// Order execution status.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum OrderStatus {
    Filled,
    PartiallyFilled,
    Rejected,
    Error,
}

/// Order execution result from MT5.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderResult {
    /// Original order ID
    pub order_id: String,
    /// Execution status
    pub status: OrderStatus,
    /// Actual fill price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fill_price: Option<f64>,
    /// Slippage from requested price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub slippage: Option<f64>,
    /// Execution timestamp
    pub timestamp: String,
    /// Error message if failed
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}
```

**src/handlers/mod.rs:**

```rust
//! Message handlers for MT5 Bridge.

pub mod order_handler;
pub mod tick_handler;

pub use order_handler::OrderHandler;
pub use tick_handler::TickHandler;
```

**src/handlers/tick_handler.rs:**

```rust
//! Tick message handler.

use crate::models::Tick;
use crate::protocol::AckResponse;
use tracing::{debug, instrument};

/// Handler for incoming tick data from MT5.
pub struct TickHandler;

impl TickHandler {
    pub fn new() -> Self {
        Self
    }

    /// Process incoming tick and prepare for publishing.
    #[instrument(skip(self), fields(symbol = %tick.symbol))]
    pub fn handle(&self, tick: &Tick) -> AckResponse {
        debug!(
            account_id = %tick.account_id,
            bid = tick.bid,
            ask = tick.ask,
            spread = tick.spread(),
            "Tick received"
        );

        // In Story 2.3, this will publish to PUB socket
        // For now, just acknowledge receipt
        AckResponse::ok()
    }
}

impl Default for TickHandler {
    fn default() -> Self {
        Self::new()
    }
}
```

**src/handlers/order_handler.rs:**

```rust
//! Order message handler.

use crate::models::{Order, OrderResult};
use tracing::{info, instrument};

/// Handler for order commands from trading engine.
pub struct OrderHandler;

impl OrderHandler {
    pub fn new() -> Self {
        Self
    }

    /// Process order command and forward to MT5.
    #[instrument(skip(self), fields(order_id = %order.order_id))]
    pub async fn handle(&self, order: &Order) -> OrderResult {
        info!(
            account_id = %order.account_id,
            symbol = %order.symbol,
            action = ?order.action,
            volume = order.volume,
            "Order received"
        );

        // In Story 2.3, this will forward to MT5 EA via REQ socket
        // For now, return placeholder result
        OrderResult {
            order_id: order.order_id.clone(),
            status: crate::models::OrderStatus::Rejected,
            fill_price: None,
            slippage: None,
            timestamp: chrono::Utc::now().to_rfc3339(),
            error: Some("Bridge not connected to MT5 (scaffold only)".to_string()),
        }
    }
}

impl Default for OrderHandler {
    fn default() -> Self {
        Self::new()
    }
}
```

**src/zmq_server.rs:**

```rust
//! ZeroMQ server implementation.
//!
//! This is a scaffold placeholder. Full ZeroMQ socket implementation
//! will be completed in Story 2.3.

use crate::config::Config;
use crate::handlers::{OrderHandler, TickHandler};
use tracing::{info, warn};

/// ZeroMQ server for MT5 bridge communication.
pub struct ZmqServer {
    config: Config,
    tick_handler: TickHandler,
    order_handler: OrderHandler,
}

impl ZmqServer {
    /// Create a new ZeroMQ server with the given configuration.
    pub fn new(config: Config) -> anyhow::Result<Self> {
        Ok(Self {
            config,
            tick_handler: TickHandler::new(),
            order_handler: OrderHandler::new(),
        })
    }

    /// Run the ZeroMQ server.
    ///
    /// This scaffold demonstrates the async structure that will be
    /// used for the actual implementation in Story 2.3.
    pub async fn run(&self) -> anyhow::Result<()> {
        info!(
            req_endpoint = %self.config.req_endpoint(),
            pub_endpoint = %self.config.pub_endpoint(),
            sub_endpoint = %self.config.sub_endpoint(),
            "ZeroMQ server starting (scaffold mode)"
        );

        // Scaffold: Log port availability
        // In Story 2.3, this will bind actual ZeroMQ sockets
        warn!("ZeroMQ sockets not bound - scaffold only");
        warn!("Full implementation in Story 2.3: MT5 Bridge ZeroMQ Server");

        // Keep running until shutdown signal
        // In production, this will be the main event loop
        loop {
            tokio::time::sleep(tokio::time::Duration::from_secs(60)).await;
            info!("MT5 Bridge heartbeat (scaffold mode)");
        }
    }

    /// Get reference to tick handler.
    pub fn tick_handler(&self) -> &TickHandler {
        &self.tick_handler
    }

    /// Get reference to order handler.
    pub fn order_handler(&self) -> &OrderHandler {
        &self.order_handler
    }
}
```

### Task 5: Create Multi-Stage Dockerfile (AC4)

**Dockerfile:**

```dockerfile
# Stage 1: Build dependencies with cargo-chef
FROM rust:1.75-slim AS chef
RUN cargo install cargo-chef
WORKDIR /app

# Stage 2: Plan dependencies
FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

# Stage 3: Build dependencies (cached layer)
FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# Build application
COPY . .
RUN cargo build --release

# Stage 4: Runtime
FROM debian:bookworm-slim AS runtime
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy binary from builder
COPY --from=builder /app/target/release/mt5-bridge /app/mt5-bridge

# Set environment variables
ENV RUST_LOG=info
ENV ZMQ_REQ_PORT=5555
ENV ZMQ_PUB_PORT=5556
ENV ZMQ_SUB_PORT=5557

# Expose ZeroMQ ports
EXPOSE 5555 5556 5557

# Health check (scaffold: binary exists)
# NOTE: Story 2.3 should implement proper healthcheck that verifies
# ZeroMQ sockets are bound and responding (e.g., ZMQ REQ/REP ping)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD test -f /app/mt5-bridge || exit 1

# Run the application
CMD ["/app/mt5-bridge"]
```

### Task 6: Create Test Infrastructure (AC5)

**tests/integration_tests.rs:**

```rust
//! Integration tests for MT5 Bridge.

use mt5_bridge::config::Config;
use mt5_bridge::models::{Order, OrderSide, Tick};
use mt5_bridge::protocol::{AckResponse, MessageType};

#[test]
fn test_config_defaults() {
    let config = Config::default();
    assert_eq!(config.zmq_req_port, 5555);
    assert_eq!(config.zmq_pub_port, 5556);
    assert_eq!(config.zmq_sub_port, 5557);
}

#[test]
fn test_config_endpoints() {
    let config = Config::default();
    assert_eq!(config.req_endpoint(), "tcp://0.0.0.0:5555");
    assert_eq!(config.pub_endpoint(), "tcp://0.0.0.0:5556");
    assert_eq!(config.sub_endpoint(), "tcp://0.0.0.0:5557");
}

#[test]
fn test_tick_spread_calculation() {
    let tick = Tick {
        account_id: "test-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };
    assert!((tick.spread() - 0.20).abs() < 0.001);
}

#[test]
fn test_tick_topic() {
    let tick = Tick {
        account_id: "test-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };
    assert_eq!(tick.topic(), "tick:XAUUSD");
}

#[test]
fn test_order_serialization() {
    let order = Order {
        action: OrderSide::Buy,
        symbol: "XAUUSD".to_string(),
        volume: 0.1,
        price: 1850.45,
        sl: Some(1845.00),
        tp: Some(1860.00),
        order_id: "ORDER-123".to_string(),
        account_id: "ftmo-gold-001".to_string(),
    };

    let json = serde_json::to_string(&order).unwrap();
    assert!(json.contains("XAUUSD"));
    assert!(json.contains("ORDER-123"));
}

#[test]
fn test_ack_response_ok() {
    let ack = AckResponse::ok();
    assert_eq!(ack.msg_type, MessageType::Ack);
    assert_eq!(ack.status, "ok");
    assert!(ack.message.is_none());
}

#[test]
fn test_ack_response_error() {
    let ack = AckResponse::error("Test error");
    assert_eq!(ack.msg_type, MessageType::Error);
    assert_eq!(ack.status, "error");
    assert_eq!(ack.message, Some("Test error".to_string()));
}
```

**tests/protocol_tests.rs:**

```rust
//! Protocol serialization and deserialization tests.

use mt5_bridge::models::{Order, OrderResult, OrderSide, OrderStatus, Tick};
use mt5_bridge::protocol::{IncomingMessage, MessageType};

#[test]
fn test_tick_serialization_roundtrip() {
    let tick = Tick {
        account_id: "ftmo-gold-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };

    let json = serde_json::to_string(&tick).unwrap();
    let deserialized: Tick = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.account_id, tick.account_id);
    assert_eq!(deserialized.symbol, tick.symbol);
    assert!((deserialized.bid - tick.bid).abs() < 0.001);
}

#[test]
fn test_order_serialization_roundtrip() {
    let order = Order {
        action: OrderSide::Buy,
        symbol: "XAUUSD".to_string(),
        volume: 0.1,
        price: 1850.45,
        sl: Some(1845.00),
        tp: Some(1860.00),
        order_id: "ORDER-123".to_string(),
        account_id: "ftmo-gold-001".to_string(),
    };

    let json = serde_json::to_string(&order).unwrap();
    let deserialized: Order = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.order_id, order.order_id);
    assert_eq!(deserialized.action, OrderSide::Buy);
}

#[test]
fn test_message_type_serialization() {
    let msg_type = MessageType::Tick;
    let json = serde_json::to_string(&msg_type).unwrap();
    assert_eq!(json, "\"tick\"");

    let msg_type = MessageType::Order;
    let json = serde_json::to_string(&msg_type).unwrap();
    assert_eq!(json, "\"order\"");
}

#[test]
fn test_order_result_with_error() {
    let result = OrderResult {
        order_id: "ORDER-123".to_string(),
        status: OrderStatus::Rejected,
        fill_price: None,
        slippage: None,
        timestamp: "2025-12-19T14:32:15.456Z".to_string(),
        error: Some("Insufficient margin".to_string()),
    };

    let json = serde_json::to_string(&result).unwrap();
    assert!(json.contains("rejected"));
    assert!(json.contains("Insufficient margin"));
}
```

### Task 7: Update README.md

Update `services/mt5-bridge/README.md` with comprehensive documentation.

### Task 8: Verify All Commands Work

- [x] Test `cargo build` compiles successfully ✅
- [x] Test `cargo run` starts and logs ports ✅
- [x] Test `cargo test` runs tests (14 tests pass) ✅
- [x] Test `docker build .` builds image ✅
- [x] Test `make build-mt5-bridge` from project root (target exists, requires local Rust)

---

## Technical Specifications

### Rust Version and Edition

- **Rust Version:** 1.75+ (specified in Cargo.toml rust-version)
- **Edition:** 2021

### ZeroMQ Port Configuration

Per Architecture specification:

| Port | Pattern | Purpose |
|------|---------|---------|
| 5555 | REQ/REP | MT5 EA commands and responses |
| 5556 | PUB | Tick data to trading-engine |
| 5557 | SUB | Order commands from trading-engine |

### Message Protocol (JSON)

**Tick message from MT5:**
```json
{
  "type": "tick",
  "account_id": "ftmo-gold-001",
  "symbol": "XAUUSD",
  "bid": 1850.25,
  "ask": 1850.45,
  "timestamp": "2025-12-03T14:32:15.123Z"
}
```

**Order command to MT5:**
```json
{
  "type": "order",
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

**Order response from MT5:**
```json
{
  "type": "order_result",
  "order_id": "ORDER-123",
  "status": "filled",
  "fill_price": 1850.47,
  "slippage": 0.02,
  "timestamp": "2025-12-03T14:32:15.456Z"
}
```

### Tokio Runtime (Context7 Research - 2025)

Based on latest Tokio documentation:

**Signal Handling Pattern:**
```rust
tokio::select! {
    result = server.run() => { /* handle result */ }
    _ = tokio::signal::ctrl_c() => { /* graceful shutdown */ }
}
```

**Key Features:**
- `tokio::signal::ctrl_c()` for async Ctrl-C handling
- Unix signals via `tokio::signal::unix::signal(SignalKind::...)`
- `#[tokio::main]` macro for runtime initialization
- `tokio::select!` for concurrent operation handling

### Tracing (Context7 Research - 2025)

Based on latest tracing documentation:

**Structured Logging Pattern:**
```rust
use tracing::{info, debug, instrument};

#[instrument(skip(self), fields(order_id = %order.order_id))]
pub async fn handle(&self, order: &Order) -> OrderResult {
    info!(symbol = %order.symbol, "Processing order");
    // ...
}
```

**Environment-Based Filtering:**
```rust
tracing_subscriber::fmt()
    .with_env_filter(EnvFilter::from_default_env())
    .json()
    .init();
```

Set `RUST_LOG=mt5_bridge=debug` for debug logging.

### Serde JSON (Context7 Research - 2025)

**Derive Macros:**
```rust
use serde::{Serialize, Deserialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct MyStruct {
    pub field: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub optional_field: Option<i32>,
}
```

### ZeroMQ (zmq.rs)

The `zeromq` crate is a native Rust implementation. Per Context7:

**Cargo.toml:**
```toml
zeromq = { version = "0.4", default-features = true }
```

**Note:** Full socket binding implementation in Story 2.3.

---

## Architecture Compliance

This story implements:
- **Architecture - MT5 Bridge Structure:** Directory layout from docs/architecture.md
- **Architecture - Polyglot Stack:** Rust 1.75+ for latency-critical messaging
- **Architecture - Docker Compose:** Multi-stage Dockerfile with cargo-chef

**Referenced Sections:**
- [Source: docs/architecture.md#mt5-bridge-service-rust]
- [Source: docs/architecture.md#monorepo-structure]
- [Source: docs/architecture.md#zeromq-patterns]
- [Source: docs/architecture.md#message-protocol]

---

## Previous Story Intelligence

### From Story 1.6 (Completed)

**Key Learnings:**
- Scaffold should demonstrate async patterns for future development
- Platform-safe signal handling (SIGTERM/SIGINT)
- Multi-stage Docker builds with dependency caching
- Module docstrings document future implementation scope
- Test infrastructure more important than coverage at scaffold stage

**Code Patterns Established:**
- Docker Compose uses `docker compose` (v2 syntax)
- Environment variables with `${VAR:-default}` pattern
- Container health checks for all services
- Structured logging with JSON output

**Files Created in 1.6:**
- `services/trading-engine/` - Complete Python scaffold
- Async entry point with signal handling pattern

### Git Recent Commits

```
147a22c Implement spec 1 story 1.6
d6e55b7 Implement spec 1 story 1.5
7c5dad4 Implement spec 1 story 1.4
82328cb Implement spec 1 story 1.3
e6ed42f Implement epec 1 story 1.1 1.2
```

---

## Dev Agent Guardrails

### MUST DO:

1. **Use Rust 1.75+** as specified in architecture (edition 2021)
2. **Use zeromq crate** (zmq.rs) - native Rust implementation
3. **Use tokio for async runtime** with `#[tokio::main]`
4. **Use tracing for logging** - async-aware, structured logging
5. **Follow architecture directory structure** exactly as specified
6. **Implement graceful shutdown** with tokio::signal
7. **Use serde derive** for JSON serialization
8. **Multi-stage Dockerfile** with cargo-chef for dependency caching
9. **Include account_id** in all messages for multi-account support
10. **JSON message format** per protocol specification

### DO NOT:

1. **Do NOT implement actual ZeroMQ socket binding** - this is scaffold only (Story 2.3)
2. **Do NOT add MT5 connection logic** - comes in Story 2.3
3. **Do NOT use libzmq bindings** - use native Rust zeromq crate
4. **Do NOT skip graceful shutdown** - critical for production reliability
5. **Do NOT add complex business logic** - handlers are stubs
6. **Do NOT modify docker-compose.yml** - that's Story 1.9
7. **Do NOT use println! for logging** - use tracing macros

### File Modifications:

**Files to Modify:**
- `services/mt5-bridge/Cargo.toml` - Add dependencies
- `services/mt5-bridge/src/main.rs` - Implement entry point
- `services/mt5-bridge/src/lib.rs` - Module exports
- `services/mt5-bridge/Dockerfile` - Multi-stage with cargo-chef
- `services/mt5-bridge/README.md` - Update documentation

**Files to Create:**
- `services/mt5-bridge/src/zmq_server.rs` - Server scaffold
- `services/mt5-bridge/src/protocol.rs` - Message protocol
- `services/mt5-bridge/src/config.rs` - Configuration
- `services/mt5-bridge/src/error.rs` - Bridge error types
- `services/mt5-bridge/src/handlers/mod.rs`
- `services/mt5-bridge/src/handlers/tick_handler.rs`
- `services/mt5-bridge/src/handlers/order_handler.rs`
- `services/mt5-bridge/src/models/mod.rs`
- `services/mt5-bridge/src/models/tick.rs`
- `services/mt5-bridge/src/models/order.rs`
- `services/mt5-bridge/tests/integration_tests.rs`
- `services/mt5-bridge/tests/protocol_tests.rs` - Protocol serialization tests

**Files NOT to Modify:**
- `infra/docker/docker-compose.yml` - Updated in Story 1.9
- `Makefile` - Already has mt5-bridge targets
- Any other service directories

---

## Testing Verification

### Manual Test Steps

```bash
# 1. Navigate to mt5-bridge
cd /home/hopdev/Dev/Sandboxed/services/mt5-bridge

# 2. Build the project
cargo build
# Expected: Compiles without errors

# 3. Run tests
cargo test
# Expected: All tests pass

# 4. Run the service
cargo run
# Expected: Logs "MT5 Bridge starting", shows ports, runs heartbeat loop
# Press Ctrl-C to exit gracefully

# 5. Build Docker image
docker build -t mt5-bridge:test .
# Expected: Multi-stage build completes successfully

# 6. Run Docker container
docker run --rm mt5-bridge:test
# Expected: Same output as local run

# 7. From project root
cd /home/hopdev/Dev/Sandboxed
make build-mt5-bridge
# Expected: cargo build --release succeeds
```

### Verification Checklist

- [x] `cargo build` compiles without errors
- [x] All dependencies in Cargo.toml resolve correctly
- [x] Directory structure matches architecture spec
- [x] `cargo run` starts and logs configured ports
- [x] Service exits gracefully on Ctrl-C (SIGTERM/SIGINT handled)
- [x] `cargo test` discovers and runs tests (14 tests pass)
- [x] Docker build creates working image (mt5-bridge:test)
- [x] `make build-mt5-bridge` target exists in Makefile

---

## Dependencies

- **Prerequisites:** Story 1.1 (Project Structure) - DONE
- **Blocks:**
  - Story 1.9 (Full Stack Docker Compose) - needs service to add
  - Story 2.3 (MT5 Bridge ZeroMQ Server) - needs scaffold
  - All Epic 2+ stories using MT5 communication

---

## Definition of Done

- [x] Cargo.toml has all required dependencies
- [x] `cargo build` compiles without errors
- [x] Directory structure matches architecture specification
- [x] Entry point with tokio runtime and signal handling
- [x] Protocol, config, handlers, and models modules created
- [x] Dockerfile uses multi-stage build (simplified due to cargo-chef compatibility)
- [x] Docker build creates working image
- [x] Test infrastructure ready (integration tests)
- [x] `cargo test` discovers and runs tests
- [x] README.md updated with service documentation
- [x] All verification tests pass
- [x] Story status updated to `review` in sprint-status.yaml

---

## References

- [Architecture - MT5 Bridge Service](../architecture.md#mt5-bridge-service-rust)
- [Architecture - Monorepo Structure](../architecture.md#monorepo-structure)
- [Architecture - ZeroMQ Patterns](../architecture.md#zeromq-patterns)
- [Architecture - Message Protocol](../architecture.md#message-protocol)
- [Story 1.6 - Trading Engine Scaffold](./1-6-trading-engine-service-scaffold.md)
- [Tokio Documentation](https://tokio.rs/)
- [Tracing Documentation](https://tracing.rs/)
- [zmq.rs GitHub](https://github.com/zeromq/zmq.rs)

---

## Dev Agent Record

### Context Reference

- Epic 1 Stories: `docs/epics.md` (Story 1.7 section)
- Architecture: `docs/architecture.md` (MT5 Bridge, Monorepo, ZeroMQ sections)
- Previous Story: `docs/sprint-artifacts/1-6-trading-engine-service-scaffold.md`
- Tokio docs via Context7 MCP
- Tracing docs via Context7 MCP
- Serde docs via Context7 MCP

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Build verification via Docker: `docker run --rm -v ... rust:slim cargo build`
- Test verification via Docker: `docker run --rm -v ... rust:slim cargo test` (14 tests pass)
- Service start verification: JSON logs show ports 5555/5556/5557 and graceful shutdown
- Docker image build: `docker build -t mt5-bridge:test .` succeeded

### Completion Notes List

- All 8 tasks completed successfully
- Updated Rust version to 1.83 due to dependency requirements (pest crate requires 1.83+)
- Simplified Dockerfile (removed cargo-chef due to compatibility issues with current crate ecosystem, still uses multi-stage build with dependency caching)
- All 14 tests pass (7 integration + 7 protocol tests)
- Service demonstrates proper async patterns with tokio runtime
- Graceful shutdown handles both SIGTERM and SIGINT
- JSON structured logging via tracing crate

### File List

**Modified:**
- `services/mt5-bridge/Cargo.toml` - Added dependencies (tokio, zeromq, serde, tracing, etc.)
- `services/mt5-bridge/src/main.rs` - Implemented tokio entry point with signal handling
- `services/mt5-bridge/src/lib.rs` - Module exports
- `services/mt5-bridge/Dockerfile` - Multi-stage build
- `services/mt5-bridge/README.md` - Comprehensive documentation

**Created:**
- `services/mt5-bridge/Cargo.lock` - Dependency lock file (auto-generated)
- `services/mt5-bridge/src/config.rs` - Configuration from environment
- `services/mt5-bridge/src/error.rs` - BridgeError enum
- `services/mt5-bridge/src/protocol.rs` - Message protocol definitions
- `services/mt5-bridge/src/zmq_server.rs` - ZMQ server scaffold
- `services/mt5-bridge/src/handlers/mod.rs` - Handler module exports
- `services/mt5-bridge/src/handlers/tick_handler.rs` - Tick processing
- `services/mt5-bridge/src/handlers/order_handler.rs` - Order processing
- `services/mt5-bridge/src/models/mod.rs` - Model exports
- `services/mt5-bridge/src/models/tick.rs` - Tick data model
- `services/mt5-bridge/src/models/order.rs` - Order data model
- `services/mt5-bridge/tests/integration_tests.rs` - 11 integration tests (including handler tests)
- `services/mt5-bridge/tests/protocol_tests.rs` - 7 protocol serialization tests

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-19 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-19 | Tokio, Tracing, Serde, ZeroMQ documentation researched via Context7 MCP |
| 2025-12-19 | **Validation improvements applied:** (1) Added `chrono` to Cargo.toml Task 1 dependencies; (2) Added `account_id` architecture enhancement note in tick.rs; (3) Added `tests/protocol_tests.rs` with serialization tests; (4) Added `src/error.rs` with BridgeError enum per architecture; (5) Added SIGTERM signal handling to main.rs; (6) Added multi-port support note in config.rs; (7) Added Dockerfile healthcheck note for Story 2.3; (8) Added Quick Reference constraints box at top of Tasks section; (9) Updated file lists |
| 2025-12-19 | **Implementation completed** by Claude Opus 4.5. All tasks completed, 14 tests passing, Docker image built successfully. Updated Rust version to 1.83 due to dependency requirements. |
| 2025-12-19 | **Code review fixes applied:** (1) Removed unused `config` crate dependency; (2) Fixed README cargo-chef claim to match actual Dockerfile; (3) Added 4 handler tests (TickHandler, OrderHandler async tests); (4) Added Cargo.lock to File List. Total: 18 tests now passing (11 integration + 7 protocol). |

---

## Notes

- This story is **scaffold only** - no actual ZeroMQ socket binding
- Full ZeroMQ implementation comes in Story 2.3
- The scaffold demonstrates async patterns and message protocol
- Focus on clean, extensible structure that Story 2.3+ can build upon
- Test infrastructure is more important than test coverage at this stage
- **Dockerfile** uses simplified multi-stage build (cargo-chef removed due to dependency compatibility issues with 2024 edition crates)
- **Architecture deviation:** Rust version 1.83 required (architecture spec says 1.75+). Consider updating `docs/architecture.md:683` to reflect this.
