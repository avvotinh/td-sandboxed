# Story 1.4: Environment Configuration Setup

**Epic:** 1 - Foundation & Infrastructure
**Status:** Done
**Created:** 2025-12-19

---

## User Story

As a **developer**,
I want **environment configuration files with all required variables documented**,
So that **I can easily configure and deploy services across different environments**.

---

## Context

This story completes the environment configuration management for the multi-account trading system. The system requires configuration for four services (tv-api, mt5-bridge, trading-engine, notification) and infrastructure (Redis, TimescaleDB). All secrets must be managed via environment variables per NFR6.

### Prerequisites

- **Story 1.3 Complete:** TimescaleDB schema initialized with all required tables
- **Story 1.2 Complete:** Docker Compose infrastructure stack running
- **Story 1.1 Complete:** Project structure with service directories

**Previous Story:** [1-3-timescaledb-schema-initialization.md](./1-3-timescaledb-schema-initialization.md)
**Reference:** [Epic 1 Context](../epic-1-context.md)

---

## Current State

### Existing Files

**`configs/.env.example`** (64 lines):
- Has basic TradingView, Database, Logging, Benchmark config
- Missing: Trading Engine, MT5 Bridge, Notification service variables
- Missing: ZeroMQ ports, Trading mode, Telegram credentials

**`configs/dev/.env`** (64 lines):
- Contains actual development credentials (not tracked by git per .gitignore)
- TradingView SESSION_ID and SESSION_SIGN configured [REDACTED - see actual file]
- Database credentials configured for development

**`configs/prod/`**:
- Empty directory - no .env.example template

**`infra/docker/docker-compose.yml`**:
- Uses inline environment variables with defaults
- Missing: env_file directive for centralized configuration

---

## Acceptance Criteria

### AC1: Updated .env.example with All Variables
**Given** I examine `configs/.env.example`
**When** I read the file
**Then** I see documented variables for:
- Infrastructure: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`
- TV-API: `SESSION_ID`, `SESSION_SIGN`
- Trading Engine: `TRADING_MODE`, `ZMQ_BRIDGE_HOST`, `ZMQ_PUB_PORT`, `ZMQ_SUB_PORT`
- MT5 Bridge: `RUST_LOG`, `ZMQ_REQ_PORT`, `ZMQ_PUB_PORT`, `ZMQ_SUB_PORT`
- Notification: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Logging: `LOG_LEVEL`, `LOG_FORMAT`

### AC2: Dev .env Has Sensible Defaults
**Given** I examine `configs/dev/.env`
**When** I compare to `.env.example`
**Then** all required variables have values
**And** placeholder values are clearly marked for secrets

### AC3: Production Template Exists
**Given** I examine `configs/prod/`
**When** I list the directory
**Then** `.env.example` exists with production-specific documentation

### AC4: Docker Compose Uses env_file
**Given** I copy `.env.example` to `.env` and fill credentials
**When** Docker Compose reads configuration
**Then** all environment variables are loaded from the env file
**And** services start without missing required variables

---

## Tasks

### Task 1: Update configs/.env.example (AC1)
- [x] Add Infrastructure section with all database and Redis variables
- [x] Add TV-API section with TradingView credentials
- [x] Add Trading Engine section with mode and ZeroMQ settings
- [x] Add MT5 Bridge section with Rust logging and ZMQ ports
- [x] Add Notification section with Telegram credentials
- [x] Add documentation comments for each variable
- [x] Include placeholder instructions for obtaining credentials

### Task 2: Verify and Update configs/dev/.env (AC2)
- [x] Ensure all variables from .env.example are present
- [x] Add development defaults for new service variables
- [x] Use placeholder values for secrets not yet configured
- [x] Maintain existing working credentials (TradingView, Database)

### Task 3: Create configs/prod/.env.example (AC3)
- [x] Create production environment template
- [x] Add production-specific documentation comments
- [x] Include security reminders (NFR6 compliance)
- [x] Add deployment checklist notes
- [x] Add SSL/TLS configuration hints for database connections
- [x] Add reminder to set LOG_LEVEL=warn or LOG_LEVEL=error (not debug)
- [x] Note container resource limits recommendation
- [x] Include pre-deployment verification checklist

### Task 4: Update Docker Compose with env_file (AC4)
- [x] Add `env_file` directive to docker-compose.yml
- [x] Configure to load from appropriate environment directory
- [x] Test with `docker compose config` to verify variable substitution
- [x] Verify infrastructure services start with env_file loading

### Task 5: Verify Configuration
- [x] Test `docker compose -f infra/docker/docker-compose.yml config` shows resolved variables
- [x] Test infrastructure starts with `make infra-up` (or docker compose up)
- [x] Verify database connection with POSTGRES_PASSWORD from env file
- [x] Document any issues found during verification

---

## Technical Specifications

### Complete .env.example Template

```bash
# Sandboxed Multi-Account Trading System - Environment Configuration
#
# USAGE:
# 1. Copy this file to configs/dev/.env (for development) or configs/prod/.env (for production)
# 2. Fill in all required values (marked with [REQUIRED])
# 3. Never commit .env files to git - they contain secrets
#
# NFR6: All secrets must be managed via environment variables
# Version: 1.4 (Story 1.4)
# Last Updated: 2025-12-19

