# Sandboxed Trading System - Root Makefile
# =========================================
# Unified build, test, and lint commands.
#
# Services:
#   - trading-engine (Python 3.11+) - NautilusTrader kernel + backtest lab + live path
#   - chart-viewer (Python 3.12+)   - FastAPI viewer for Result Contract v2 runs
#   - mt5-bridge (Rust 1.75+)       - MetaTrader 5 ZeroMQ bridge
#   - tv-api (Go)                   - FROZEN (decision D4): tv-cli historical fetch only
#
# The research loop (backtest, sweep, walk-forward, viewer) needs no Docker, no
# TimescaleDB and no Redis — decision D6. The infra and compose targets below are
# for the live path only.
#
# Usage:
#   make help          - Show all available targets
#   make test          - Run all tests
#
# Prerequisites:
#   - For research: Python 3.11+ with uv
#   - For the live path: Docker and Docker Compose v2, Rust 1.75+
#   - For data fetch: Go 1.21+

# Variables
COMPOSE_FILE := infra/docker/docker-compose.yml
DOCKER_COMPOSE := docker compose -f $(COMPOSE_FILE)

# Service directories
TV_API_DIR := services/tv-api
MT5_BRIDGE_DIR := services/mt5-bridge
TRADING_ENGINE_DIR := services/trading-engine
CHART_VIEWER_DIR := services/chart-viewer

# All phony targets
.PHONY: all help \
        infra-up infra-down infra-logs infra-status \
        build up down logs restart clean \
        build-tv-cli build-mt5-bridge build-trading-engine \
        test test-strict test-mt5-bridge test-trading-engine test-chart-viewer \
        lint lint-mt5-bridge lint-trading-engine lint-chart-viewer \
        viewer

# Default target
all: help

# Help target - displays available commands
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Research loop (no Docker needed):"
	@echo "  test-trading-engine Run trading-engine tests"
	@echo "  test-chart-viewer   Run chart-viewer tests"
	@echo "  viewer              Start the chart viewer on port 8777"
	@echo ""
	@echo "Infrastructure (live path only):"
	@echo "  infra-up        Start Redis and TimescaleDB containers"
	@echo "  infra-down      Stop infrastructure containers"
	@echo "  infra-logs      View infrastructure logs"
	@echo "  infra-status    Show container health status"
	@echo ""
	@echo "Docker Compose (live path only):"
	@echo "  build           Build all Docker images"
	@echo "  up              Start all services (detached)"
	@echo "  down            Stop all services"
	@echo "  logs            View aggregated logs (follow mode)"
	@echo "  restart         Restart all services"
	@echo "  clean           Stop and remove all containers, networks, volumes"
	@echo ""
	@echo "Per-Service Build:"
	@echo "  build-tv-cli          Build the frozen tv-cli fetch binary"
	@echo "  build-mt5-bridge      Build mt5-bridge binary locally"
	@echo "  build-trading-engine  Build trading-engine package locally"
	@echo ""
	@echo "Testing:"
	@echo "  test            Run all service tests (continues on failure)"
	@echo "  test-strict     Run all tests in strict mode (fails on first error)"
	@echo "  test-mt5-bridge Run mt5-bridge tests"
	@echo ""
	@echo "Linting:"
	@echo "  lint            Run all linters"
	@echo "  lint-mt5-bridge Run mt5-bridge linter (cargo clippy)"
	@echo "  lint-trading-engine Run trading-engine linter (ruff)"
	@echo "  lint-chart-viewer   Run chart-viewer linter (ruff)"

# =============================================================================
# Infrastructure Commands (live path only)
# =============================================================================

# Start infrastructure services (Redis, TimescaleDB)
infra-up:
	@echo "Starting infrastructure services..."
	$(DOCKER_COMPOSE) up -d redis timescaledb
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@$(MAKE) infra-status

# Stop infrastructure services
infra-down:
	@echo "Stopping infrastructure services..."
	$(DOCKER_COMPOSE) down

# View infrastructure logs
infra-logs:
	$(DOCKER_COMPOSE) logs -f redis timescaledb

# Show container health status
infra-status:
	@echo "Container Status:"
	@docker ps --filter "name=trading-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No trading containers running"

# =============================================================================
# Docker Compose Commands (live path only)
# =============================================================================

# Build all Docker images
build:
	@echo "Building all Docker images..."
	$(DOCKER_COMPOSE) build

# Start all services in detached mode
up:
	@echo "Starting all services..."
	$(DOCKER_COMPOSE) up -d

