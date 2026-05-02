# Sandboxed Trading System

> Multi-account automated trading system for prop firms and personal accounts, powered by NautilusTrader with pluggable rule engine.

[![Architecture](https://img.shields.io/badge/Architecture-Microservices-blue)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()
[![Docker](https://img.shields.io/badge/Docker-Compose-blue)]()

## Overview

Event-driven automated trading system for **multi-account, multi-prop-firm trading**, architected as a **monorepo with independent microservices**. The system leverages a polyglot tech stack optimized for each service's requirements.

### Core Services

| Service | Language | Purpose |
|---------|----------|---------|
| **tv-api** | Go | TradingView WebSocket data collector |
| **mt5-bridge** | Rust | MT5 ZeroMQ bridge (latency-critical) |
| **trading-engine** | Python | NautilusTrader core, strategies, multi-account management |
| **notification** | Go | Telegram alerts and notifications |

### Key Features

- **Multi-Account Support**: Run multiple accounts simultaneously with independent strategies
- **Pluggable Rule Engine**: Built-in prop firm presets (FTMO, The5ers) + custom YAML rules
- **Polyglot Optimization**: Right language for each service's requirements
- **Service Independence**: No shared code, independent deployment
- **Risk Isolation**: Account-level risk management, failures don't cascade

## Project Structure

```
Sandboxed/
├── services/                    # Independent microservices
│   ├── tv-api/                  # TradingView data collector (Go) - COMPLETE
│   ├── mt5-bridge/              # MT5 ZeroMQ bridge (Rust)
│   ├── trading-engine/          # Trading core (Python/NautilusTrader)
│   └── notification/            # Telegram bot (Go)
├── infra/                       # Infrastructure configs
│   ├── docker/                  # Docker Compose files
│   ├── redis/                   # Redis configuration
│   ├── timescaledb/             # TimescaleDB init scripts
│   └── scripts/                 # Infrastructure scripts
├── configs/                     # Environment configs
│   ├── .env.example             # Environment template
│   ├── dev/                     # Development environment
│   └── prod/                    # Production environment
├── docs/                        # Documentation
│   ├── architecture.md          # System architecture
│   └── sprint-artifacts/        # Sprint planning and stories
├── scripts/                     # Development utilities
├── Makefile                     # Build commands
└── README.md                    # This file
```

## Quick Start

### Prerequisites

- Docker 24+ and Docker Compose 2.x
- 8GB RAM minimum
- TradingView account (for data collection)

### Setup

```bash
# Clone repository
git clone <repo-url>
cd Sandboxed

# Configure environment
cp configs/.env.example configs/dev/.env
# Edit configs/dev/.env with your credentials

# Start infrastructure
make infra-up

# View available commands
make help
```

## Documentation

For detailed documentation, see the [`docs/`](docs/) directory:

- **[Architecture](docs/architecture.md)** - Complete system architecture and design decisions
- **[Sprint Artifacts](docs/sprint-artifacts/)** - Current sprint stories and status

## Development Status

This project is under active development. See sprint artifacts for current progress.

## License

MIT License - See LICENSE for details
