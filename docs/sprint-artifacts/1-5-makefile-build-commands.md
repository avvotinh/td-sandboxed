# Story 1.5: Makefile Build Commands

**Epic:** 1 - Foundation & Infrastructure
**Status:** Done
**Created:** 2025-12-19

---

## User Story

As a **developer**,
I want **unified Makefile commands for common operations**,
So that **I can build, test, and run services consistently**.

---

## Context

This story implements the unified Makefile for the Sandboxed multi-account trading system. The project uses a polyglot tech stack with four independent services:

| Service | Language | Build Tool | Test Framework |
|---------|----------|------------|----------------|
| tv-api | Go 1.21+ | `go build` | `go test` |
| mt5-bridge | Rust 1.75+ | `cargo build` | `cargo test` |
| trading-engine | Python 3.11+ | `uv build` | `uv run pytest` |
| notification | Go 1.21+ | `go build` | `go test` |

The Makefile consolidates build, test, lint, and Docker Compose operations into a single interface, abstracting the polyglot complexity from developers.

### Current Test Status by Service

| Service | Test Framework | Test Location | Status |
|---------|---------------|---------------|--------|
| tv-api | `go test` | `*_test.go` files | Has 6 test files |
| mt5-bridge | `cargo test` | `tests/` directory | Empty (scaffolded) |
| trading-engine | `pytest` | `tests/` directory | Empty (scaffolded) |
| notification | `go test` | `*_test.go` files | Empty (no tests yet) |

**Note:** Some test directories are empty/scaffolded at this stage. The `make test` command uses `|| true` to continue even if individual services have no tests or tests fail. Use `make test-strict` for CI environments where failures should stop the build.

### Prerequisites

- **Story 1.4 Complete:** Environment configuration files created and verified
- **Story 1.2 Complete:** Docker Compose infrastructure stack (Redis, TimescaleDB)
- **Story 1.1 Complete:** Project structure with all service directories

**Previous Story:** [1-4-environment-configuration-setup.md](./1-4-environment-configuration-setup.md)

---

## Current State

### Existing Files

**`Makefile`** (19 lines - placeholder):
- Has `help` target only
- States "Full implementation in Story 1.5"

**`infra/docker/docker-compose.yml`** (66 lines):
- Defines Redis and TimescaleDB services
- Uses `${POSTGRES_PASSWORD:-devpassword}` pattern for environment variables
- Services on `trading-net` network

**Service Build Files:**
- `services/tv-api/go.mod` - Go module
- `services/tv-api/Dockerfile` - Docker build
- `services/mt5-bridge/Cargo.toml` - Rust cargo
- `services/mt5-bridge/Dockerfile` - Docker build
- `services/trading-engine/pyproject.toml` - Python uv project
- `services/trading-engine/Dockerfile` - Docker build
- `services/notification/go.mod` - Go module
- `services/notification/Dockerfile` - Docker build

---

## Acceptance Criteria

### AC1: Help Command Shows Available Targets
**Given** I am in the project root
**When** I run `make help`
**Then** I see available commands with descriptions

### AC2: Infrastructure Up Command
**Given** I run `make infra-up`
**Then** Redis and TimescaleDB containers start
**And** containers are healthy within 60 seconds

### AC3: Infrastructure Down Command
**Given** I run `make infra-down`
**Then** infrastructure containers stop gracefully

### AC4: Build All Services
**Given** I run `make build`
**Then** all Docker images are built for all services

### AC5: Start All Services
**Given** I run `make up`
**Then** all services start with proper dependencies
**And** infrastructure services start first

### AC6: Stop All Services
**Given** I run `make down`
**Then** all services stop gracefully

### AC7: Aggregated Logs
**Given** I run `make logs`
**Then** I see aggregated logs from all services in follow mode

### AC8: Test All Services
**Given** I run `make test`
**Then** tests run for all services that have tests

### AC9: Per-Service Build Commands
**Given** I run `make build-<service>`
**Then** only that service's binary/package is built locally (not Docker)

---

## Tasks