# ============================================================================
# INFRASTRUCTURE - Database & Cache
# ============================================================================

# PostgreSQL/TimescaleDB Configuration
# Used by: trading-timescaledb container, trading-engine, tv-api
POSTGRES_DB=trading
POSTGRES_USER=trading
POSTGRES_PASSWORD=your_secure_password_here  # [REQUIRED] Min 16 chars recommended

# Redis Configuration
# Used by: trading-redis container, tv-api, trading-engine, notification
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=                               # Optional - leave empty for no auth in dev
REDIS_DB=0

# Alternative: Set REDIS_URL directly instead of HOST/PORT components
# REDIS_URL=redis://redis:6379/0

# ============================================================================
# TV-API SERVICE - TradingView Data Collector
# ============================================================================

# TradingView Session Credentials
# How to obtain:
# 1. Log into TradingView in your browser
# 2. Open DevTools (F12) -> Application -> Cookies
# 3. Find cookies for tradingview.com
# 4. Copy 'sessionid' (SESSION_ID) and 'sessionid_sign' (SESSION_SIGN) values
SESSION_ID=your_session_id_here              # [REQUIRED] TradingView sessionid cookie
SESSION_SIGN=your_session_sign_here          # [REQUIRED] TradingView sessionid_sign cookie

# ============================================================================
# TRADING ENGINE SERVICE - Python/Nautilus Trader
# ============================================================================

# Trading Mode
# paper = Simulated trading (no real orders)
# live  = Real trading with actual MT5 orders
TRADING_MODE=paper                            # [REQUIRED] paper | live

# ZeroMQ Connection to MT5 Bridge
# Used to communicate with mt5-bridge for order execution
#
# ZeroMQ Port Architecture:
# - mt5-bridge PUBLISHES tick data on port 5556 → trading-engine SUBSCRIBES
# - trading-engine sends orders → mt5-bridge SUBSCRIBES on port 5557
# Both services use the same ports as opposite ends of the same channels
#
ZMQ_BRIDGE_HOST=mt5-bridge                    # Docker service name
ZMQ_PUB_PORT=5556                             # Port for receiving tick data (SUB from mt5-bridge PUB)
ZMQ_SUB_PORT=5557                             # Port for sending orders (to mt5-bridge)

# Database Connection (auto-generated from POSTGRES_* vars)
# Override only for external database
# TIMESCALE_URL=postgres://trading:password@trading-timescaledb:5432/trading?sslmode=disable

# Redis Connection (auto-generated)
# Override only for external Redis
# REDIS_URL=redis://redis:6379

# ============================================================================
# MT5 BRIDGE SERVICE - Rust ZeroMQ Bridge
# ============================================================================

# Rust Logging Configuration
# trace = Most verbose
# debug = Development debugging
# info  = Standard operation
# warn  = Warnings only
# error = Errors only
RUST_LOG=info                                 # trace | debug | info | warn | error

# ZeroMQ Ports (exposed to MT5 EA)
# These must match the ports configured in your MT5 Expert Advisor
ZMQ_REQ_PORT=5555                             # REQ/REP port for MT5 EA commands
# ZMQ_PUB_PORT=5556                           # Defined above - shared with trading-engine
# ZMQ_SUB_PORT=5557                           # Defined above - shared with trading-engine

# ============================================================================
# NOTIFICATION SERVICE - Telegram Bot
# ============================================================================

# Telegram Bot Credentials
# How to obtain:
# 1. Message @BotFather on Telegram
# 2. Create new bot with /newbot command
# 3. Copy the bot token provided
# 4. Start chat with your bot and get chat_id from:
#    https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_BOT_TOKEN=your_bot_token_here        # [REQUIRED for notifications]
TELEGRAM_CHAT_ID=your_chat_id_here            # [REQUIRED for notifications]

