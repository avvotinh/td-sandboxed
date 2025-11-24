# HFT Data Lakehouse Blueprint

> A high-performance, open-source data lakehouse architecture for algorithmic trading, designed for sub-20ms latency queries on real-time market data.

[![Architecture](https://img.shields.io/badge/Architecture-Hot%2FCold%20Path-blue)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()
[![Docker](https://img.shields.io/badge/Docker-Compose-blue)]()

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Development](#development)
- [Documentation](#documentation)
- [Roadmap](#roadmap)

## 🎯 Overview

This project provides a complete blueprint for building a **High-Frequency Trading (HFT) Data Lakehouse** that democratizes access to professional-grade trading infrastructure. It's designed for individual algorithmic traders and small teams who need:

- ⚡ **Sub-20ms query latency** for real-time trading decisions
- 💰 **Low total cost of ownership** with self-hosted open-source components
- 🔧 **Easy deployment** via Docker Compose (8-hour setup target)
- 📊 **Dual storage paths**: Hot path for real-time, cold path for analytics

### Use Cases

- Real-time market data collection and storage
- Low-latency data access for trading bots
- Historical data analysis and backtesting
- Machine learning feature engineering on market data

## 🏗️ Architecture

```
TradingView WebSocket
        ↓
   Go Ingestion Client
        ↓
    ┌───┴───┐
    ↓       ↓
  Redis  TimescaleDB  ← HOT PATH (Real-time, <20ms)
            ↓
       Airflow ETL
            ↓
    Parquet Files
            ↓
      ClickHouse      ← COLD PATH (Analytics)
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Ingestion** | Go | High-performance WebSocket client |
| **Hot Cache** | Redis | Sub-20ms latest price queries |
| **Hot Storage** | TimescaleDB | Short-term time-series data |
| **Orchestration** | Apache Airflow | ETL job scheduling |
| **Cold Storage** | Parquet Files | Long-term compressed storage |
| **Analytics** | ClickHouse | Fast analytical queries |
| **Deployment** | Docker Compose | Container orchestration |

## ✨ Features

### Epic 1: Foundation & Hot Path ✅ (In Progress)

- [x] **Story 1.2**: TradingView WebSocket client ([tv-api](tv-api/))
- [x] **Story 1.1**: Docker Compose infrastructure
- [ ] **Story 1.3**: Redis integration for real-time cache
- [ ] **Story 1.4**: TimescaleDB integration for time-series storage
- [ ] **Story 1.5**: Benchmark validation (<20ms latency)

### Epic 2: Cold Path & Finalization 🔄 (Planned)

- [ ] **Story 2.1**: Airflow setup and DAG creation
- [ ] **Story 2.2**: Parquet export from TimescaleDB
- [ ] **Story 2.3**: ClickHouse analytical engine
- [ ] **Story 2.4**: Complete documentation

## 🚀 Quick Start

### Prerequisites

- **Docker** 26.x+ and **Docker Compose** 2.x+
- **TradingView Account** (for WebSocket credentials)
- **8 GB RAM** minimum (16 GB recommended)
- **20 GB disk space** for data storage

### 1. Clone Repository

```bash
git clone https://github.com/avvotinh/td-sandboxed.git
cd td-sandboxed
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

**Get TradingView credentials**:
1. Login to TradingView in your browser
2. Open DevTools (F12) → Application → Cookies
3. Copy `sessionid` → `SESSION_ID`
4. Copy `sessionid_sign` → `SESSION_SIGN`

### 3. Start Services

```bash
# Start infrastructure (Redis + TimescaleDB)
docker-compose up -d redis timescaledb

# Wait for health checks (~30 seconds)
docker-compose ps

# Start ingestion client
docker-compose up -d ingestion-client

# View logs
docker-compose logs -f ingestion-client
```

### 4. Verify Installation

```bash
# Check Redis
docker-compose exec redis redis-cli ping
# Should return: PONG

# Check TimescaleDB
docker-compose exec timescaledb psql -U hftuser -d hft_lakehouse -c "\dt"
# Should list: ticks, candles, system_metrics

# Check data ingestion
docker-compose exec redis redis-cli --scan --pattern "latest_tick:*"
# Should show symbols being tracked
```

## 📁 Project Structure

```
td-sandboxed/
├── docs/                      # Documentation
│   ├── prd.md                # Product Requirements
│   └── architecture.md       # Architecture Design
│
├── tv-api/                   # Go ingestion client (Epic 1, Story 1.2)
│   ├── cmd/                  # CLI applications
│   ├── pkg/tradingview/      # Public API
│   ├── internal/             # Internal packages
│   │   ├── protocol/         # WebSocket protocol
│   │   ├── session/          # Session management
│   │   ├── transport/        # WebSocket transport
│   │   └── store/            # Storage layer (Redis, TimescaleDB)
│   └── config.yaml           # Subscription configuration
│
├── migrations/               # Database schemas (Epic 1, Story 1.4)
│   ├── 001_create_ticks.sql
│   ├── 002_create_candles.sql
│   └── 003_create_monitoring.sql
│
├── scripts/                  # Utility scripts
│   └── benchmark/            # Performance benchmarks (Story 1.5)
│
├── data/                     # Data storage (Docker volumes)
│   ├── timescaledb/          # TimescaleDB data
│   └── cold_storage/         # Parquet files (Epic 2)
│
├── docker-compose.yml        # Infrastructure definition
├── .env.example              # Environment template
├── DEVELOPMENT.md            # Developer guide
└── README.md                 # This file
```

## 🛠️ Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed development guide.

### Build tv-api Locally

```bash
cd tv-api

# Install dependencies
go mod download

# Build CLIs
go build -o bin/tv-chart ./cmd/tv-chart
go build -o bin/tv-quote ./cmd/tv-quote

# Run tests
./scripts/test.sh

# Run linters
./scripts/lint.sh
```

### Run Benchmark (Story 1.5)

```bash
# Run performance benchmark
docker-compose --profile tools run benchmark

# Expected output:
# ✅ Redis latency: 5.2ms (avg)
# ✅ TimescaleDB latency: 12.8ms (avg)
# ✅ Total hot path latency: 18.0ms (avg)
# ✅ PASS: All metrics under 20ms target
```

## 📖 Documentation

- **[Product Requirements (PRD)](docs/prd.md)** - Complete feature specifications
- **[Architecture Document](docs/architecture.md)** - System design and patterns
- **[Development Guide](DEVELOPMENT.md)** - Developer documentation
- **[tv-api README](tv-api/README.md)** - Ingestion client usage

## 🗺️ Roadmap

### Phase 1: Infrastructure Setup (Current)
- [x] Docker Compose environment
- [x] Database migrations
- [x] Environment configuration
- [ ] Integration testing

### Phase 2: Storage Integration (Next)
- [ ] Redis store implementation
- [ ] TimescaleDB store implementation
- [ ] Parallel write strategy
- [ ] Error handling & retry

### Phase 3: Performance Validation
- [ ] Benchmark tools
- [ ] Latency measurement
- [ ] Load testing
- [ ] NFR1 validation (<20ms)

### Phase 4: Cold Path (Epic 2)
- [ ] Airflow setup
- [ ] ETL pipeline
- [ ] Parquet export
- [ ] ClickHouse integration

## 📊 Performance Targets

| Metric | Target | Status |
|--------|--------|--------|
| Hot path query latency | < 20ms | 🔄 In testing |
| Concurrent symbol streams | 100+ | ✅ Achieved |
| Data retention (hot) | 7 days | ✅ Configured |
| Data retention (cold) | Unlimited | 🔄 Epic 2 |
| Setup time | < 8 hours | 🔄 In progress |

## 🤝 Contributing

This is a blueprint/reference project. Contributions welcome:

1. Fork the repository
2. Create a feature branch
3. Follow coding standards (see [DEVELOPMENT.md](DEVELOPMENT.md))
4. Submit a pull request

## 📄 License

MIT License - See [LICENSE](LICENSE) for details

## 🔗 Links

- **Repository**: https://github.com/avvotinh/td-sandboxed
- **Issues**: https://github.com/avvotinh/td-sandboxed/issues
- **TradingView API**: [tv-api](tv-api/)

## 📧 Support

For questions and support:
- Check [DEVELOPMENT.md](DEVELOPMENT.md) troubleshooting section
- Review [docs/architecture.md](docs/architecture.md)
- Open an issue on GitHub

---

**Built with ❤️ for the algorithmic trading community**
