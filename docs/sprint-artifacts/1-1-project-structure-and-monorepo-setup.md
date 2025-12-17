# Story 1.1: Project Structure and Monorepo Setup

**Epic:** 1 - Foundation & Infrastructure
**Status:** Done
**Created:** 2025-12-17

---

## User Story

As a **developer**,
I want **the monorepo structure established with service directories**,
So that **I can develop independent services with clear boundaries**.

---

## Context

This is the first story in Epic 1 and establishes the foundational project structure. The tv-api service already exists and is complete. This story focuses on:
1. Verifying the existing structure matches architecture spec
2. Creating placeholder files in empty service directories
3. Adding language-specific configuration files

**Reference:** [Epic 1 Context](../epic-1-context.md)

---

## Current State

```
services/
├── tv-api/              # ✅ COMPLETE - 35+ Go files
├── mt5-bridge/          # ❌ EMPTY directories only
│   ├── src/
│   └── tests/
├── trading-engine/      # ❌ EMPTY directories only
│   ├── src/
│   └── tests/
└── notification/        # ❌ EMPTY directories only
    ├── cmd/
    └── internal/
```

---

## Acceptance Criteria

### AC1: Directory Structure Verification
**Given** I clone the repository
**When** I examine the directory structure
**Then** I see the following structure:
```
Sandboxed/
├── services/
│   ├── tv-api/           # Existing Go service
│   ├── mt5-bridge/       # New Rust service
│   ├── trading-engine/   # New Python service
│   └── notification/     # New Go service
├── infra/
│   ├── docker/
│   ├── redis/
│   ├── timescaledb/
│   └── scripts/
├── configs/
│   ├── .env.example
│   ├── dev/
│   └── prod/
├── scripts/
├── Makefile
└── README.md
```

### AC2: Service Directory Contents
**Given** each service directory exists
**When** I examine it
**Then** it contains:
- Dockerfile (placeholder or functional)
- README.md with service description
- Language-specific dependency files:
  - Go: go.mod
  - Rust: Cargo.toml
  - Python: pyproject.toml

### AC3: Gitignore Files
**Given** each service directory exists
**When** I check for .gitignore
**Then** language-appropriate ignores are configured:
- Go: bin/, *.exe, vendor/
- Rust: target/, Cargo.lock (optional)
- Python: __pycache__/, .venv/, *.pyc, .uv/

### AC4: tv-api Preservation
**Given** tv-api is already complete
**When** I complete this story
**Then** no files in tv-api are modified or removed

---

## Tasks

### Task 1: Verify Existing Structure
- [x] Confirm all directories from architecture spec exist
- [x] Document any discrepancies between current state and spec
- [x] Verify tv-api has complete structure (do not modify)

### Task 2: Create mt5-bridge Placeholders
- [x] Create `services/mt5-bridge/Cargo.toml` with basic config
- [x] Create `services/mt5-bridge/src/main.rs` with minimal entry point
- [x] Create `services/mt5-bridge/src/lib.rs` placeholder
- [x] Create `services/mt5-bridge/Dockerfile` placeholder
- [x] Create `services/mt5-bridge/README.md`
- [x] Create `services/mt5-bridge/.gitignore`

### Task 3: Create trading-engine Placeholders
- [x] Create `services/trading-engine/pyproject.toml` with basic config
- [x] Create `services/trading-engine/src/__init__.py`
- [x] Create `services/trading-engine/src/__main__.py` with minimal entry
- [x] Create `services/trading-engine/Dockerfile` placeholder
- [x] Create `services/trading-engine/README.md`
- [x] Create `services/trading-engine/.gitignore`

### Task 4: Create notification Placeholders
- [x] Create `services/notification/go.mod`
- [x] Create `services/notification/cmd/bot/main.go` with minimal entry
- [x] Create `services/notification/Dockerfile` placeholder
- [x] Create `services/notification/README.md`
- [x] Create `services/notification/.gitignore`

### Task 5: Create Root Makefile Placeholder
- [x] Create root `Makefile` with help target only
- [x] Add comment noting full implementation in Story 1.5