# ============================================================================
# LOGGING - All Services
# ============================================================================

# Log Level (applies to all services unless overridden)
LOG_LEVEL=info                                # debug | info | warn | error

# Log Format
# json = Structured JSON output (recommended for production)
# text = Human-readable text (recommended for development)
LOG_FORMAT=json                               # json | text

# ============================================================================
# APPLICATION TUNING
# ============================================================================

# TV-API Performance Tuning
BATCH_SIZE=100                                # Records to batch before database insert
FLUSH_INTERVAL=1s                             # Time interval to flush batch

# Benchmark Configuration (for testing)
BENCHMARK_ITERATIONS=1000                     # Queries to run in benchmark
BENCHMARK_TARGET_MS=20                        # Target latency in ms (NFR1)

# ============================================================================
# SECURITY NOTES (NFR6)
# ============================================================================
#
# - NEVER commit .env files to git (verified in .gitignore)
# - Use strong passwords (minimum 16 characters, mixed case, numbers, symbols)
# - Rotate credentials regularly (monthly recommended)
# - Use different credentials for dev/staging/prod environments
# - Consider secrets management tools for production:
#   - HashiCorp Vault
#   - AWS Secrets Manager
#   - Docker Secrets (Swarm mode)
#
# ============================================================================
```

### Docker Compose env_file Configuration

The docker-compose.yml should be updated to include `env_file` directive. Per architecture.md, the compose file should support loading environment from a centralized location.

```yaml
# Add at top level or per service:
env_file:
  - ../../configs/dev/.env
```

**Docker Compose Variable Precedence (highest to lowest):**
1. Shell environment variables (`export VAR=value`)
2. Values in compose.yml `environment:` section
3. Values from `env_file`

**Note:** The current docker-compose.yml uses `${VARIABLE:-default}` syntax which works with exported environment variables OR an env_file. The env_file approach provides better organization and prevents shell environment pollution. The existing `${VAR:-default}` fallbacks remain as safe defaults if env_file is missing or incomplete.

### Production .env.example Additional Notes

Production template should include:
- Stronger password requirements (minimum 24 characters, mixed case, numbers, symbols)
- SSL/TLS configuration hints:
  ```
  # For production TimescaleDB with SSL:
  # TIMESCALE_URL=postgres://user:pass@host:5432/db?sslmode=require
  ```
- LOG_LEVEL should default to `warn` or `error` (never `debug` in production)
- Backup credential storage recommendations (HashiCorp Vault, AWS Secrets Manager)
- Container resource limits recommendation:
  ```
  # Recommended: Set memory limits in docker-compose.prod.yml
  # trading-engine: 2GB, mt5-bridge: 512MB, notification: 256MB
  ```
- Pre-deployment verification checklist:
  - [ ] All placeholder values replaced with real credentials
  - [ ] Database connection tested with SSL
  - [ ] Telegram bot token verified working
  - [ ] No development credentials remain

---

## Architecture Compliance

This story implements:
- **NFR6:** All secrets managed via environment variables
- **Architecture 5.3:** Environment configuration section
- **Architecture Deployment:** Development and production environment separation

**Referenced Sections:**
- [Source: docs/architecture.md#environment-configuration]
- [Source: docs/architecture.md#deployment-architecture]
- [Source: docs/epic-1-context.md#story-1.4]

---

## Previous Story Intelligence

### From Story 1.3 (Completed)

**Key Learnings:**
- Database credentials work: `POSTGRES_DB=trading`, `POSTGRES_USER=trading`, `POSTGRES_PASSWORD=devpassword`
- Container verification pattern: `docker compose -f infra/docker/docker-compose.yml up -d`
- Health checks use environment variables: `pg_isready -U ${POSTGRES_USER:-trading}`

**Files Verified Working:**
- `configs/dev/.env` - Database credentials loaded successfully
- `infra/docker/docker-compose.yml` - Variable substitution works with exports

### From Story 1.2 (Completed)

**Key Learnings:**
- Docker Compose reads environment variables from shell exports or .env files
- SELinux `:z` suffix required for volume mounts on Fedora
- Container naming follows `trading-*` convention

### Git Recent Commits

```
82328cb Implement spec 1 story 1.3
e6ed42f Implement epec 1 story 1.1 1.2
483033f Planning and create architecture document
```

**Patterns Established:**
- Environment variables are exported before docker compose commands
- Current workflow: `export POSTGRES_PASSWORD=devpassword && docker compose up -d`

---

## Dev Agent Guardrails

### MUST DO:

1. **Update `configs/.env.example`** with ALL service variables from Technical Specifications
2. **Preserve existing working values** in `configs/dev/.env` (TradingView, Database)
3. **Add new service variables** with development defaults to `configs/dev/.env`
4. **Create `configs/prod/.env.example`** with production security notes
5. **Add `env_file` directive** to docker-compose.yml for cleaner configuration
6. **Test configuration** with `docker compose config` before marking complete

### DO NOT:

1. **Remove or change working TradingView credentials** in dev/.env
2. **Commit actual .env files** - they're in .gitignore
3. **Remove existing default values** from docker-compose.yml (keep `${VAR:-default}`)
4. **Add production secrets** to any file in the repository
5. **Skip the env_file directive** - it's required for cleaner multi-service config
6. **Break existing infrastructure** - test that Redis and TimescaleDB still work
7. **Log or echo credential values** during verification - use existence checks only
8. **Expose secrets in error messages** - mask sensitive values in any output

### File Modification Order:

1. `configs/.env.example` - Add all new variables (expand from 64 to ~100 lines)
2. `configs/dev/.env` - Add new service variables with dev defaults
3. `configs/prod/.env.example` - Create new file with production template
4. `infra/docker/docker-compose.yml` - Add env_file directive

### Variable Naming Conventions:

- Infrastructure: `POSTGRES_*`, `REDIS_*`
- Service-specific: `SERVICE_VARIABLE_NAME` (e.g., `TRADING_MODE`)
- ZeroMQ: `ZMQ_*_PORT`
- Password references: `*_PASSWORD` or `*_TOKEN`

---

## Testing Verification

### Manual Test Steps

```bash
# 1. Navigate to project root
cd /home/hopdev/Dev/Sandboxed

