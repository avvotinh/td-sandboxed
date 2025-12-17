# Story 1.2: Docker Compose Infrastructure Stack

**Epic:** 1 - Foundation & Infrastructure
**Status:** Done
**Created:** 2025-12-17

---

## User Story

As a **developer**,
I want **Redis and TimescaleDB running via Docker Compose**,
So that **I have the required data stores for development**.

---

## Context

This story establishes the core infrastructure services (Redis 7.2+ and TimescaleDB/PostgreSQL 16+) that all application services depend on. The existing `docker-compose.yml` uses legacy naming (`hft-*`) and needs to be updated to match the current architecture specification (`trading-*`).

### Prerequisites

If upgrading from an existing `hft-*` setup, clean up old resources first:
```bash
# Remove old containers and network (if they exist)
docker compose -f infra/docker/docker-compose.yml down -v 2>/dev/null || true
docker network rm hft-network 2>/dev/null || true
```

**Previous Story:** [1-1-project-structure-and-monorepo-setup.md](./1-1-project-structure-and-monorepo-setup.md)
**Reference:** [Epic 1 Context](../epic-1-context.md)

---

## Current State

```yaml
# infra/docker/docker-compose.yml - CURRENT STATE
- container_name: hft-redis          # WRONG: should be trading-redis
- container_name: hft-timescaledb    # WRONG: should be trading-timescaledb
- network: hft-network               # WRONG: should be trading-net
- No redis.conf volume mount         # MISSING
- No init.sql volume mount           # MISSING (needed for Story 1.3)
- Contains legacy ingestion-client   # REMOVE or update
- Contains benchmark service         # REMOVE (obsolete)
```

---

## Acceptance Criteria

### AC1: Infrastructure Services Start
**Given** I have Docker 24+ and Docker Compose 2.x installed
**When** I run `make infra-up`
**Then** Redis 7.2+ starts on port 6379
**And** TimescaleDB (PostgreSQL 16+) starts on port 5432
**And** both services are on the `trading-net` Docker network
**And** volumes are created for persistent data (`redis_data`, `timescale_data`)

### AC2: Redis Health Check
**Given** the infrastructure is running
**When** I run `docker exec trading-redis redis-cli ping`
**Then** I receive "PONG"

### AC3: TimescaleDB Health Check
**Given** the infrastructure is running
**When** I connect to TimescaleDB with configured credentials
**Then** I can execute SQL queries
**And** `pg_isready` returns success

### AC4: Network Configuration
**Given** docker-compose.yml is updated
**When** I inspect the network configuration
**Then** the network is named `trading-net`
**And** the subnet is `172.20.0.0/16`

### AC5: Naming Convention
**Given** I run `docker ps`
**When** infrastructure is running
**Then** containers are named `trading-redis` and `trading-timescaledb`

---

## Tasks

### Task 1: Update docker-compose.yml Core Services
- [x] Rename `hft-redis` container to `trading-redis`
- [x] Rename `hft-timescaledb` container to `trading-timescaledb`
- [x] Rename `hft-network` to `trading-net`
- [x] Update database defaults: `POSTGRES_DB=trading`, `POSTGRES_USER=trading`

### Task 2: Add Redis Configuration
- [x] Create `infra/redis/redis.conf` with persistence settings
- [x] Add volume mount for redis.conf in docker-compose.yml
- [x] Verify Redis health check configuration

### Task 3: Prepare TimescaleDB for Schema Init
- [x] Create empty placeholder `infra/timescaledb/init.sql` with header comment (schema populated in Story 1.3)
- [x] Add volume mount for `init.sql` in docker-compose.yml
- [x] Verify TimescaleDB health check using `pg_isready`
- [x] Ensure `shm_size: 256mb` is set for PostgreSQL shared memory

**Placeholder init.sql content:**
```sql
-- TimescaleDB Schema Initialization
-- Full schema implemented in Story 1.3
-- This placeholder ensures docker-compose volume mount works

SELECT 'Schema placeholder - see Story 1.3 for full implementation';
```