### Task 1: Implement Core Makefile Structure (AC1)
- [x] Add `.PHONY` declarations for all targets
- [x] Implement `help` target with formatted output using `@echo` (see format below)
- [x] Add variable definitions for common paths
- [x] Add header comment with usage documentation

**Expected `make help` output format:**
```
Usage: make [target]

Infrastructure:
  infra-up        Start Redis and TimescaleDB containers
  infra-down      Stop infrastructure containers
  infra-logs      View infrastructure logs
  infra-status    Show container health status

Docker Compose:
  build           Build all Docker images
  up              Start all services (detached)
  down            Stop all services
  logs            View aggregated logs (follow mode)
  restart         Restart all services

Per-Service Build:
  build-tv-api          Build tv-api binaries locally
  build-mt5-bridge      Build mt5-bridge binary locally
  build-trading-engine  Build trading-engine package locally
  build-notification    Build notification binary locally

Testing:
  test            Run all service tests
  test-<service>  Run tests for specific service

Linting:
  lint            Run all linters
  lint-<service>  Run linter for specific service
```

### Task 2: Implement Infrastructure Commands (AC2, AC3)
- [x] Implement `infra-up` target using docker compose
- [x] Implement `infra-down` target using docker compose
- [x] Implement `infra-logs` target for infrastructure-only logs
- [x] Implement `infra-status` target to show container health

### Task 3: Implement Docker Compose Commands (AC4, AC5, AC6, AC7)
- [x] Implement `build` target to build all Docker images
- [x] Implement `up` target to start all services in detached mode
- [x] Implement `down` target to stop all services
- [x] Implement `logs` target with follow mode (`-f`)
- [x] Implement `restart` target for convenience

### Task 4: Implement Per-Service Build Commands (AC9)
- [x] Implement `build-tv-api` using `go build`
- [x] Implement `build-mt5-bridge` using `cargo build --release`
- [x] Implement `build-trading-engine` using `uv build`
- [x] Implement `build-notification` using `go build`

### Task 5: Implement Test Commands (AC8)
- [x] Implement `test` target to run all service tests
- [x] Implement `test-tv-api` using `go test ./...`
- [x] Implement `test-mt5-bridge` using `cargo test`
- [x] Implement `test-trading-engine` using `uv run pytest`
- [x] Implement `test-notification` using `go test ./...`

### Task 6: Implement Lint Commands
- [x] Implement `lint` target that runs all per-service linters sequentially
- [x] Implement `lint-tv-api` using `golangci-lint run` (if available) or `go vet ./...`
- [x] Implement `lint-mt5-bridge` using `cargo clippy`
- [x] Implement `lint-trading-engine` using `uv run ruff check .`
- [x] Implement `lint-notification` using `golangci-lint run` (if available) or `go vet ./...`

**Error Handling for lint/test targets:**
- Individual service failures should NOT block other services from running
- Use `; \` line continuation to run all linters even if one fails
- Example: `lint-tv-api; lint-mt5-bridge; lint-trading-engine; lint-notification`
- Or use `|| true` suffix: `cd services/tv-api && go vet ./... || true`

### Task 7: Verify All Commands Work
- [x] Test `make help` shows all commands
- [x] Test `make infra-up` starts Redis and TimescaleDB
- [x] Test `make infra-down` stops infrastructure
- [x] Test per-service build commands (may require dependencies installed)
- [x] Document any commands that require prerequisites

---

## Technical Specifications

### Makefile Template (from Architecture)

The Architecture document specifies the following Makefile structure:

```makefile
# Makefile (root level)

.PHONY: all build up down logs test lint clean help \
        infra-up infra-down infra-logs infra-status \
        build-tv-api build-mt5-bridge build-trading-engine build-notification \
        test-tv-api test-mt5-bridge test-trading-engine test-notification \
        lint-tv-api lint-mt5-bridge lint-trading-engine lint-notification \
        restart

# Infrastructure
infra-up:
	docker compose -f infra/docker/docker-compose.yml up -d redis timescaledb

infra-down:
	docker compose -f infra/docker/docker-compose.yml down

# Build all services
build:
	docker compose -f infra/docker/docker-compose.yml build

# Start all services
up:
	docker compose -f infra/docker/docker-compose.yml up -d

