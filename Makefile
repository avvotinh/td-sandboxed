# Sandboxed Trading System - Root Makefile
# =========================================
# Unified build, test, and deployment commands for the polyglot trading system.
#
# Services:
#   - tv-api (Go 1.21+)        - TradingView API bridge
#   - mt5-bridge (Rust 1.75+)  - MetaTrader 5 ZeroMQ bridge
#   - trading-engine (Python 3.11+) - NautilusTrader-based engine
#   - notification (Go 1.21+) - Telegram notification bot
#
# Usage:
#   make help          - Show all available targets
#   make infra-up      - Start infrastructure (Redis, TimescaleDB)
#   make build         - Build all Docker images
#   make up            - Start all services
#   make test          - Run all tests
#
# Prerequisites:
#   - Docker and Docker Compose v2
#   - For local builds: Go 1.21+, Rust 1.75+, Python 3.11+ with uv

# Variables
COMPOSE_FILE := infra/docker/docker-compose.yml
DOCKER_COMPOSE := docker compose -f $(COMPOSE_FILE)

# Service directories
TV_API_DIR := services/tv-api
MT5_BRIDGE_DIR := services/mt5-bridge
TRADING_ENGINE_DIR := services/trading-engine
NOTIFICATION_DIR := services/notification

# All phony targets
.PHONY: all help \
        infra-up infra-down infra-logs infra-status \
        build up down logs restart clean \
        build-tv-api build-mt5-bridge build-trading-engine build-notification \
        test test-strict test-tv-api test-mt5-bridge test-trading-engine test-notification \
        lint lint-tv-api lint-mt5-bridge lint-trading-engine lint-notification

# Default target
all: help

# Help target - displays available commands
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Infrastructure:"
	@echo "  infra-up        Start Redis and TimescaleDB containers"
	@echo "  infra-down      Stop infrastructure containers"
	@echo "  infra-logs      View infrastructure logs"
	@echo "  infra-status    Show container health status"
	@echo ""
	@echo "Docker Compose:"
	@echo "  build           Build all Docker images"
	@echo "  up              Start all services (detached)"
	@echo "  down            Stop all services"
	@echo "  logs            View aggregated logs (follow mode)"
	@echo "  restart         Restart all services"
	@echo "  clean           Stop and remove all containers, networks, volumes"
	@echo ""
	@echo "Per-Service Build:"
	@echo "  build-tv-api          Build tv-api binaries locally"
	@echo "  build-mt5-bridge      Build mt5-bridge binary locally"
	@echo "  build-trading-engine  Build trading-engine package locally"
	@echo "  build-notification    Build notification binary locally"
	@echo ""
	@echo "Testing:"
	@echo "  test            Run all service tests (continues on failure)"
	@echo "  test-strict     Run all tests in strict mode (fails on first error)"
	@echo "  test-tv-api     Run tv-api tests"
	@echo "  test-mt5-bridge Run mt5-bridge tests"
	@echo "  test-trading-engine Run trading-engine tests"
	@echo "  test-notification Run notification tests"
	@echo ""
	@echo "Linting:"
	@echo "  lint            Run all linters"
	@echo "  lint-tv-api     Run tv-api linter"
	@echo "  lint-mt5-bridge Run mt5-bridge linter (cargo clippy)"
	@echo "  lint-trading-engine Run trading-engine linter (ruff)"
	@echo "  lint-notification Run notification linter"

# =============================================================================
# Infrastructure Commands
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
# Docker Compose Commands
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
# Per-Service Build Commands (Local builds - require toolchains installed)
# =============================================================================

# Build tv-api Go binaries locally
build-tv-api:
	@echo "Building tv-api..."
	@mkdir -p $(TV_API_DIR)/bin
	cd $(TV_API_DIR) && go build -o bin/tv-chart ./cmd/tv-chart
	cd $(TV_API_DIR) && go build -o bin/tv-quote ./cmd/tv-quote
	@echo "tv-api binaries built in $(TV_API_DIR)/bin/"

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

# Build notification Go binary locally
build-notification:
	@echo "Building notification..."
	@mkdir -p $(NOTIFICATION_DIR)/bin
	cd $(NOTIFICATION_DIR) && go build -o bin/bot ./cmd/bot
	@echo "notification binary built in $(NOTIFICATION_DIR)/bin/"

# =============================================================================
# Test Commands
# =============================================================================

# Run all service tests (continues even if individual tests fail)
test:
	@echo "Running all service tests..."
	@echo ""
	@echo "=== tv-api tests ==="
	@cd $(TV_API_DIR) && go test ./... || true
	@echo ""
	@echo "=== mt5-bridge tests ==="
	@cd $(MT5_BRIDGE_DIR) && cargo test || true
	@echo ""
	@echo "=== trading-engine tests ==="
	@cd $(TRADING_ENGINE_DIR) && uv run pytest || true
	@echo ""
	@echo "=== notification tests ==="
	@cd $(NOTIFICATION_DIR) && go test ./... || true
	@echo ""
	@echo "All tests completed."

# Run tv-api tests
test-tv-api:
	@echo "Running tv-api tests..."
	cd $(TV_API_DIR) && go test ./...

# Run mt5-bridge tests
test-mt5-bridge:
	@echo "Running mt5-bridge tests..."
	cd $(MT5_BRIDGE_DIR) && cargo test

# Run trading-engine tests
test-trading-engine:
	@echo "Running trading-engine tests..."
	cd $(TRADING_ENGINE_DIR) && uv run pytest

# Run notification tests
test-notification:
	@echo "Running notification tests..."
	cd $(NOTIFICATION_DIR) && go test ./...

# Run all tests in strict mode (fails on first error - use for CI)
test-strict:
	@echo "Running all service tests (strict mode - fails on first error)..."
	cd $(TV_API_DIR) && go test ./...
	cd $(MT5_BRIDGE_DIR) && cargo test
	cd $(TRADING_ENGINE_DIR) && uv run pytest
	cd $(NOTIFICATION_DIR) && go test ./...
	@echo "All tests passed."

# =============================================================================
# Lint Commands
# =============================================================================

# Run all linters (continues even if individual linters fail)
lint:
	@echo "Running all linters..."
	@echo ""
	@echo "=== tv-api lint ==="
	@cd $(TV_API_DIR) && go vet ./... || true
	@echo ""
	@echo "=== mt5-bridge lint ==="
	@cd $(MT5_BRIDGE_DIR) && cargo clippy || true
	@echo ""
	@echo "=== trading-engine lint ==="
	@cd $(TRADING_ENGINE_DIR) && uv run ruff check . || true
	@echo ""
	@echo "=== notification lint ==="
	@cd $(NOTIFICATION_DIR) && go vet ./... || true
	@echo ""
	@echo "All linting completed."

# Run tv-api linter
lint-tv-api:
	@echo "Running tv-api linter..."
	cd $(TV_API_DIR) && go vet ./...

# Run mt5-bridge linter
lint-mt5-bridge:
	@echo "Running mt5-bridge linter..."
	cd $(MT5_BRIDGE_DIR) && cargo clippy

# Run trading-engine linter
lint-trading-engine:
	@echo "Running trading-engine linter..."
	cd $(TRADING_ENGINE_DIR) && uv run ruff check .

# Run notification linter
lint-notification:
	@echo "Running notification linter..."
	cd $(NOTIFICATION_DIR) && go vet ./...