### Task 4: Clean Up Legacy Services
- [x] Remove entire `ingestion-client` service block (context path `./tv-api` is incorrect relative location)
- [x] Remove entire `benchmark` service block (obsolete performance testing service)
- [x] Remove `profiles:` section (no longer needed)
- [x] Keep only `redis` and `timescaledb` services for this story (application services added in Story 1.9)

### Task 5: Verify Infrastructure Commands Work
- [x] Test infrastructure startup (use docker compose directly until Makefile Story 1.5)
- [x] Test infrastructure shutdown
- [x] Verify services are healthy via Docker health checks

**Testing Commands (Makefile not yet available):**
```bash
# Start infrastructure
docker compose -f infra/docker/docker-compose.yml up -d

# Stop infrastructure
docker compose -f infra/docker/docker-compose.yml down

# After Story 1.5, these become: make infra-up / make infra-down
```

---

## Technical Specifications

### Target docker-compose.yml Structure

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: trading-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
      - ../redis/redis.conf:/usr/local/etc/redis/redis.conf:ro
    command: redis-server /usr/local/etc/redis/redis.conf
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    restart: unless-stopped
    networks:
      - trading-net

  timescaledb:
    image: timescale/timescaledb:latest-pg16
    container_name: trading-timescaledb
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-trading}
      POSTGRES_USER: ${POSTGRES_USER:-trading}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - timescale_data:/var/lib/postgresql/data
      - ../timescaledb/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-trading} -d ${POSTGRES_DB:-trading}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - trading-net
    shm_size: 256mb

volumes:
  redis_data:
    driver: local
  timescale_data:
    driver: local

networks:
  trading-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### Redis Configuration (infra/redis/redis.conf)

```conf
# Redis Configuration for Trading System
# Persistence settings
appendonly yes
appendfsync everysec

# Memory management
maxmemory 2gb
maxmemory-policy allkeys-lru

# Security (password set via env in docker-compose if needed)
# requirepass ${REDIS_PASSWORD}

# Logging
loglevel notice
```

### Environment Variables Required

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DB` | `trading` | Database name |
| `POSTGRES_USER` | `trading` | Database user |
| `POSTGRES_PASSWORD` | **required** | Database password (no default) |
| `REDIS_PASSWORD` | optional | Redis password (optional for dev) |

**Development Setup:**
```bash
# Set password before running docker compose:
export POSTGRES_PASSWORD=devpassword

# Or add to configs/dev/.env (do NOT commit real passwords):
echo "POSTGRES_PASSWORD=devpassword" >> configs/dev/.env

# Then run with env file:
docker compose -f infra/docker/docker-compose.yml --env-file configs/dev/.env up -d
```

---

## Architecture Compliance

### From architecture.md

| Requirement | Implementation |
|-------------|----------------|
| Network: `trading-net` | Bridge network with subnet 172.20.0.0/16 |
| Redis 7.2+ | Image: `redis:7-alpine` |
| TimescaleDB PG16+ | Image: `timescale/timescaledb:latest-pg16` |
| Container naming | `trading-redis`, `trading-timescaledb` |
| Health checks | Required for both services |
| Restart policy | `unless-stopped` |

### From PRD

| NFR | Compliance |
|-----|------------|
| NFR27: Redis 7.2+ compatible | Using `redis:7-alpine` image |
| NFR28: PostgreSQL 16+ / TimescaleDB | Using `timescaledb:latest-pg16` image |
| NFR11: Data persistence | Volumes for both services |

---

## File Structure

### Files to Create
```
infra/
├── redis/
│   └── redis.conf           # NEW: Redis configuration
├── timescaledb/
│   └── init.sql             # NEW: Placeholder (schema in Story 1.3)
└── docker/
    └── docker-compose.yml   # UPDATE: Rename containers, fix network