# Stop all services
down:
	docker compose -f infra/docker/docker-compose.yml down

# View logs
logs:
	docker compose -f infra/docker/docker-compose.yml logs -f

# Restart all services
restart: down up

# Individual service commands
build-tv-api:
	cd services/tv-api && go build -o bin/tv-chart ./cmd/tv-chart
	cd services/tv-api && go build -o bin/tv-quote ./cmd/tv-quote

build-mt5-bridge:
	cd services/mt5-bridge && cargo build --release

build-trading-engine:
	cd services/trading-engine && uv build

build-notification:
	cd services/notification && go build -o bin/bot ./cmd/bot

# Testing
test:
	cd services/trading-engine && uv run pytest
	cd services/tv-api && go test ./...
	cd services/mt5-bridge && cargo test
	cd services/notification && go test ./...

# Linting
lint:
	cd services/trading-engine && uv run ruff check .
	cd services/tv-api && golangci-lint run
	cd services/mt5-bridge && cargo clippy
	cd services/notification && golangci-lint run
```

### Latest Technical Information (2025)

#### uv (Python Package Manager)
- **Version:** Latest stable (fast Rust-based Python package manager)
- **Build command:** `uv build` - builds source distributions and wheels to `dist/`
- **Run tests:** `uv run pytest` - runs pytest in project environment
- **Lint:** `uv run ruff check .` - runs ruff linter
- **Key feature:** `uv run` automatically syncs lockfile and environment before execution

#### Cargo (Rust)
- **Release build:** `cargo build --release` - optimized build to `target/release/`
- **Run tests:** `cargo test` - runs all tests
- **Lint:** `cargo clippy` - runs Rust linter
- **Note:** Use `--release` for production builds to enable optimizations

#### Go
- **Build:** `go build -o <output> <package>` - compiles to specified output
- **Run tests:** `go test ./...` - runs tests recursively
- **Lint:** `go vet ./...` or `golangci-lint run` (if installed)
- **Note:** Go tests include race detection with `-race` flag

#### Docker Compose (v2.x)
- **Build:** `docker compose build` - builds all service images
- **Start:** `docker compose up -d` - starts in detached mode
- **Stop:** `docker compose down` - stops and removes containers
- **Logs:** `docker compose logs -f` - follows log output
- **Note:** Modern Docker uses `docker compose` (space) not `docker-compose` (hyphen)

---

## Architecture Compliance

This story implements:
- **Architecture - Makefile Commands:** Implements the exact structure from architecture.md
- **Architecture - Polyglot Stack:** Supports Go, Rust, Python with appropriate build tools
- **Architecture - Docker Compose:** Uses docker-compose.yml for service orchestration

**Referenced Sections:**
- [Source: docs/architecture.md#makefile-commands]
- [Source: docs/architecture.md#deployment-architecture]
- [Source: docs/epics.md#story-1-5-makefile-build-commands]

---

## Previous Story Intelligence

### From Story 1.4 (Completed)

**Key Learnings:**
- Environment variables work with `${VAR:-default}` pattern in docker-compose.yml
- Docker Compose variable precedence: shell env > compose environment > env_file
- Container naming follows `trading-*` convention
- Services verified: `docker compose -f infra/docker/docker-compose.yml config`

**Files Verified Working:**
- `infra/docker/docker-compose.yml` - Infrastructure services healthy
- `configs/dev/.env` - Development credentials configured

**Patterns Established:**
- Infrastructure verification: `docker ps --filter "name=trading-"`
- Database check: `docker exec trading-timescaledb pg_isready -U trading`
- Redis check: `docker exec trading-redis redis-cli ping`

### Git Recent Commits

```
7c5dad4 Implement spec 1 story 1.4
82328cb Implement spec 1 story 1.3
e6ed42f Implement epec 1 story 1.1 1.2
483033f Planning and create architecture document
```

**Code Patterns:**
- Environment configuration uses shell exports before docker compose
- Container health checks implemented for all infrastructure services

---

## Dev Agent Guardrails

### MUST DO:

1. **Use modern `docker compose`** (space, not hyphen) for all compose commands
2. **Follow Architecture Makefile structure** from docs/architecture.md#makefile-commands (template above has updated `docker compose` syntax)
3. **Add `.PHONY` declarations** for ALL targets (prevents issues with same-named files)
4. **Include `help` target** as first/default target with clear documentation
5. **Use relative paths** from project root for all service directories
6. **Include error handling** - commands should fail fast on errors
7. **Test infrastructure commands** - verify `make infra-up` and `make infra-down` work
8. **Use `-f` flag** for logs command to enable follow mode
9. **Build Go binaries to `bin/` directory** within each service (e.g., `services/tv-api/bin/`)

### DO NOT:

1. **Do NOT use `docker-compose`** (hyphenated) - deprecated in Docker Compose v2
2. **Do NOT hardcode passwords** - rely on environment variables or defaults
3. **Do NOT add services to docker-compose.yml** - only infrastructure for now
4. **Do NOT require specific Go/Rust/Python versions** to be pre-installed for Docker builds
5. **Do NOT break existing infrastructure** - test that Redis and TimescaleDB still work
6. **Do NOT add complex conditional logic** - keep Makefile simple and portable
7. **Do NOT use BSD make syntax** - stick to GNU make compatible syntax
8. **Do NOT add newlines in recipe commands** - use `&&` or `;` for chaining

### File Modification:

**Files to Modify:**
- `Makefile` - Replace placeholder with full implementation

**Files NOT to Modify:**
- `infra/docker/docker-compose.yml` - Already configured correctly
- `configs/dev/.env` - Environment config complete
- Any service source code files

---

## Testing Verification

### Manual Test Steps

```bash
# 1. Navigate to project root
cd /home/hopdev/Dev/Sandboxed