# 2. Verify env_file loads correctly
docker compose -f infra/docker/docker-compose.yml config

# 3. Test infrastructure starts with env file
docker compose -f infra/docker/docker-compose.yml down
docker compose -f infra/docker/docker-compose.yml up -d

# 4. Verify containers are healthy
docker ps --filter "name=trading-" --format "table {{.Names}}\t{{.Status}}"

# 5. Verify database connection still works
docker exec trading-timescaledb pg_isready -U trading -d trading
# Expected: trading-timescaledb:5432 - accepting connections

# 6. Verify Redis connection
docker exec trading-redis redis-cli ping
# Expected: PONG

# 7. Test variable substitution
docker compose -f infra/docker/docker-compose.yml config | grep POSTGRES_DB
# Expected: POSTGRES_DB: trading
```

### Verification Checklist

- [x] `configs/.env.example` contains all variables from Technical Specifications
- [x] `configs/dev/.env` has development defaults for all new variables
- [x] `configs/prod/.env.example` exists with production security notes
- [x] `docker compose config` shows resolved variables without errors
- [x] Infrastructure services start without missing variable errors
- [x] Existing TradingView and Database credentials still work

---

## Dependencies

- **Prerequisites:** Story 1.3 (TimescaleDB Schema) - DONE
- **Blocks:**
  - Story 1.5 (Makefile) - needs env configuration for commands
  - Story 1.6 (Trading Engine) - needs TRADING_MODE and ZMQ variables
  - Story 1.7 (MT5 Bridge) - needs RUST_LOG and ZMQ_* variables
  - Story 1.8 (Notification) - needs TELEGRAM_* variables
  - Story 1.9 (Full Stack) - needs all services configured

---

## Definition of Done

- [x] `configs/.env.example` updated with all service variables (~100 lines)
- [x] `configs/dev/.env` updated with new service variables (development defaults)
- [x] `configs/prod/.env.example` created with production template and security notes
- [x] `infra/docker/docker-compose.yml` updated with `env_file` directive
- [x] `docker compose config` executes without errors
- [x] Infrastructure services (Redis, TimescaleDB) start and pass health checks
- [x] All existing functionality preserved (database connection, Redis ping)
- [x] Story status updated to `review` in sprint-status.yaml

---

## File List

**Files to Create:**
- `configs/prod/.env.example` - Production environment template

**Files to Modify:**
- `configs/.env.example` - Add all service variables
- `configs/dev/.env` - Add new service variables with dev defaults
- `infra/docker/docker-compose.yml` - Add env_file directive

**Files NOT to Modify:**
- `infra/timescaledb/init.sql` - Complete from Story 1.3
- `.gitignore` - Already ignores .env files correctly
- Any service source code files

---

## References

- [Architecture - Environment Configuration](../architecture.md#environment-configuration)
- [Architecture - Docker Compose Configuration](../architecture.md#service-configuration)
- [Epic 1 Context - Story 1.4](../epic-1-context.md#story-14-environment-configuration-setup)
- [Story 1.3 - TimescaleDB Schema](./1-3-timescaledb-schema-initialization.md)
- [Docker Compose env_file documentation](https://docs.docker.com/compose/environment-variables/set-environment-variables/#use-the-env_file-attribute)

---

## Dev Agent Record

### Context Reference

- Epic 1 Context: `docs/epic-1-context.md`
- Architecture: `docs/architecture.md` (Environment Configuration, Docker Compose sections)
- Previous Story: `docs/sprint-artifacts/1-3-timescaledb-schema-initialization.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Docker Compose config verification: `docker compose -f infra/docker/docker-compose.yml config` executed successfully
- Variable precedence note: env_file loads variables INTO container, but `${VAR}` in environment section looks for shell variables first. Added fallback default `${POSTGRES_PASSWORD:-devpassword}` for compatibility.
- Infrastructure health verification: Both containers (trading-redis, trading-timescaledb) report healthy status

