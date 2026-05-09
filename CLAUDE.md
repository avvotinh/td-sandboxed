# Sandboxed Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-11-27

## Active Technologies
- **Python 3.11+** — trading-engine (NautilusTrader 1.x, SQLAlchemy, pyzmq, pydantic)
- **Rust** — mt5-bridge
- **Go** — tv-api (TradingView webhook), notification (Telegram bot)
- **TimescaleDB** (PostgreSQL 16+) — historical data, audit logs
- **Redis 7.2+** — real-time cache, pub/sub
- **ZeroMQ** — inter-service communication (order flow)
- **uv 0.8+** — Python package manager
- **Docker Compose** — local development

## Project Structure

```text
services/
├── trading-engine/    # Python — NautilusTrader, rule engine, risk management
│   ├── src/
│   ├── tests/
│   ├── configs/
│   └── pyproject.toml
├── mt5-bridge/        # Rust — MetaTrader 5 bridge
│   ├── src/
│   ├── tests/
│   └── Cargo.toml
├── tv-api/            # Go — TradingView webhook receiver
│   ├── cmd/
│   ├── internal/
│   ├── pkg/
│   └── go.mod
└── notification/      # Go — Telegram bot notifications
    ├── cmd/
    ├── internal/
    └── go.mod
docs/
├── architecture.md
├── prd.md
├── sprint-artifacts/
└── team-setup-guide.md
configs/               # FTMO presets, shared config
```

## Commands

```bash
# Trading engine (Python)
cd services/trading-engine && uv run pytest
cd services/trading-engine && uv run ruff check .

# Go services
cd services/tv-api && go test ./...
cd services/notification && go test ./...

# Rust mt5-bridge
cd services/mt5-bridge && cargo test

# Docker
docker compose up -d
```

## Code Style

- Python: ruff (line-length 100, target py311), type hints required
- Go: gofmt, go vet, context-first parameters
- Rust: cargo fmt, cargo clippy
- MQL5: `#property strict`, `OnInit/OnTick/OnTimer/OnDeinit` lifecycle, `MqlTradeRequest` API (no MT4 legacy)

<!-- MANUAL ADDITIONS START -->

## ECC Team — Workflow Matrix

| Tình huống | Công cụ ECC |
|---|---|
| Research trước khi implement (GitHub/Context7/web) | `researcher` subagent (hoặc `/research <topic>`) |
| Thiết kế module mới | `architect` subagent |
| Phân rã story thành task | `planner` subagent |
| Viết test trước (TDD) | `tdd-guide` subagent |
| Review code Python | `python-reviewer` subagent |
| Review code Go | `go-reviewer` subagent |
| Review code Rust (mt5-bridge) | `rust-reviewer` subagent |
| Review code MQL5 (mt5 EA — Epic 14) | `mql5-reviewer` subagent |
| Security gate (credentials/network/DB) | `security-reviewer` subagent |
| Review schema / migration | `database-reviewer` subagent |
| Lỗi build Go | `go-build-resolver` subagent |
| Lỗi build Python | Tự fix với context từ `python-patterns` skill |
| Lỗi build Rust | Tự fix với `cargo check` + context từ rules/rust/ |
| Lỗi build MQL5 | Tự fix với `metaeditor64.exe /compile /log` + context từ rules/mql5/ |
| Viết MT5 EA / ZMQ binding (Epic 14) | `mql5-patterns` skill + `mql5-zmq-bridge` skill |
| Refactor sau epic | `refactor-cleaner` subagent |
| Sync docs sống (prd/architecture/epic-context/sprint-status) sau epic/story | `doc-updater` subagent |
| Audit cấu hình ECC | `harness-optimizer` subagent (chạy `/harness-audit` trước) |
| Tra cứu docs NautilusTrader/Redis | `docs-lookup` subagent + Context7 MCP |

## Slash Commands

| Command | Mô tả |
|---|---|
| `/setup` | Hướng dẫn setup project lần đầu (check prerequisites, start infra, migrate, install deps) |
| `/up` | Start tất cả services via Docker Compose |
| `/down` | Stop tất cả services |
| `/health` | Kiểm tra health của Redis, TimescaleDB, và các containers |
| `/migrate` | Chạy database migrations trên TimescaleDB |
| `/test [service]` | Chạy test suite (all hoặc từng service) |
| `/lint` | Chạy linters across tất cả services |
| `/logs [service]` | Xem logs từ containers |
| `/review` | Review tất cả changes trong branch hiện tại |
| `/research <topic>` | Research topic trước khi implement — output vào `docs/research/` |
| `/sprint-status` | Xem trạng thái sprint và suggest next story |
| `/harness-audit` | Audit cấu hình `.claude/` (agents, commands, rules, hooks) |

## ECC Rules

Rules tự động load từ `.claude/rules/` — bao gồm:
- `common/` — quy tắc nền tảng (security, coding style, git workflow, testing, patterns)
- `common/sandboxed-domain.md` — quy tắc đặc thù FTMO (monorepo boundaries, DB discipline, sprint workflow)
- `python/` — Python-specific (PEP 8, async patterns, FTMO rule engine)
- `golang/` — Go-specific (context propagation, error wrapping, tv-api patterns)
- `rust/` — Rust-specific (mt5-bridge: error handling, unsafe, FFI, async)
- `mql5/` — MQL5-specific (MT5 EA: trade operations, ZMQ DLL safety, HMAC, FTMO pre-trade guards)
- `database/` — TimescaleDB / Alembic / audit trail discipline

<!-- MANUAL ADDITIONS END -->