### Task 6: Verify and Update Root README
- [x] Ensure README.md exists with project overview
- [x] Add section pointing to docs/ for detailed documentation

---

## Technical Notes

### mt5-bridge (Rust)
```toml
# Cargo.toml minimum
[package]
name = "mt5-bridge"
version = "0.1.0"
edition = "2021"

[dependencies]
# Dependencies added in Story 1.7
```

### trading-engine (Python)
```toml
# pyproject.toml minimum
[project]
name = "trading-engine"
version = "0.1.0"
requires-python = ">=3.11"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### notification (Go)
```go
// go.mod minimum
module github.com/user/sandboxed/services/notification

go 1.21
```

### Dockerfile Placeholder Template
```dockerfile
# Placeholder - Full implementation in Story 1.x
FROM alpine:latest
CMD ["echo", "Service not yet implemented"]
```

---

## Dependencies

- **Prerequisites:** None (first story)
- **Blocks:** Stories 1.6, 1.7, 1.8 (service scaffolds)

---

## Definition of Done

- [x] All directories from architecture spec exist
- [x] Each service has: Dockerfile, README.md, dependency file, .gitignore
- [x] tv-api remains unchanged
- [x] Root Makefile exists (placeholder)
- [ ] All files committed to repository
- [x] Story status updated to `done` in sprint-status.yaml

---

## File List

**New Files:**
- `services/mt5-bridge/Cargo.toml`
- `services/mt5-bridge/src/main.rs`
- `services/mt5-bridge/src/lib.rs`
- `services/mt5-bridge/Dockerfile`
- `services/mt5-bridge/README.md`
- `services/mt5-bridge/.gitignore`
- `services/trading-engine/pyproject.toml`
- `services/trading-engine/src/__init__.py`
- `services/trading-engine/src/__main__.py`
- `services/trading-engine/Dockerfile`
- `services/trading-engine/README.md`
- `services/trading-engine/.gitignore`
- `services/notification/go.mod`
- `services/notification/cmd/bot/main.go`
- `services/notification/Dockerfile`
- `services/notification/README.md`
- `services/notification/.gitignore`
- `Makefile`

**Modified Files:**
- `README.md` (rewritten with correct project overview)
- `docs/sprint-artifacts/sprint-status.yaml`
- `docs/sprint-artifacts/1-1-project-structure-and-monorepo-setup.md`

---

## Dev Agent Record

### Implementation Date
2025-12-17

### Implementation Plan
1. Verified existing directory structure against architecture spec
2. Created mt5-bridge (Rust) placeholder files with Cargo.toml, src/main.rs, src/lib.rs, Dockerfile, README.md, .gitignore
3. Created trading-engine (Python) placeholder files with pyproject.toml, src/__init__.py, src/__main__.py, Dockerfile, README.md, .gitignore
4. Created notification (Go) placeholder files with go.mod, cmd/bot/main.go, Dockerfile, README.md, .gitignore
5. Created root Makefile with help target placeholder
6. Verified root README.md exists with documentation section

### Completion Notes
- All service placeholder files created and verified
- tv-api service remains unmodified (verified timestamps)
- Python module tested and working (`python -m src` outputs expected message)
- Makefile help target working (`make help` outputs expected message)
- All services have language-appropriate .gitignore files
- All Dockerfiles use alpine:latest placeholder pattern

### Code Review Fixes (2025-12-17)
- **FIXED**: Root README.md rewritten with correct Sandboxed Trading System content (was showing old "HFT Data Lakehouse Blueprint" content)
- **FIXED**: Cleaned up __pycache__ directory from trading-engine/src/

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-17 | Story implementation complete - all service placeholders created |
| 2025-12-17 | Code review: Fixed README.md (was wrong project), cleaned __pycache__ |

---

## Notes

- This story creates MINIMAL placeholders only
- Full service implementation happens in Stories 1.6, 1.7, 1.8
- Focus is on structure verification and placeholder creation
- Makefile fully implemented in Story 1.5