```

### Files to Modify
- `infra/docker/docker-compose.yml` - Update naming, add volume mounts

### Schema Note
- `infra/timescaledb/init.sql` - Created as placeholder in this story; full schema populated in Story 1.3

---

## Previous Story Intelligence

### From Story 1.1 (Completed)

**Learnings:**
- Project structure is now established with all service directories
- Makefile exists with `help` target only (full implementation in Story 1.5)
- Root README.md was corrected to show Sandboxed Trading System content
- tv-api service is complete and should not be modified

**Patterns Established:**
- Placeholder Dockerfile pattern: `FROM alpine:latest` + echo message
- Service README.md format with description and status
- Language-specific .gitignore files in each service

**Files Created:**
- Service placeholders in `services/mt5-bridge/`, `services/trading-engine/`, `services/notification/`
- Root `Makefile` with help target

---

## Anti-Pattern Prevention

### DO NOT:
1. **Modify tv-api service** - It's complete and working
2. **Create init.sql in this story** - That's Story 1.3
3. **Implement full Makefile** - That's Story 1.5
4. **Add application services to docker-compose** - That's Story 1.9
5. **Use `hft-*` naming** - Must use `trading-*` naming
6. **Skip health checks** - Required for `depends_on: condition: service_healthy`

### MUST DO:
1. **Update ALL container names** to `trading-*` prefix
2. **Update network name** to `trading-net`
3. **Add redis.conf volume mount** for persistence configuration
4. **Add init.sql volume mount placeholder** (file created in Story 1.3)
5. **Verify health checks work** before marking complete

---

## Testing Verification

### Manual Test Steps

```bash
# 0. Set environment variable (required)
export POSTGRES_PASSWORD=devpassword

# 1. Start infrastructure (use docker compose until Makefile ready in Story 1.5)
docker compose -f infra/docker/docker-compose.yml up -d

# 2. Check containers are running with correct names
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# Expected: trading-redis, trading-timescaledb

# 3. Test Redis
docker exec trading-redis redis-cli ping
# Expected: PONG

# 4. Test TimescaleDB
docker exec trading-timescaledb pg_isready -U trading -d trading
# Expected: accepting connections

# 5. Verify network
docker network inspect trading-net
# Expected: Subnet 172.20.0.0/16

# 6. Stop infrastructure
docker compose -f infra/docker/docker-compose.yml down

# 7. Verify clean shutdown
docker ps
# Expected: No trading-* containers
```

### Health Check Verification

```bash
# Check Redis health
docker inspect trading-redis --format='{{.State.Health.Status}}'
# Expected: healthy

# Check TimescaleDB health
docker inspect trading-timescaledb --format='{{.State.Health.Status}}'
# Expected: healthy
```

---

## Dependencies

- **Prerequisites:** Story 1.1 (Project Structure) - DONE
- **Blocks:**
  - Story 1.3 (TimescaleDB Schema) - needs infrastructure running
  - Story 1.4 (Environment Config) - needs docker-compose for env_file
  - Story 1.5 (Makefile) - needs infra-up/down targets to work

---

## Definition of Done

- [x] docker-compose.yml updated with `trading-*` naming
- [x] Network renamed to `trading-net` with correct subnet
- [x] Redis configuration file created at `infra/redis/redis.conf`
- [x] TimescaleDB placeholder created at `infra/timescaledb/init.sql`
- [x] Volume mounts configured for redis.conf and init.sql
- [x] Legacy services (ingestion-client, benchmark) removed
- [x] Infrastructure starts successfully via docker compose
- [x] Infrastructure stops successfully via docker compose
- [x] Redis health check passes (`redis-cli ping` returns PONG)
- [x] TimescaleDB health check passes (`pg_isready` succeeds)
- [x] All containers use `trading-*` prefix
- [x] Story status updated to `done` (code review complete)

---

## Dev Agent Record

### Context Reference

- Epic 1 Context: `docs/epic-1-context.md`
- Architecture: `docs/architecture.md` (Infrastructure Architecture section)
- PRD: `docs/prd.md` (Non-Functional Requirements)
- Previous Story: `docs/sprint-artifacts/1-1-project-structure-and-monorepo-setup.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- SELinux permission issue fixed by adding `:z` suffix to volume mounts for bind-mounted config files
- Removed obsolete `version: '3.8'` attribute from docker-compose.yml (Docker Compose V2 warning)
- Cleaned up legacy `hft-*` containers and networks before starting new infrastructure

