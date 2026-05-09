# Hướng dẫn sử dụng Claude Code Team — Sandboxed FTMO Trading System

> **Tài liệu này** giải thích cách sử dụng hệ thống agents, skills, commands, rules đã cấu hình cho dự án Sandboxed. Đọc từ đầu đến cuối nếu mới bắt đầu, hoặc nhảy thẳng đến phần use case phù hợp.
>
> **Cập nhật:** 2026-04-18
> **Áp dụng cho:** Mọi developer làm việc trên repo Sandboxed bằng Claude Code

---

## Mục lục

1. [Bắt đầu nhanh (5 phút)](#1-bắt-đầu-nhanh)
2. [Kiến trúc team](#2-kiến-trúc-team)
3. [Slash Commands — Vận hành hàng ngày](#3-slash-commands--vận-hành-hàng-ngày)
4. [Agents — Chuyên gia theo vai trò](#4-agents--chuyên-gia-theo-vai-trò)
5. [Skills — Tri thức chuyên sâu](#5-skills--tri-thức-chuyên-sâu)
6. [Rules — Quy tắc tự động](#6-rules--quy-tắc-tự-động)
7. [Hooks — Kiểm tra tự động](#7-hooks--kiểm-tra-tự-động)
8. [Workflows theo tình huống](#8-workflows-theo-tình-huống)
9. [Quy trình làm story hoàn chỉnh](#9-quy-trình-làm-story-hoàn-chỉnh)
10. [Tips và lưu ý](#10-tips-và-lưu-ý)

---

## 1. Bắt đầu nhanh

### Lần đầu clone repo

```
/setup
```

Command này sẽ tự động:
- Kiểm tra prerequisites (Docker, Go, Rust, Python 3.11+, uv)
- Start Redis + TimescaleDB
- Chạy database migrations
- Install Python dependencies
- Chạy test suite để verify

### Mỗi ngày khi bắt đầu làm việc

```
/up                    # Start tất cả services
/health                # Kiểm tra mọi thứ chạy đúng
/sprint-status         # Xem đang ở đâu, làm gì tiếp
```

### Khi kết thúc ngày

```
/down                  # Stop tất cả services
```

---

## 2. Kiến trúc team

Team được tổ chức thành 4 lớp, mỗi lớp hoạt động khác nhau:

```
┌─────────────────────────────────────────────────┐
│  Commands (/setup, /up, /test, /review, ...)    │  ← Bạn gõ lệnh
│  Tác vụ cụ thể, chạy ngay                       │
├─────────────────────────────────────────────────┤
│  Agents (architect, python-reviewer, ...)       │  ← Claude gọi khi cần chuyên gia
│  Chuyên gia theo vai trò, được delegate task    │
├─────────────────────────────────────────────────┤
│  Skills (python-patterns, ftmo-compliance, ...) │  ← Load tri thức khi cần
│  Gói kiến thức + workflow tái sử dụng           │
├─────────────────────────────────────────────────┤
│  Rules + Hooks                                  │  ← Luôn luôn chạy nền
│  Quy tắc tự động áp dụng mọi lúc                │
└─────────────────────────────────────────────────┘
```

**Nguyên tắc sử dụng:**
- **Commands** — bạn chủ động gọi bằng `/tên-lệnh`
- **Agents** — Claude tự gọi khi phù hợp, hoặc bạn yêu cầu ("hãy dùng python-reviewer review file này")
- **Skills** — Claude tự load khi context cần, hoặc bạn yêu cầu ("load skill ftmo-compliance")
- **Rules** — tự động, không cần gọi, luôn ảnh hưởng đến mọi output của Claude

---

## 3. Slash Commands — Vận hành hàng ngày

### Quản lý infrastructure

| Command | Mô tả | Ví dụ |
|---|---|---|
| `/setup` | Setup project lần đầu: check prerequisites, start infra, migrate DB, install deps, verify | `/setup` |
| `/up` | Start tất cả services via Docker Compose, verify health | `/up` |
| `/down` | Stop tất cả services | `/down` |
| `/health` | Kiểm tra Redis, TimescaleDB, containers, port conflicts | `/health` |
| `/migrate` | Chạy SQL migrations lên TimescaleDB theo thứ tự | `/migrate` |
| `/logs` | Xem container logs, highlight errors | `/logs trading-engine` |

### Kiểm tra code

| Command | Mô tả | Ví dụ |
|---|---|---|
| `/test` | Chạy test suite — tất cả hoặc từng service (`trading-engine` / `tv-api` / `mt5-bridge` / `notification`) | `/test trading-engine` |
| `/lint` | Chạy linters tất cả services (ruff, go vet, cargo clippy) | `/lint` |
| `/review` | Review tất cả changes, gọi agents phù hợp theo ngôn ngữ | `/review` |

### Research & Sprint

| Command | Mô tả | Ví dụ |
|---|---|---|
| `/research <topic>` | Research topic (GitHub + Context7 + web) trước khi code, output vào `docs/research/` | `/research trailing drawdown rule` |
| `/sprint-status` | Xem trạng thái sprint, suggest story tiếp theo | `/sprint-status` |
| `/harness-audit` | Audit cấu hình `.claude/` (agents, commands, rules, hooks) — báo cáo thừa/thiếu/cần update | `/harness-audit` |

---

## 4. Agents — Chuyên gia theo vai trò

### 4.1 Cách gọi agent

Agent được gọi bằng cách mô tả yêu cầu trong prompt. Claude sẽ tự delegate cho agent phù hợp, hoặc bạn có thể chỉ định trực tiếp:

```
Hãy dùng architect subagent thiết kế module risk-management mới

Review file services/trading-engine/src/rules/daily_loss.py bằng python-reviewer

Dùng security-reviewer kiểm tra toàn bộ thay đổi trong branch này
```

### 4.2 Core Team — Agents thường xuyên sử dụng

#### `researcher` — Research trước khi implement
- **Khi nào dùng:** Trước khi implement feature non-trivial, chọn library, hoặc gặp pattern lạ
- **Model:** Sonnet
- **Luồng chuẩn (theo `development-workflow.md`):** GitHub code search → Context7 library docs → web search (chỉ khi thiếu) → grep local codebase
- **Output:** `docs/research/<topic-slug>-<YYYY-MM-DD>.md` (TL;DR + options + code references + open questions)
- **Input cho:** `planner` / `architect` đọc làm nền trước khi design
- **Ví dụ:**
  ```
  /research trailing drawdown rule for FTMO
  /research python TA indicator library comparison
  Dùng researcher tra xem ZeroMQ CURVE auth có library Python nào battle-tested.
  ```

#### `architect` — Kiến trúc sư
- **Khi nào dùng:** Thiết kế module mới, quyết định schema, chọn pattern, đánh giá trade-off
- **Model:** Opus (chất lượng cao nhất)
- **Output:** Architecture Decision Records (ADRs), system design diagrams
- **Ví dụ:**
  ```
  Thiết kế module state-recovery cho trading-engine.
  Cần handle: crash recovery, position reconciliation với MT5, Redis snapshot restore.
  Dùng architect subagent.
  ```

#### `planner` — Phân rã công việc
- **Khi nào dùng:** Nhận story mới cần phân rã thành tasks, ước lượng scope
- **Output:** Task list chi tiết map đến file cụ thể
- **Ví dụ:**
  ```
  Phân rã story 8.1 "Implement position reconciliation" thành tasks.
  Dùng planner subagent.
  ```

#### `tdd-guide` — Hướng dẫn TDD
- **Khi nào dùng:** Bắt đầu implement feature mới, cần viết test trước
- **Output:** Test cases, fixture suggestions, implementation guide theo Red-Green-Refactor
- **Ví dụ:**
  ```
  Tôi cần implement hàm check_daily_loss_limit() trong rule engine.
  Dùng tdd-guide để viết test trước.
  ```

#### `python-reviewer` — Review code Python
- **Khi nào dùng:** Sau khi viết/sửa code Python trong trading-engine
- **Model:** Sonnet (nhanh, đủ tốt cho review)
- **Kiểm tra:** Security (SQL injection, hardcoded secrets), error handling, type hints, async patterns, PEP 8
- **FTMO-specific:** Kiểm tra Redis snapshot usage, rule-engine check, ZeroMQ REQ/REP, `asyncio.wait_for` timeout
- **Ví dụ:**
  ```
  Review file services/trading-engine/src/rules/daily_loss.py
  ```

#### `go-reviewer` — Review code Go
- **Khi nào dùng:** Sau khi viết/sửa code Go trong tv-api hoặc notification
- **Kiểm tra:** Error wrapping, context propagation, goroutine leaks, race conditions
- **FTMO-specific:** Context timeout cho webhook handlers, HMAC signature verification, secrets qua env vars
- **Ví dụ:**
  ```
  Review services/tv-api/internal/handlers/webhook.go bằng go-reviewer
  ```

#### `rust-reviewer` — Review code Rust
- **Khi nào dùng:** Sau khi viết/sửa code Rust trong `mt5-bridge`
- **Kiểm tra:** Memory safety, error handling (`Result`, `?`), `unsafe` blocks, async patterns, ownership/borrowing
- **FTMO-specific:** MT5 credential handling qua `secrecy::Secret`, checked arithmetic cho price/qty math, CURVE auth trên ZeroMQ socket khi bind non-loopback
- **Ví dụ:**
  ```
  Review services/mt5-bridge/src/broker/order.rs bằng rust-reviewer
  ```

#### `security-reviewer` — Kiểm tra bảo mật
- **Khi nào dùng:** Khi code đụng đến credentials, network, DB access, API endpoints
- **Kiểm tra:** OWASP Top 10, hardcoded secrets, SQL injection, SSRF, insecure crypto
- **FTMO-specific:** MT5 credentials, Telegram bot token, ZeroMQ CURVE auth, audit trail completeness
- **Ví dụ:**
  ```
  Security review toàn bộ changes trong branch này.
  Đặc biệt chú ý credential handling và ZeroMQ configuration.
  ```

#### `database-reviewer` — Review database
- **Khi nào dùng:** Khi tạo/sửa migration, thay đổi schema, viết query phức tạp
- **Kiểm tra:** Index missing, N+1 queries, data types, constraint policies, transaction length
- **FTMO-specific:** Alembic migration bắt buộc, hypertable retention 180 ngày, double-entry audit logging, `ADD COLUMN NOT NULL` phải tách 3 revision
- **Rules nền:** `rules/database/` (schema.md, timescale.md, audit.md)
- **Ví dụ:**
  ```
  Review migration file services/trading-engine/alembic/versions/009_position_snapshots.py
  bằng database-reviewer
  ```

### 4.3 Build & Fix Agents

#### `go-build-resolver` — Sửa lỗi build Go
- **Khi nào dùng:** `go build` hoặc `go mod tidy` fail trong tv-api/notification
- **Ví dụ:**
  ```
  services/tv-api build fail với lỗi "undefined: WebhookHandler".
  Dùng go-build-resolver fix.
  ```

> **Lưu ý:** Chưa có `python-build-resolver` / `rust-build-resolver`. Với Python dùng context từ skill `python-patterns`; với Rust dùng `cargo check` + rules/rust/.

### 4.4 On-demand Agents

#### `refactor-cleaner` — Dọn dẹp sau epic
- **Khi nào dùng:** Sau khi kết thúc 1 epic, dọn dead code, unused imports, deprecated functions
- **Ví dụ:**
  ```
  Epic 7 (Audit Logging) đã xong. Dùng refactor-cleaner quét dead code
  trong services/trading-engine/src/
  ```

#### `doc-updater` — Sync docs sống
- **Khi nào dùng:** Story done / epic done / architecture thay đổi / new epic / drift audit
- **Scope sở hữu:** `docs/prd.md`, `docs/architecture.md`, `docs/epics.md`, `docs/epic-<N>-context.md`, `docs/sprint-artifacts/sprint-status.yaml`
- **KHÔNG làm:** codemap, story spec (author tự viết), research output (researcher lo), validation-report
- **Nguyên tắc:** minimum diff — chỉ sửa phần thật sự thay đổi
- **Ví dụ:**
  ```
  Vừa merge story 8.8. Dùng doc-updater sync sprint-status.yaml và epic-8-context.md.

  Epic 8 đã done — dùng doc-updater update epics.md, prd.md roadmap,
  và architecture.md nếu có thay đổi topology.

  Bắt đầu epic 9 "Multi-account dashboard". Dùng doc-updater scaffold
  docs/epic-9-context.md và block trong sprint-status.yaml.
  ```

#### `docs-lookup` — Tra cứu documentation
- **Khi nào dùng:** Cần tìm cách sử dụng NautilusTrader, Redis, ZeroMQ, Tokio, crate Rust... API
- **Model:** Haiku (lightweight, high-frequency — tối ưu cost)
- **Kết hợp:** Context7 MCP server để fetch docs mới nhất
- **Ví dụ:**
  ```
  Tra cứu NautilusTrader API cho position management.
  Dùng docs-lookup.
  ```

#### `harness-optimizer` — Audit cấu hình Claude Code
- **Khi nào dùng:** Khi cần review/tối ưu setup agents, hooks, rules
- **Workflow:** Chạy `/harness-audit` trước để lấy baseline, rồi áp dụng fix tối thiểu
- **Ví dụ:**
  ```
  Audit toàn bộ cấu hình .claude/ — có gì thừa, thiếu, hoặc cần update?
  Dùng harness-optimizer.
  ```

---

## 5. Skills — Tri thức chuyên sâu

Skills là gói kiến thức được load vào context khi cần. Không tự chạy — cần được tham chiếu.

### 5.1 Cách sử dụng skill

```
Load skill python-testing rồi viết test cho module rule-engine

Dùng knowledge từ ftmo-compliance skill để verify hàm check_daily_loss()

Tham chiếu docker-patterns skill để viết Dockerfile cho trading-engine
```

### 5.2 Danh sách skills

#### Development patterns

| Skill | Nội dung | Dùng khi |
|---|---|---|
| `python-patterns` | Decorators, async/await, context managers, dataclasses, package organization | Viết code Python mới |
| `python-testing` | pytest fixtures, parametrize, mocking, async testing, coverage | Viết test Python |
| `golang-patterns` | Context propagation, error handling, interfaces, channel patterns | Viết code Go mới |
| `golang-testing` | Table-driven tests, httptest, testify, mocking, benchmarks | Viết test Go |
| `docker-patterns` | Multi-stage builds, healthchecks, compose patterns, volume management | Sửa Dockerfile / docker-compose |
| `api-design` | REST conventions, versioning, error responses, pagination, authentication | Thiết kế API endpoints |

> **Rust:** Chưa có skill dedicated. Dùng `docs-lookup` + Context7 để tra crate docs; idiom/convention có trong `rules/rust/`.

#### Database & Infrastructure

| Skill | Nội dung | Dùng khi |
|---|---|---|
| `database-migrations` | Alembic patterns, TimescaleDB hypertables, rollback strategies, zero-downtime migrations | Tạo migration mới |

#### Quality & Security

| Skill | Nội dung | Dùng khi |
|---|---|---|
| `security-review` | OWASP checklist, credential scanning, cloud infrastructure security, remediation patterns | Security audit |
| `ftmo-compliance` | Daily loss limit, max drawdown, audit trail checklist — đặc thù FTMO | Sửa rule engine, risk limits |

#### Workflow & Operations

| Skill | Nội dung | Dùng khi |
|---|---|---|
| `iterative-retrieval` | Tìm context hiệu quả trong monorepo lớn, chunking strategies | Debug phức tạp cần nhiều context |
| `local-dev` | Quick start, per-service commands, env vars, Docker Compose, troubleshooting | Gặp vấn đề khi chạy local |

---

## 6. Rules — Quy tắc tự động

Rules nằm trong `.claude/rules/` và **tự động load** vào mọi session Claude Code. Không cần gọi.

### 6.1 Cấu trúc

```
.claude/rules/
├── common/                     # Áp dụng cho mọi ngôn ngữ
│   ├── coding-style.md         # Naming, formatting, file size limits
│   ├── git-workflow.md         # Branch naming, commit message, PR
│   ├── testing.md              # Coverage, test pyramid
│   ├── security.md             # Secrets, injection, network + FTMO-specific
│   ├── patterns.md             # Immutability, pure functions
│   ├── performance.md          # Đo trước khi tối ưu
│   ├── agents.md               # Khi nào delegate cho subagent
│   ├── hooks.md                # Hook integration
│   ├── code-review.md          # Review standards
│   ├── development-workflow.md # Dev process
│   └── sandboxed-domain.md     # ★ Rules đặc thù FTMO
│
├── python/                     # Áp dụng khi làm việc với .py files
│   ├── coding-style.md         # PEP 8, ruff, naming
│   ├── patterns.md             # Dataclass, async + FTMO rule engine
│   ├── testing.md              # pytest, fixtures
│   ├── hooks.md                # PostToolUse cho ruff
│   └── security.md             # bandit, pip-audit
│
├── golang/                     # Áp dụng khi làm việc với .go files
│   ├── coding-style.md         # gofmt, effective Go
│   ├── patterns.md             # Context, error wrapping, functional options
│   ├── testing.md              # Table-driven tests, -race
│   ├── hooks.md                # PostToolUse cho gofmt -w + go vet
│   └── security.md             # govulncheck, gosec, context timeouts
│
├── rust/                       # Áp dụng khi làm việc với .rs files (mt5-bridge)
│   ├── coding-style.md         # rustfmt, clippy, thiserror/anyhow
│   ├── patterns.md             # Newtype, typestate, async/Tokio, FFI
│   ├── testing.md              # cargo test, proptest, llvm-cov
│   ├── hooks.md                # PostToolUse cho cargo fmt --check
│   └── security.md             # cargo audit, secrecy, unsafe discipline
│
└── database/                   # Áp dụng với Alembic migrations + TimescaleDB
    ├── schema.md               # Alembic discipline, destructive ops, indexing
    ├── timescale.md            # Hypertable, retention, compression, continuous aggregates
    └── audit.md                # Double-entry audit trail, correlation IDs
```

### 6.2 Rules đặc thù FTMO (`common/sandboxed-domain.md`)

Đây là rules quan trọng nhất — bất kỳ code nào Claude viết đều phải tuân thủ:

- **Monorepo boundaries:** Services không import lẫn nhau trực tiếp, chỉ giao tiếp qua ZeroMQ/Redis
- **Database discipline:** Mọi schema change qua Alembic migration, hypertable retention 180 ngày
- **Sprint workflow:** Mỗi commit = 1 story, format `Implement spec <epic> story <story>`
- **FTMO compliance:** Ngưỡng daily loss / max drawdown load từ config, không hardcode

### 6.3 Ảnh hưởng thực tế

Khi rules hoạt động, Claude sẽ **tự động**:
- Từ chối hardcode credentials — đề xuất `settings.get_secret()` (Python) / `std::env::var` + `secrecy::Secret` (Rust)
- Dùng `asyncio.sleep()` thay vì `time.sleep()` trong async code
- Wrap MT5 calls trong `asyncio.wait_for(timeout=5.0)`
- Dùng REQ/REP cho ZeroMQ order flow, không dùng PUSH/PULL
- Đọc balance/equity từ Redis snapshot, không tính lại từ trade history
- Ghi `audit_log` trong cùng transaction trước khi write vào `account.*`
- Tách `ADD COLUMN NOT NULL` thành 3 revision (add nullable → backfill → set NOT NULL)
- Trong Rust: không `unwrap()` ngoài `main.rs`/tests; mỗi `unsafe` kèm `// SAFETY:` comment

---

## 7. Hooks — Kiểm tra tự động

Hooks cấu hình trong `.claude/settings.local.json` (gitignored, mỗi dev có bản riêng). Các hook hiện đang kích hoạt chạy sau mỗi lần Claude Edit/Write:

| Trigger | Hook | Hành động |
|---|---|---|
| `*.py` edit | `ruff check` | Per-service `uv run ruff check <file>` khi file nằm trong `services/<svc>/`, fallback về repo-root ruff. Giới hạn 20 dòng output. |
| `*.go` edit | `gofmt -w` + `go vet ./...` | Auto-format file tại chỗ; `go vet` chạy trong thư mục package của file vừa sửa (10 dòng đầu). |
| `*.rs` edit | `cargo fmt --check` | Đi ngược lên tìm `Cargo.toml` gần nhất rồi check format. Không auto-fix để tránh conflict với IDE save. |

**Ý nghĩa thực tế:**
- Mỗi khi Claude sửa code, lint/format feedback hiện ngay trong output, và Claude sẽ tự fix trước khi tiếp tục.
- Hooks thất bại (missing tool, Cargo.toml không tìm thấy) **không** chặn flow — chỉ in warning.

**Chưa bật (thêm tay nếu muốn):**
- Python: `mypy` / `pyright` type-check, `black` format
- Go: `goimports`, `staticcheck`
- Rust: `cargo clippy` (chậm — nên chạy pre-commit thay vì mỗi edit)

---

## 8. Workflows theo tình huống

### 8.1 Implement feature mới cho trading-engine (Python)

```
# 1. Xem story cần làm
/sprint-status

# 2. Research (nếu non-trivial — bỏ qua nếu rõ ràng)
/research position reconciliation patterns for MT5
# → docs/research/position-reconciliation-2026-04-18.md

# 3. Phân rã story thành tasks (planner đọc research output)
Phân rã story 8.1 "Position reconciliation" thành tasks. Dùng planner.
Tham chiếu docs/research/position-reconciliation-2026-04-18.md.

# 4. Nếu cần thiết kế — gọi architect
Thiết kế module reconciliation: cần so sánh positions trong
trading-engine vs MT5, detect mismatches, auto-correct.
Dùng architect.

# 5. Viết test trước — gọi tdd-guide
Viết test cho hàm reconcile_positions(engine_positions, mt5_positions).
Dùng tdd-guide.

# 6. Implement (Claude tự viết, ruff hook tự chạy)
Implement hàm reconcile_positions() theo test vừa viết.

# 7. Review
/review

# 8. Test
/test trading-engine

# 9. Security check (nếu đụng credentials/network)
Dùng security-reviewer kiểm tra changes.

# 10. Sync docs
Dùng doc-updater mark story 8.1 done trong sprint-status.yaml
và epic-8-context.md.
```

**Khi nào skip research (step 2):**
- Story "giống hệt" story trước (VD thêm rule tương tự daily-loss)
- Đã có file `docs/research/<topic>-*.md` còn current
- Answer là 10-phút-Google

### 8.2 Thêm endpoint mới cho tv-api (Go)

```
# 1. Thiết kế API
Thiết kế endpoint POST /api/v1/signals cho tv-api.
Nhận TradingView webhook, validate, forward qua ZeroMQ.
Load skill api-design.

# 2. Implement
Implement handler và routing cho endpoint /api/v1/signals
trong services/tv-api/

# 3. Review
Review services/tv-api/ bằng go-reviewer.
Chú ý context propagation và error wrapping.

# 4. Test
/test tv-api
```

### 8.3 Sửa mt5-bridge (Rust)

```
# 1. Tra crate docs nếu cần
Dùng docs-lookup tra cứu tokio-tungstenite reconnect patterns.

# 2. Viết test trước
Dùng tdd-guide viết test cho hàm place_order() xử lý
partial fill + timeout. Load rules/rust/testing.md context.

# 3. Implement — cargo fmt hook tự chạy sau edit
Implement logic retry với exponential backoff trong OrderExecutor.

# 4. Review
Review services/mt5-bridge/src/broker/ bằng rust-reviewer.
Đặc biệt chú ý unsafe blocks và credential handling.

# 5. Test
/test mt5-bridge
```

### 8.4 Tạo database migration mới

```
# 1. Thiết kế schema
Cần thêm table position_snapshots cho reconciliation.
Load skill database-migrations. Dùng database-reviewer review thiết kế.

# 2. Tạo migration file
Tạo revision Alembic mới trong
services/trading-engine/alembic/versions/
cho position_snapshots (hypertable, 180d retention).

# 3. Review
Review migration bằng database-reviewer.
Kiểm tra: indexes, data types, hypertable config, retention policy,
ADD COLUMN NOT NULL split đúng chưa.

# 4. Apply
/migrate
```

### 8.5 Debug production issue

```
# 1. Xem logs
/logs trading-engine

# 2. Nếu cần tìm context trong codebase
Load skill iterative-retrieval.
Tìm tất cả nơi gọi account.balance trong trading-engine.

# 3. Nếu cần tra cứu docs
Dùng docs-lookup tra cứu NautilusTrader error handling cho
PositionClosed event.

# 4. Fix + review
# ... fix code ...
/review
/test trading-engine
```

### 8.6 Sửa lỗi build

```
# Go build fail
services/tv-api build fail. Dùng go-build-resolver fix.

# Python dependency conflict
trading-engine không cài được NautilusTrader.
Load skill python-patterns, check pyproject.toml compatibility.

# Rust build fail
cd services/mt5-bridge && cargo check --all-features
# Claude tự đọc error, sửa theo rules/rust/coding-style.md
```

### 8.7 Refactor sau khi kết thúc epic

```
# 1. Quét dead code
Dùng refactor-cleaner quét services/trading-engine/src/
Tìm: unused imports, dead functions, deprecated code từ epic 7.

# 2. Update docs
Dùng doc-updater sync architecture.md với code hiện tại.

# 3. Full review
/lint
/test
```

### 8.8 Security audit trước release

```
# 1. Full security scan
Dùng security-reviewer scan toàn bộ repo.
Chú ý: credential leaks, SQL injection, ZeroMQ auth, audit trail gaps.

# 2. FTMO compliance check
Load skill ftmo-compliance.
Verify: daily loss limit, max drawdown, audit trail completeness
cho tất cả rule engine functions.

# 3. Database security
Dùng database-reviewer kiểm tra: constraints, connection security,
migration safety, audit trail completeness.
```

### 8.9 Audit & tối ưu cấu hình Claude Code

```
# 1. Chạy audit
/harness-audit

# 2. Áp dụng fix
Dùng harness-optimizer fix các issue HIGH/MEDIUM đã báo cáo.
```

### 8.10 Onboarding developer mới

```
# 1. Setup environment
/setup

# 2. Hiểu kiến trúc
Giải thích kiến trúc dự án Sandboxed. Dùng architect.

# 3. Hiểu sprint hiện tại
/sprint-status

# 4. Chạy thử
/up
/health
/test
```

---

## 9. Quy trình làm story hoàn chỉnh

```
┌─────────────────────────────────────────┐
│  /sprint-status  →  Chọn story          │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  /research <topic>  (nếu non-trivial)   │
│  → docs/research/<slug>-<date>.md       │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  planner subagent  →  Phân rã tasks     │
│  (đọc research output nếu có)           │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  architect subagent (nếu cần thiết kế)  │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  tdd-guide subagent  →  Viết test trước │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  Implement code                         │
│  (hooks tự động: ruff / gofmt / cargo)  │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  /review  →  python/go/rust-reviewer    │
│  security-reviewer (nếu đụng security)  │
│  database-reviewer (nếu đụng schema)    │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  /test  →  Chạy test suite              │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  Commit + PR                            │
│  doc-updater → sync sprint-status.yaml  │
│  + epic-N-context.md                    │
└─────────────────────────────────────────┘
```

---

## 10. Tips và lưu ý

### Song song hoá

Claude có thể gọi nhiều agents đồng thời. Tận dụng bằng cách yêu cầu rõ:

```
Review đồng thời:
- services/trading-engine/ bằng python-reviewer
- services/tv-api/ bằng go-reviewer
- services/mt5-bridge/ bằng rust-reviewer
```

### Khi nào KHÔNG cần gọi agent

- Sửa lỗi nhỏ, rõ ràng → Claude tự fix được
- Thay đổi config/yaml → không cần review agent
- Commit message, git operations → Claude tự xử lý

### Khi nào BẮT BUỘC gọi agent

- Feature non-trivial hoặc chọn library mới → `researcher` (trước khi plan/implement)
- Thay đổi kiến trúc (thêm service, đổi communication pattern) → `architect`
- Code đụng credentials, API keys, tokens → `security-reviewer`
- Tạo/sửa database migration → `database-reviewer`
- Thay đổi FTMO rule engine logic → load `ftmo-compliance` skill
- Đụng `unsafe` block trong Rust → `rust-reviewer` + `security-reviewer`
- Story/epic done hoặc thay đổi topology → `doc-updater` (sync sprint-status + docs sống)

### File quan trọng cần biết

| File | Vai trò |
|---|---|
| `CLAUDE.md` | Convention tổng, workflow matrix — Claude luôn đọc |
| `.claude/rules/common/sandboxed-domain.md` | Rules đặc thù FTMO — tự động enforce |
| `.claude/rules/database/*.md` | Alembic + TimescaleDB + audit trail — enforce khi đụng migration |
| `.claude/rules/rust/*.md` | Convention Rust cho `mt5-bridge` |
| `.claude/settings.local.json` | Hooks + permissions — local, không commit |
| `docs/architecture.md` | Kiến trúc hệ thống — agents tham chiếu, `doc-updater` maintain |
| `docs/prd.md` | Product scope + roadmap — `doc-updater` maintain |
| `docs/epics.md` + `docs/epic-<N>-context.md` | Epic index + per-epic tech context — `doc-updater` maintain |
| `docs/sprint-artifacts/sprint-status.yaml` | Trạng thái sprint hiện tại — `doc-updater` maintain |
| `docs/research/` | Research output trước implement — `researcher` ghi vào |
| `configs/ftmo-presets.yaml` | Ngưỡng FTMO (daily loss, max drawdown) |

### Cập nhật và maintain

- **Thêm rule mới:** Tạo file `.md` trong `.claude/rules/common/`, `python/`, `golang/`, `rust/`, hoặc `database/`
- **Thêm agent mới:** Tạo file `.md` trong `.claude/agents/` với frontmatter (name, description, tools, model)
- **Thêm command mới:** Tạo file `.md` trong `.claude/commands/` mô tả workflow
- **Thêm skill mới:** Tạo folder trong `.claude/skills/<name>/SKILL.md` với frontmatter
- **Audit định kỳ:** Chạy `/harness-audit` hàng epic — theo sau là `harness-optimizer` để áp dụng fix

---

## Phụ lục — Quick Reference Card

```
COMMANDS (gõ trực tiếp)              AGENTS (yêu cầu Claude gọi)
─────────────────────────            ──────────────────────────────
/setup         Setup lần đầu         researcher        Research trước code
/up            Start services        architect         Thiết kế
/down          Stop services         planner           Phân rã task
/health        Check health          tdd-guide         Viết test trước
/migrate       Run migrations        python-reviewer   Review Python
/test [svc]    Run tests             go-reviewer       Review Go
/lint          Run linters           rust-reviewer     Review Rust
/logs [svc]    View logs             security-reviewer Security
/review        Review changes        database-reviewer Database
/research ...  Research topic        go-build-resolver Fix build Go
/sprint-status Sprint info           refactor-cleaner  Dọn code
/harness-audit Audit .claude/        doc-updater       Sync docs sống
                                     docs-lookup       Tra docs (Haiku)
                                     harness-optimizer Tối ưu harness
```
