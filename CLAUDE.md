# Sandboxed Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-07-14 (v2 — research-first)

## Active Technologies
- **Python 3.11+** — trading-engine (NautilusTrader 1.x, SQLAlchemy, pyzmq, pydantic)
- **Python + FastAPI** — chart-viewer (đọc Result Contract v2 JSON + parquet, lightweight-charts vendored)
- **Rust** — mt5-bridge
- **TimescaleDB** (PostgreSQL 16+) — historical data, audit logs (chỉ live path — research loop không cần)
- **Redis 7.2+** — real-time cache, pub/sub (chỉ live path)
- **ZeroMQ** — inter-service communication (order flow)
- **uv 0.8+** — Python package manager
- **Docker Compose** — chỉ cho live path (research loop chạy local thuần — Quyết định D6)

## Project Structure

```text
services/
├── trading-engine/    # Python — NautilusTrader, rule engine, risk management
│   ├── src/
│   ├── tests/
│   ├── configs/
│   └── pyproject.toml
├── chart-viewer/      # Python — FastAPI viewer đọc results/*.json (Contract v2), không Docker/DB
│   ├── src/
│   └── pyproject.toml
└── mt5-bridge/        # Rust — MetaTrader 5 bridge
    ├── src/
    ├── tests/
    └── Cargo.toml
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

# Backtest (research loop — không cần Docker/DB)
cd services/trading-engine && uv run python -m src backtest run --job <job.yaml> --export ../../results/

# Chart viewer
cd services/chart-viewer && uv run chart-viewer --results-dir ../../results --port 8777

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
| Review code Rust (mt5-bridge) | `rust-reviewer` subagent |
| Review code MQL5 (mt5 EA — Epic 14) | `mql5-reviewer` subagent |
| Review chiến lược / entry-exit model (chống lookahead, survivorship, overfit, leakage, sizing/fee) | `quant-reviewer` subagent — BẮT BUỘC cho mọi entry/exit model mới trước khi tin backtest |
| Đọc `results/*.json` (Contract v2), sinh verdict vào `docs/v2/studies/` | `backtest-analyst` subagent (hoặc `/study <slug>`) |
| Security gate (credentials/network/DB) | `security-reviewer` subagent |
| Review schema / migration | `database-reviewer` subagent (quay lại ở live path P5) |
| Lỗi build Python | Tự fix với context từ `python-patterns` skill |
| Lỗi build Rust | Tự fix với `cargo check` + context từ rules/rust/ |
| Lỗi build MQL5 | Tự fix với `metaeditor64.exe /compile /log` + context từ rules/mql5/ |
| Viết MT5 EA / ZMQ binding (Epic 14) | `mql5-patterns` skill + `mql5-zmq-bridge` skill |
| Sync docs sống (`docs/v2/*`, studies) sau phase/story | `doc-updater` subagent |
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
| `/backtest <job-yaml>` | Chạy point backtest + export Result Contract v2 vào `results/` — in run_id + metrics |
| `/viewer [run-id]` | Start chart-viewer (port 8777), in URL — kèm run cụ thể nếu có |
| `/study <slug>` | Vòng study trọn gói: backtests với `--export` → `backtest-analyst` sinh verdict vào `docs/v2/studies/` |
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