# 2. Test help command
make help
# Expected: List of all available targets with descriptions

# 3. Test infrastructure up
make infra-up
# Expected: Redis and TimescaleDB containers start

# 4. Verify containers running
docker ps --filter "name=trading-"
# Expected: trading-redis and trading-timescaledb with healthy status

# 5. Test infrastructure down
make infra-down
# Expected: Containers stop gracefully

# 6. Test build (Docker images)
make build
# Expected: All service Docker images built (may take time first run)

# 7. Test per-service build (requires local toolchain)
# These may fail if Go/Rust/Python not installed - that's OK
make build-tv-api 2>/dev/null || echo "Go not installed - skip"
make build-mt5-bridge 2>/dev/null || echo "Rust not installed - skip"
make build-trading-engine 2>/dev/null || echo "Python/uv not installed - skip"

# 8. Test all services up (after build)
make up
make logs  # Ctrl+C to exit
make down
```

### Verification Checklist

- [x] `make help` displays all targets with descriptions
- [x] `make infra-up` starts Redis and TimescaleDB containers
- [x] `make infra-down` stops infrastructure containers
- [x] `make build` builds Docker images without errors
- [x] `make up` starts all services
- [x] `make down` stops all services
- [x] `make logs` shows aggregated logs in follow mode
- [x] Per-service build commands are defined (execution depends on toolchain availability)

---

## Dependencies

- **Prerequisites:** Story 1.4 (Environment Configuration) - DONE
- **Blocks:**
  - Story 1.6 (Trading Engine Scaffold) - needs build commands
  - Story 1.7 (MT5 Bridge Scaffold) - needs build commands
  - Story 1.8 (Notification Scaffold) - needs build commands
  - Story 1.9 (Full Stack Docker Compose) - needs `make up/down`

---

## Definition of Done

- [x] `Makefile` fully implemented with all targets from Architecture spec
- [x] `make help` shows comprehensive help text
- [x] `make infra-up` and `make infra-down` work correctly
- [x] `make build` builds all Docker images
- [x] `make up`, `make down`, `make logs` work correctly
- [x] Per-service build targets defined (`build-*`)
- [x] Per-service test targets defined (`test-*`)
- [x] Per-service lint targets defined (`lint-*`)
- [x] All commands use modern `docker compose` (not `docker-compose`)
- [x] Story status updated to `review` in sprint-status.yaml

---

## File List

**Files to Modify:**
- `Makefile` - Replace placeholder with full implementation (~130-150 lines)

**Files NOT to Modify:**
- `infra/docker/docker-compose.yml` - Already configured
- `configs/dev/.env` - Already configured
- Any service directories or source files

---

## References

- [Architecture - Makefile Commands](../architecture.md#makefile-commands)
- [Architecture - Deployment Architecture](../architecture.md#deployment-architecture)
- [Epic 1 - Story 1.5](../epics.md#story-15-makefile-build-commands)
- [Story 1.4 - Environment Configuration](./1-4-environment-configuration-setup.md)
- [Docker Compose CLI Reference](https://docs.docker.com/compose/reference/)
- [uv Documentation](https://docs.astral.sh/uv/)
- [Cargo Book](https://doc.rust-lang.org/cargo/)

---

## Dev Agent Record

### Context Reference

- Epic 1 Context: `docs/epics.md` (Story 1.5 section)
- Architecture: `docs/architecture.md` (Makefile Commands, Deployment sections)
- Previous Story: `docs/sprint-artifacts/1-4-environment-configuration-setup.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Verified `make help` displays all 20+ targets with descriptions
- Verified `make infra-up` starts Redis and TimescaleDB containers (both healthy)
- Verified `make infra-down` stops infrastructure containers gracefully
- Verified `make build` executes without errors (infrastructure uses pre-built images)
- Verified `make up` and `make down` work correctly
- Verified `build-tv-api` builds Go binaries to `services/tv-api/bin/`
- Verified `build-trading-engine` builds Python package to `services/trading-engine/dist/`
- Verified `build-notification` builds Go binary to `services/notification/bin/`
- Note: `build-mt5-bridge` requires Rust toolchain (expected - not installed on this system)
- Note: Some lint/test commands depend on external tools (cargo, ruff via uv) - handled with `|| true`

