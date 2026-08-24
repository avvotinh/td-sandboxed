---
name: local-dev
description: Local development knowledge — how to run, debug, and troubleshoot the Sandboxed trading system
---

# Local Development Guide

## Architecture Overview
- **trading-engine** (Python 3.11+) — NautilusTrader kernel + backtest lab + live path
- **chart-viewer** (Python/FastAPI) — reads `results/*.json` (Contract v2), no Docker/DB
- **mt5-bridge** (Rust) — MetaTrader 5 ZeroMQ bridge (ports 5555/5556/5557)
- **tv-api** (Go) — **frozen** (decision D4): only `cmd/tv-cli` survives, for historical
  data fetch. No server, no webhook receiver. `notification` was deleted in v2.

## Infrastructure
The **research loop needs none of it** (decision D6) — backtest, sweep, walk-forward and
the viewer run on parquet + JSON files alone. Do not ask for `/up` or `/migrate` when the
work is research.

Live path only:
- **Redis** (port 6379) — hot storage, pub/sub
- **TimescaleDB** (port 5432) — PostgreSQL 16 + time-series hypertables

## Quick Start (research loop)
```bash
cd services/trading-engine
uv run python -m src backtest run --job configs/backtest/<job>.yaml --export ../../results/
cd ../chart-viewer && uv run chart-viewer --results-dir ../../results --port 8777
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

### tv-api (Go) — frozen, fetch only
```bash
cd services/tv-api
go build ./...         # tv-cli is the only binary
./scripts/chunked-fetch.sh --symbol OANDA:XAUUSD --bare-symbol XAUUSD \
  --timeframe 5 --tf-label M5 --window-name in_sample --window-kind in_sample \
  --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z --step-days 20
```
- Needs SESSION_ID and SESSION_SIGN env vars (they expire — refresh from browser cookies)
- Writes into `data/historical/<symbol>/<tf>/<window>/chunks/`
- Frozen per D4: do not add features here. `internal/protocol` has one pre-existing
  test failure (`TestParseWSPacket`) that is deliberately not being fixed.

### mt5-bridge (Rust)
```bash
cd services/mt5-bridge
cargo test             # Run tests
cargo clippy           # Lint
cargo build --release  # Build
```
- ZeroMQ ports: 5555 (REQ/REP), 5556 (PUB), 5557 (SUB)

### chart-viewer (Python)
```bash
cd services/chart-viewer
uv run pytest
uv run chart-viewer --results-dir ../../results --port 8777
```
- Reads Contract v2 JSON + the parquet named by each run's `data_ref` — no Docker, no DB

## Database
- Init schema: `infra/timescaledb/init.sql` (auto-applied on first docker run)
- Migrations: `infra/timescaledb/migrations/*.sql` (manual apply in order)
- Hypertables: trade_audit_log, rule_check_log, account_snapshot (180-day retention)

## Environment Variables
- Dev config: `configs/dev/.env`
- Required secrets: POSTGRES_PASSWORD (live path), SESSION_ID + SESSION_SIGN (tv-cli fetch).
  The Telegram vars are gone with the `notification` service.
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
2. Read the fetch log the script writes: `data/historical/<symbol>/<tf>/<window>/fetch.log`