### Completion Notes List

1. **Task 1 (AC1):** Updated `configs/.env.example` from 64 lines to 143 lines with comprehensive documentation for all services including Trading Engine (TRADING_MODE, ZMQ_*), MT5 Bridge (RUST_LOG, ZMQ_REQ_PORT), Notification (TELEGRAM_*), and detailed security notes.

2. **Task 2 (AC2):** Updated `configs/dev/.env` with all new service variables. Preserved existing TradingView credentials (SESSION_ID, SESSION_SIGN) and database credentials. Added development defaults: TRADING_MODE=paper, RUST_LOG=debug, LOG_LEVEL=debug, LOG_FORMAT=text. Telegram credentials use placeholder values.

3. **Task 3 (AC3):** Created `configs/prod/.env.example` with comprehensive production documentation including: pre-deployment verification checklist, 24-character password requirements, SSL/TLS configuration hints, LOG_LEVEL=warn default, container resource limit recommendations, and secrets management guidance.

4. **Task 4 (AC4):** Updated docker-compose.yml with explicit environment variables per service (principle of least privilege). Added documentation header explaining variable precedence. Uses `${VAR:-default}` pattern for shell variable substitution with fallbacks.

   **Code Review Fix (2025-12-19):** Removed `env_file` directive which was leaking ALL environment variables (including TradingView tokens, Telegram credentials) into the TimescaleDB container. Now each service only receives the variables it needs.

5. **Task 5:** Verified configuration with `docker compose config` showing only database variables for timescaledb. Infrastructure services started successfully with both containers (trading-redis, trading-timescaledb) passing health checks. Database accepting connections (`pg_isready`), Redis responding to PING.

### File List

**Files Created:**
- `configs/prod/.env.example` - Production environment template with security guidance

**Files Modified (tracked by git):**
- `configs/.env.example` - Expanded from 64 to 143 lines with all service variables
- `infra/docker/docker-compose.yml` - Added documentation header, explicit environment variables per service

**Files Updated (not tracked by git - per .gitignore):**
- `configs/dev/.env` - Contains Trading Engine, MT5 Bridge, Notification service variables with dev defaults. Intentionally excluded from git to protect credentials.

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-19 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-19 | **Validation improvements applied:** Added ZMQ port architecture clarification; Added Docker Compose variable precedence documentation; Expanded production template security guidance with SSL hints, log level recommendations, and pre-deployment checklist; Added REDIS_URL alternative notation; Added credential security guardrails (no logging/echoing secrets) |
| 2025-12-19 | **Implementation complete:** All 5 tasks completed. Created configs/prod/.env.example, updated configs/.env.example (143 lines), configs/dev/.env with all service variables, docker-compose.yml with env_file directive. Infrastructure verified healthy. |
| 2025-12-19 | **Code Review Fixes:** (1) Removed env_file directive - was leaking all credentials to timescaledb container; (2) Removed obsolete version key from docker-compose.yml (deprecated in Compose 2.x); (3) Redacted credentials from story doc; (4) Clarified dev/.env is intentionally not git-tracked; (5) Updated verification checklist; (6) Fixed arrow characters in .env.example |

---

## Notes

- This story focuses on environment configuration ONLY
- No service code changes required
- All secrets must use environment variables (NFR6)
- Production .env.example is a TEMPLATE - never contains real secrets
- env_file directive provides cleaner configuration than shell exports
- Docker Compose 2.x supports env_file with relative paths from compose file location