### Completion Notes List

- Implemented comprehensive Makefile (252 lines) with all targets from Architecture spec
- All commands use modern `docker compose` syntax (v2, space not hyphen)
- Added `.PHONY` declarations for all 24 targets
- Added variable definitions for reusable paths (COMPOSE_FILE, service directories)
- Implemented error handling for aggregate test/lint commands using `|| true`
- Added `clean` target for complete container/volume cleanup
- Added `infra-status` target for quick container health check
- All infrastructure commands verified working with real Docker containers

### File List

**Modified:**
- `Makefile` - Replaced placeholder with full implementation (260 lines)
- `docs/architecture.md` - Updated Makefile Commands section to use modern `docker compose` syntax

**Generated (build artifacts):**
- `services/trading-engine/uv.lock` - Lock file generated by `uv build` (should be committed for reproducible builds)

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-19 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-19 | **Validation improvements applied:** (1) Updated embedded Makefile template to use modern `docker compose` syntax; (2) Clarified Architecture compliance instruction; (3) Added complete .PHONY declaration for all 20+ targets; (4) Added test status by service table; (5) Added expected `make help` output format; (6) Added error handling guidance for lint/test targets; (7) Added restart target; (8) Added parallel build documentation; (9) Updated line count estimate to ~130-150 lines |
| 2025-12-19 | **Implementation complete:** Full Makefile implementation (252 lines) with all targets. Verified: make help, infra-up/down, build, up/down, per-service builds (tv-api, trading-engine, notification), test, lint commands. Story marked Ready for Review. |
| 2025-12-19 | **Code Review fixes applied:** (1) Updated docs/architecture.md Makefile section to use `docker compose` instead of deprecated `docker-compose`; (2) Added `test-strict` target for CI environments; (3) Updated test status table to reflect actual state (tv-api has tests, others empty); (4) Documented uv.lock in File List; (5) Clarified test command behavior in notes |

---

## Notes

- This story focuses on Makefile implementation ONLY
- No service code changes required
- Docker builds may take several minutes on first run
- Per-service build commands require local toolchains (Go, Rust, Python/uv)
- Docker-based builds (`make build`) work without local toolchains
- Use `docker compose` (v2 syntax) not `docker-compose` (deprecated)
- **Parallel builds:** For faster local builds, use `make -j4 build-tv-api build-mt5-bridge build-notification` to run independent targets in parallel