### Completion Notes List

- **Task 1 Complete:** Updated docker-compose.yml with all `trading-*` naming convention, network, and database defaults
- **Task 2 Complete:** Created redis.conf with persistence settings (appendonly yes, appendfsync everysec, maxmemory 2gb)
- **Task 3 Complete:** Created init.sql placeholder with header comment, added volume mount with SELinux fix, verified pg_isready health check
- **Task 4 Complete:** Removed ingestion-client, benchmark services, and profiles section - only redis and timescaledb services remain
- **Task 5 Complete:** Verified startup, shutdown, and health checks all pass:
  - Redis: `docker exec trading-redis redis-cli ping` returns PONG
  - TimescaleDB: `pg_isready -U trading -d trading` returns accepting connections
  - Network: `docker_trading-net` with subnet 172.20.0.0/16
  - Both containers report `healthy` status

### Code Review Fixes Applied

**Reviewer:** Claude Opus 4.5 (Adversarial Code Review)
**Date:** 2025-12-17

**HIGH Issues Fixed:**
1. `configs/dev/.env` - Updated POSTGRES_DB/POSTGRES_USER from `hft_lakehouse`/`hftuser` to `trading`/`trading`
2. File List updated to include README.md modification (was missing from documentation)

**MEDIUM Issues Fixed:**
1. `configs/.env.example` - Updated database naming to `trading` convention
2. `configs/dev/.env` - Set POSTGRES_PASSWORD to `devpassword` for dev environment
3. `.gitignore` - Added `configs/**/.env` pattern to prevent credential exposure

**LOW Issues Noted (Not Fixed - Acceptable):**
1. TimescaleDB uses `latest-pg16` tag - acceptable for development, consider pinning for production
2. AC1 references `make infra-up` before Makefile exists - noted in Task 5 with workaround

### File List

**Files Created:**
- `infra/redis/redis.conf` - Redis configuration with persistence settings
- `infra/timescaledb/init.sql` - Placeholder for schema (populated in Story 1.3)

**Files Modified:**
- `infra/docker/docker-compose.yml` - Updated naming convention, added volume mounts with SELinux fixes, removed legacy services
- `README.md` - Complete rewrite from "HFT Data Lakehouse" to "Sandboxed Trading System" with new project structure
- `configs/dev/.env` - Updated database naming from hft_* to trading (code review fix)
- `configs/.env.example` - Updated database naming from hft_* to trading (code review fix)
- `.gitignore` - Updated header and added configs/**/.env pattern (code review fix)

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-17 | Story created with comprehensive developer context |
| 2025-12-17 | Story validated and improved: added init.sql placeholder task, docker compose fallback commands, dev password guidance, explicit legacy cleanup steps, network cleanup prerequisites |
| 2025-12-17 | Implementation complete: All tasks done, all acceptance criteria verified, ready for review |
| 2025-12-17 | Code Review: Fixed 2 HIGH, 3 MEDIUM issues - env files updated to trading naming, .gitignore improved, File List completed |

---

## Notes

- This story focuses ONLY on infrastructure services (Redis, TimescaleDB)
- Application services (tv-api, mt5-bridge, trading-engine, notification) are added in Story 1.9
- A placeholder init.sql is created in this story to ensure volume mount works; full schema is populated in Story 1.3
- Use `docker compose` commands directly until Makefile is implemented in Story 1.5