# Stop all services
down:
	@echo "Stopping all services..."
	$(DOCKER_COMPOSE) down

# View aggregated logs in follow mode
logs:
	$(DOCKER_COMPOSE) logs -f

# Restart all services
restart: down up

# Stop and remove all containers, networks, volumes
clean:
	@echo "Cleaning up all containers, networks, and volumes..."
	$(DOCKER_COMPOSE) down -v --remove-orphans

# =============================================================================
# Research Loop
# =============================================================================

# Start the chart viewer against results/
viewer:
	cd $(CHART_VIEWER_DIR) && uv run chart-viewer --results-dir ../../results --port 8777

# =============================================================================
# Per-Service Build Commands (Local builds - require toolchains installed)
# =============================================================================

# Build the frozen tv-cli fetch binary. tv-api is frozen (D4) — tv-cli is the
# only binary left, and scripts/chunked-fetch.sh expects it at the module root.
build-tv-cli:
	@echo "Building tv-cli..."
	cd $(TV_API_DIR) && go build -o tv-cli ./cmd/tv-cli
	@echo "tv-cli built at $(TV_API_DIR)/tv-cli"

# Build mt5-bridge Rust binary locally
build-mt5-bridge:
	@echo "Building mt5-bridge..."
	cd $(MT5_BRIDGE_DIR) && cargo build --release
	@echo "mt5-bridge binary built in $(MT5_BRIDGE_DIR)/target/release/"

# Build trading-engine Python package locally
build-trading-engine:
	@echo "Building trading-engine..."
	cd $(TRADING_ENGINE_DIR) && uv build
	@echo "trading-engine package built in $(TRADING_ENGINE_DIR)/dist/"

# =============================================================================
# Test Commands
# =============================================================================
#
# tv-api is deliberately absent: it is frozen, and internal/protocol carries a
# pre-existing test failure that is not being fixed. Build it, do not test it.

# Run all service tests (continues even if individual tests fail)
test:
	@echo "Running all service tests..."
	@echo ""
	@echo "=== trading-engine tests ==="
	@cd $(TRADING_ENGINE_DIR) && uv run pytest || true
	@echo ""
	@echo "=== chart-viewer tests ==="
	@cd $(CHART_VIEWER_DIR) && uv run pytest || true
	@echo ""
	@echo "=== mt5-bridge tests ==="
	@cd $(MT5_BRIDGE_DIR) && cargo test || true
	@echo ""
	@echo "All tests completed."

# Run mt5-bridge tests
test-mt5-bridge:
	@echo "Running mt5-bridge tests..."
	cd $(MT5_BRIDGE_DIR) && cargo test

# Run trading-engine tests
test-trading-engine:
	@echo "Running trading-engine tests..."
	cd $(TRADING_ENGINE_DIR) && uv run pytest

# Run chart-viewer tests
test-chart-viewer:
	@echo "Running chart-viewer tests..."
	cd $(CHART_VIEWER_DIR) && uv run pytest

# Run all tests in strict mode (fails on first error - use for CI)
test-strict:
	@echo "Running all service tests (strict mode - fails on first error)..."
	cd $(TRADING_ENGINE_DIR) && uv run pytest
	cd $(CHART_VIEWER_DIR) && uv run pytest
	cd $(MT5_BRIDGE_DIR) && cargo test
	@echo "All tests passed."

# =============================================================================
# Lint Commands
# =============================================================================

# Run all linters (continues even if individual linters fail)
lint:
	@echo "Running all linters..."
	@echo ""
	@echo "=== trading-engine lint ==="
	@cd $(TRADING_ENGINE_DIR) && uv run ruff check . || true
	@echo ""
	@echo "=== chart-viewer lint ==="
	@cd $(CHART_VIEWER_DIR) && uv run ruff check . || true
	@echo ""
	@echo "=== mt5-bridge lint ==="
	@cd $(MT5_BRIDGE_DIR) && cargo clippy || true
	@echo ""
	@echo "All linting completed."

# Run mt5-bridge linter
lint-mt5-bridge:
	@echo "Running mt5-bridge linter..."
	cd $(MT5_BRIDGE_DIR) && cargo clippy

# Run trading-engine linter
lint-trading-engine:
	@echo "Running trading-engine linter..."
	cd $(TRADING_ENGINE_DIR) && uv run ruff check .

# Run chart-viewer linter
lint-chart-viewer:
	@echo "Running chart-viewer linter..."
	cd $(CHART_VIEWER_DIR) && uv run ruff check .
