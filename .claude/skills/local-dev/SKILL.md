---
name: local-dev
description: Local development knowledge — how to run, debug, and troubleshoot the Sandboxed trading system
---

# Local Development Guide

## Architecture Overview
Polyglot monorepo with 4 services communicating via ZeroMQ (order flow) and Redis pub/sub (events):
- **trading-engine** (Python 3.11+) — NautilusTrader, rule engine, risk management
- **mt5-bridge** (Rust) — MetaTrader 5 ZeroMQ bridge (ports 5555/5556/5557)
- **tv-api** (Go) — TradingView webhook receiver
- **notification** (Go) — Telegram bot notifications

## Infrastructure
- **Redis** (port 6379) — hot storage, pub/sub
- **TimescaleDB** (port 5432) — PostgreSQL 16 + time-series hypertables

## Quick Start
```bash
make infra-up          # Start Redis + TimescaleDB
make build             # Build all Docker images
make up                # Start all services
make test              # Run all tests
make lint              # Run all linters
```

## Service-specific Development

### trading-engine (Python)
```bash
cd services/trading-engine
uv sync                # Install dependencies
uv run pytest          # Run tests
uv run ruff check .    # Lint
```
- Config files in `configs/`
- Uses asyncio — never use `time.sleep()` in async code
- MT5 bridge calls must timeout: `asyncio.wait_for(timeout=5.0)`

### tv-api (Go)
```bash
cd services/tv-api
go test ./...          # Run tests
go vet ./...           # Lint
go build -o bin/tv-chart ./cmd/tv-chart
```
- Config: `config.yaml`
- Needs SESSION_ID and SESSION_SIGN env vars for TradingView

### mt5-bridge (Rust)
```bash
cd services/mt5-bridge
cargo test             # Run tests
cargo clippy           # Lint
cargo build --release  # Build
```
- ZeroMQ ports: 5555 (REQ/REP), 5556 (PUB), 5557 (SUB)

### notification (Go)
```bash
cd services/notification
go test ./...          # Run tests
go vet ./...           # Lint
go build -o bin/bot ./cmd/bot
```
- Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars

## Database
- Init schema: `infra/timescaledb/init.sql` (auto-applied on first docker run)
- Migrations: `infra/timescaledb/migrations/*.sql` (manual apply in order)
- Hypertables: trade_audit_log, rule_check_log, account_snapshot (180-day retention)

## Environment Variables
- Dev config: `configs/dev/.env`
- Required secrets: POSTGRES_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SESSION_ID, SESSION_SIGN
- All secrets via env vars — never hardcode

## Docker Compose
- File: `infra/docker/docker-compose.yml`
- Network: trading-net (172.20.0.0/16)
- Volumes: redis_data, timescale_data, engine_data

## Common Troubleshooting

### Container won't start
1. Check port conflicts: `ss -tlnp | grep -E '(6379|5432|5555|5556|5557)'`
2. Check logs: `docker logs trading-<service> --tail 50`
3. Check health: `make infra-status`

### Database connection failed
1. Verify TimescaleDB is healthy: `docker exec trading-timescaledb pg_isready -U trading`
2. Check POSTGRES_PASSWORD env var matches docker-compose default (devpassword)

### Python dependency issues
1. `cd services/trading-engine && uv sync`
2. If NautilusTrader fails: check Python version >= 3.11

### TradingView data not flowing
1. Check SESSION_ID and SESSION_SIGN in env (they expire — need refresh from browser cookies)
2. Check tv-api logs: `docker logs trading-tv-api --tail 30`
