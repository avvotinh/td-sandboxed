# Hướng dẫn Setup Team Phát triển - FTMO Automated Trading System

> **Tài liệu này** mô tả các bước chi tiết để xây dựng một team phát triển (dưới dạng subagents + skills + hooks) cho dự án Sandboxed, dựa trên framework [`affaan-m/everything-claude-code`](https://github.com/affaan-m/everything-claude-code) (ECC).
>
> **Ngày tạo:** 2026-04-11
> **Áp dụng cho:** Sandboxed FTMO Multi-Account Trading System
> **Stack:** Python 3.11+ (NautilusTrader), Go (tv-api), Redis 7.2+, TimescaleDB, ZeroMQ, python-telegram-bot

---

## 1. Bối cảnh & Mục tiêu

### 1.1 Hiện trạng dự án
- **Monorepo services:** `trading-engine` (Python), `mt5-bridge` (Python), `notification` (Python), `tv-api` (Go)
- **Tiến độ:** Epic 7 (Audit Logging) gần hoàn thành — story 7.6 vừa commit (`8e054f4`)
- **Branch hiện tại:** `feature/architecture`

### 1.2 Mục tiêu khi áp dụng ECC
1. **Chuyên môn hoá** công việc dev bằng subagents theo vai trò (architect, reviewer, TDD, security...) thay vì 1 main agent xử lý mọi thứ
2. **Song song hoá** các tác vụ độc lập (review Python + review Go đồng thời, build-fix cho nhiều service)
3. **Kỷ luật hoá chất lượng code** qua các hooks tự động (pre-commit, post-edit typecheck, security scan)
4. **Tích luỹ tri thức** qua skills/instincts đặc thù của FTMO domain (risk rules, FTMO presets, MT5 reconciliation...)
5. **Bảo mật** code và cấu hình bằng AgentShield (quét CVE, injection, misconfiguration)

### 1.3 Ba khái niệm cốt lõi của ECC: Agents, Skills, Rules

ECC phân chia tri thức/năng lực thành **3 lớp khác nhau** — rất dễ nhầm, cần phân biệt rõ:

| Lớp | Bản chất | Khi nào kích hoạt | Ví dụ |
|---|---|---|---|
| **Agents** (subagents) | Một nhân vật AI có chuyên môn riêng, được gọi ra để làm 1 việc cụ thể | Khi main agent delegate task (chủ động) | `python-reviewer` review 1 file, `architect` thiết kế module mới |
| **Skills** | Gói tri thức + workflow tái sử dụng, được load vào context khi cần | Khi main agent/subagent `@load` hoặc match trigger (bán tự động) | `python-testing` load pytest fixtures patterns khi viết test |
| **Rules** | Quy tắc/nguyên tắc nền, **luôn luôn** áp dụng cho mọi tác vụ trong project | Tự động, không cần gọi (bị động) | "Không hardcode credentials", "Mọi function async phải có type hint" |

**Tư duy đơn giản:**
- **Rules** = Hiến pháp (luôn có hiệu lực, nền tảng mọi quyết định)
- **Skills** = Giáo trình chuyên đề (load khi cần học chủ đề đó)
- **Agents** = Nhân viên chuyên môn (mời vào họp khi cần ý kiến chuyên gia)

Với dự án Sandboxed, rules đảm bảo mọi dev và mọi AI agent luôn tuân thủ cùng 1 chuẩn (ví dụ: style Python, convention commit, cách xử lý secret) — kể cả khi không gọi subagent nào.

---

## 2. Kiến trúc Team dự kiến

Dưới đây là mapping vai trò team → subagents ECC cho dự án Sandboxed:

### 2.1 Core Team (luôn hoạt động)

| Vai trò | Subagent ECC | Trách nhiệm trong Sandboxed |
|---|---|---|
| **Tech Lead / Architect** | `architect.md` | Thiết kế tương tác giữa tv-api ↔ trading-engine ↔ mt5-bridge; quyết định schema TimescaleDB; topology ZeroMQ |
| **Feature Planner** | `planner.md` | Phân rã story thành task nhỏ; map task sang file cụ thể |
| **Python Lead** | `python-reviewer.md` | Review trading-engine, mt5-bridge, notification — risk rules, async patterns, SQLAlchemy |
| **Go Lead** | `go-reviewer.md` | Review tv-api — HTTP handlers, error wrapping, context propagation |
| **TDD Coach** | `tdd-guide.md` | Enforce test-first cho rule-engine, signal-router, state-recovery |
| **Security Reviewer** | `security-reviewer.md` | Kiểm tra credential leakage (MT5, Telegram token), SQL injection, ZeroMQ auth |
| **Database Reviewer** | `database-reviewer.md` | Validate migrations TimescaleDB, hypertable design, retention policies |
| **Build Fixer (Python)** | `pytorch-build-resolver.md` / custom | Resolve lỗi Poetry, conflict package NautilusTrader |
| **Build Fixer (Go)** | `go-build-resolver.md` | Resolve lỗi `go mod tidy`, vendoring tv-api |
| **Doc Updater** | `doc-updater.md` | Sync `CLAUDE.md`, `architecture.md`, sprint artifacts sau khi merge |

### 2.2 On-demand Specialists

| Tình huống | Subagent |
|---|---|
| Refactor dead code sau epic | `refactor-cleaner.md` |
| E2E test qua Playwright/UI (nếu thêm dashboard) | `e2e-runner.md` |
| Audit toàn bộ hook/settings | `harness-optimizer.md` |
| Debug pipeline autonomous (loops Nautilus backtest) | `loop-operator.md` |
| Tra cứu docs NautilusTrader/Redis | `docs-lookup.md` (kết hợp Context7 MCP) |

### 2.3 Skills cần cài đặt

**Bắt buộc:**
- `python-patterns/` — async, type hints, Poetry
- `python-testing/` — pytest fixtures, mocking ZeroMQ/Redis
- `golang-patterns/` — context, error handling
- `golang-testing/` — table-driven tests, httptest
- `docker-patterns/` — multi-stage, healthcheck
- `database-migrations/` — Alembic + TimescaleDB hypertables
- `api-design/` — REST contract tv-api ↔ external

**Khuyến nghị:**
- `continuous-learning-v2/` — trích xuất instinct từ session dev
- `autonomous-loops/` — backtest/strategy optimization pipelines
- `security-review/` — FTMO compliance checklist
- `iterative-retrieval/` — tìm context hiệu quả trong monorepo lớn

---

## 3. Các bước triển khai chi tiết

### Bước 1 — Chuẩn bị môi trường (15 phút)

```bash
# 1.1 Kiểm tra Node.js (ECC dùng hooks Node-based)
node --version   # >= 18.x
npm --version

# 1.2 Backup cấu hình Claude Code hiện tại
cp -r ~/.claude ~/.claude.backup.$(date +%Y%m%d)

# 1.3 Tạo branch riêng cho việc setup
cd /home/hopdev/Dev/Sandboxed
git checkout -b chore/ecc-team-setup
```

> ⚠️ **Lưu ý:** Backup `~/.claude` trước khi chạy `install.sh` vì script có thể ghi đè hooks/settings sẵn có.

### Bước 2 — Cài ECC Plugin (5 phút)

Trong session Claude Code:

```
/plugin marketplace add https://github.com/affaan-m/everything-claude-code
/plugin install ecc@ecc
```

Sau khi cài xong, kiểm tra:

```
/plugin list
```

Bạn sẽ thấy `ecc@ecc` trong danh sách. Các command sẽ có dạng `/ecc:plan`, `/ecc:review`, ...

### Bước 3 — Cài đặt & tuỳ chỉnh Rules (30 phút)

Đây là bước **quan trọng nhất** trong setup, vì rules ảnh hưởng đến mọi tác vụ của cả team (người + AI).

#### 3.1 Hiểu cấu trúc Rules của ECC

Repo ECC tổ chức rules theo cây thư mục:

```text
rules/
├── common/              # Luôn cài — quy tắc nền tảng, ngôn ngữ-agnostic
│   ├── coding-style.md  # Convention format chung (dòng trống, naming, file size)
│   ├── git-workflow.md  # Branch naming, commit message, PR discipline
│   ├── testing.md       # Yêu cầu coverage, test pyramid
│   ├── performance.md   # Nguyên tắc tối ưu (đo trước khi tối ưu, v.v.)
│   ├── patterns.md      # Design patterns chung (immutability, pure functions)
│   ├── hooks.md         # Cách tích hợp hook vào workflow
│   ├── agents.md        # Hướng dẫn chung khi delegate cho subagent
│   └── security.md      # Best practice security đa ngôn ngữ
│
├── python/              # Cài vì trading-engine, mt5-bridge, notification dùng Python
│   ├── coding-style.md  # PEP 8, ruff, black, naming Pythonic
│   ├── patterns.md      # Dataclass, context manager, async patterns
│   ├── testing.md       # pytest, fixtures, parametrize, mocking
│   ├── hooks.md         # PostToolUse hook cho ruff/mypy
│   └── security.md      # bandit, pip-audit, secrets management
│
├── golang/              # Cài vì service tv-api dùng Go
│   ├── coding-style.md  # gofmt, golangci-lint, effective Go
│   ├── patterns.md      # Context propagation, error wrapping, interface design
│   ├── testing.md       # table-driven tests, httptest, t.Helper
│   ├── hooks.md         # PostToolUse cho go vet / go test
│   └── security.md      # govulncheck, gosec
│
├── typescript/ cpp/ java/ kotlin/ rust/ php/ perl/ dart/ csharp/ swift/
│                        # KHÔNG cài — dự án không dùng
```

**Điểm then chốt:** Mỗi file `<lang>/<topic>.md` **reference chéo** tới `common/<topic>.md` bằng đường dẫn tương đối, ví dụ `[see common/testing.md](../common/testing.md)`. Do đó:

> ⚠️ **PHẢI copy nguyên cả thư mục** (`rules/common`, `rules/python`, `rules/golang`), **KHÔNG copy từng file riêng lẻ**, nếu không các link tương đối sẽ gãy và các file cùng tên sẽ collide.

#### 3.2 Chọn vị trí cài: User-level vs Project-level

ECC hỗ trợ 2 scope cài đặt:

| Scope | Đường dẫn | Ưu | Nhược | Khi nào dùng |
|---|---|---|---|---|
| **User-level** | `~/.claude/rules/` | Áp dụng cho mọi project của dev | Không share được với team; xung đột nếu dev làm nhiều project stack khác nhau | Rule cá nhân (ví dụ: luôn dùng `pnpm`) |
| **Project-level** | `.claude/rules/` (trong repo) | Commit vào git → share với cả team; versioning theo branch; isolate giữa các project | Mỗi project phải cài riêng | **Khuyến nghị cho Sandboxed** |

**Quyết định cho dự án này:** Dùng **Project-level** (`/home/hopdev/Dev/Sandboxed/.claude/rules/`) để toàn team (sau này) có cùng chuẩn khi pull code về.

#### 3.3 Cài đặt Rules cho Sandboxed

```bash
# Clone ECC repo để chạy installer
cd /tmp
git clone https://github.com/affaan-m/everything-claude-code.git
cd everything-claude-code
npm install

# Cách 1: Dùng install.sh với flag target project
./install.sh --scope project --target /home/hopdev/Dev/Sandboxed python golang
# install.sh tự động kèm theo rules/common (luôn cần)

# Cách 2: Copy thủ công (nếu install.sh không hỗ trợ --target)
mkdir -p /home/hopdev/Dev/Sandboxed/.claude/rules
cp -r rules/common  /home/hopdev/Dev/Sandboxed/.claude/rules/
cp -r rules/python  /home/hopdev/Dev/Sandboxed/.claude/rules/
cp -r rules/golang  /home/hopdev/Dev/Sandboxed/.claude/rules/
```

**Xác minh cài đặt:**

```bash
cd /home/hopdev/Dev/Sandboxed
tree .claude/rules -L 2
# Kết quả mong đợi:
# .claude/rules
# ├── common
# │   ├── agents.md
# │   ├── coding-style.md
# │   ├── git-workflow.md
# │   ├── hooks.md
# │   ├── patterns.md
# │   ├── performance.md
# │   ├── security.md
# │   └── testing.md
# ├── python
# │   └── ... (5 file)
# └── golang
#     └── ... (5 file)
```

#### 3.4 Cách Claude Code load Rules

Sau khi đặt đúng vị trí `.claude/rules/` (hoặc `~/.claude/rules/`), **Claude Code tự động load** các file markdown này vào system context khi làm việc trong project. Không cần gọi lệnh gì.

**Thứ tự ưu tiên khi có xung đột:**
1. `.claude/rules/` (project) — ưu tiên cao nhất
2. `~/.claude/rules/` (user)
3. CLAUDE.md convention

**Lưu ý về context window:**
- Mỗi rule file thường ~1-3KB markdown → tổng ~30-50KB cho `common + python + golang`
- Không đáng kể so với context window 1M của Opus 4.6
- Nhưng **đừng copy tất cả** ngôn ngữ — chỉ những ngôn ngữ thực sự dùng

#### 3.5 Review & tuỳ chỉnh Rules cho FTMO domain

Đây là **bước bắt buộc** — không nên dùng rules y nguyên từ ECC upstream vì:
- ECC rules generic, thiếu context FTMO (risk limits, audit trail, credential handling)
- `docs/architecture.md` của Sandboxed có quy định riêng cần tôn trọng

**Quy trình tuỳ chỉnh:**

1. **Đọc từng file trong `common/`** (8 files, mất ~30 phút)
2. Ghi chú các rule nào:
   - ✅ Giữ nguyên
   - ✏️ Sửa đổi (thêm/bớt)
   - ❌ Xoá (không áp dụng cho stack hiện tại)
3. **Thêm các rule đặc thù Sandboxed** vào cuối file `common/security.md` và `python/patterns.md`

**Ví dụ — thêm vào `common/security.md`:**

```markdown
## Project-specific: Sandboxed FTMO

### Credentials handling
- **NEVER** hardcode: MT5 credentials, Telegram bot token, Redis password, DB password
- All secrets loaded via `settings.get_secret(key)` → backed by env vars / vault
- Secrets lookup MUST fail loudly (raise `ConfigError`) if missing — never silently default

### Financial data integrity
- Account balance/equity reads: Redis snapshot only (key: `account:{id}:snapshot`)
- NEVER recompute balance from trade history in hot path — use Redis hwm cache
- All write paths to `account.*` tables MUST go through `audit_log` write first (double-entry)

### Network boundary
- ZeroMQ sockets MUST use CURVE auth when exposed beyond localhost
- Order flow: REQ/REP only (not PUSH/PULL) — requires ack guarantee
- Telegram webhook: verify HMAC signature before processing
```

**Ví dụ — thêm vào `python/patterns.md`:**

```markdown
## Project-specific: Sandboxed FTMO

### Rule engine
- Every rule check function: `def check(context: RuleContext) -> RuleResult`
- RuleResult MUST be immutable (`@dataclass(frozen=True)`)
- Rule violation MUST log to `rule_check_log` hypertable before raising

### Async patterns
- `asyncio.gather()` for independent calls; `asyncio.wait()` with timeout for external APIs
- MT5 bridge calls: always wrap in `asyncio.wait_for(timeout=5.0)` to prevent hang
- NEVER use `time.sleep()` in async code — use `asyncio.sleep()`
```

#### 3.6 Viết Rule riêng cho project (tuỳ chọn nhưng khuyến nghị)

Tạo file mới `.claude/rules/common/sandboxed-domain.md` — chứa rules đặc thù không thuộc category nào có sẵn:

```markdown
# Sandboxed Domain Rules

## Monorepo boundaries
- `services/trading-engine/` KHÔNG được import từ `services/tv-api/` (và ngược lại)
- Communication giữa các service CHỈ qua ZeroMQ (order flow) hoặc Redis pub/sub (events)
- Shared code đặt trong `services/_shared/` (Python) — tv-api Go có copy riêng

## Database discipline
- Mọi schema change PHẢI đi qua Alembic migration (không `ALTER TABLE` thủ công)
- TimescaleDB hypertable: trade_audit_log, rule_check_log, account_snapshot — retention 180 ngày
- NEVER `DROP TABLE` trong migration prod — chỉ `DROP` qua backup/restore manual

## Sprint workflow
- Trước khi commit: kiểm tra `docs/sprint-artifacts/sprint-status.yaml` có phản ánh đúng trạng thái story không
- Mỗi commit tương ứng 1 story — message format: `Implement spec <epic> story <story>`
- KHÔNG commit code ngoài scope story đang làm (dùng stash/branch khác)

## FTMO compliance boundaries
- Ngưỡng daily loss / max drawdown KHÔNG được hardcode — load từ `configs/ftmo-presets.yaml`
- Mọi thay đổi preset PHẢI kèm validation report ở `docs/sprint-artifacts/validation-report-*.md`
```

#### 3.7 Xác minh Rules hoạt động

**Test nhanh** — mở 1 session Claude Code mới trong repo Sandboxed và hỏi:

```
Tôi đang làm việc trong project này. Liệt kê các rule security áp dụng cho code Python.
```

Nếu rules load đúng, Claude sẽ trả lời với nội dung từ `common/security.md` + `python/security.md` + phần project-specific bạn vừa thêm.

**Test chặt hơn** — yêu cầu Claude viết 1 function có hardcode token:

```
Viết function gửi message Telegram, dùng token "123:ABC".
```

Nếu rules hiệu lực, Claude sẽ **từ chối** hardcode và đề xuất `settings.get_secret("TELEGRAM_BOT_TOKEN")`.

> 🔍 **Nên review** nội dung rule files trước khi commit — một số rule có thể xung đột với convention sẵn có trong `docs/architecture.md`. Tạo PR riêng cho rules để review tách biệt với agents/skills.

### Bước 4 — Chọn lọc Subagents (20 phút)

Thay vì copy toàn bộ 38 agents, chỉ cài những agent phù hợp team mapping ở §2.1:

```bash
# Tạo thư mục agents local cho project
mkdir -p /home/hopdev/Dev/Sandboxed/.claude/agents

# Copy các agent cần thiết
cd /tmp/everything-claude-code/agents
cp architect.md planner.md tdd-guide.md \
   python-reviewer.md go-reviewer.md \
   security-reviewer.md database-reviewer.md \
   go-build-resolver.md doc-updater.md \
   refactor-cleaner.md harness-optimizer.md \
   docs-lookup.md loop-operator.md \
   /home/hopdev/Dev/Sandboxed/.claude/agents/
```

**Tuỳ chỉnh cho FTMO domain:**

Mở `.claude/agents/python-reviewer.md` và thêm section nói rõ các rule đặc thù của dự án — ví dụ:

```markdown
## Project-specific rules (Sandboxed FTMO)
- Mọi hàm đụng đến `account.balance` / `account.equity` PHẢI lấy từ Redis snapshot, KHÔNG tính lại trong process
- Tất cả order execution phải đi qua rule-engine check trước (tham chiếu `docs/architecture.md §4`)
- ZeroMQ socket không dùng `PUSH/PULL` cho order flow — chỉ dùng `REQ/REP` để đảm bảo ack
- Telegram bot token chỉ đọc qua `settings.get_secret()`, không hardcode
```

Tương tự cho `go-reviewer.md`, `security-reviewer.md`, `database-reviewer.md`.

### Bước 5 — Chọn lọc Skills (15 phút)

```bash
# Tạo thư mục skills
mkdir -p /home/hopdev/Dev/Sandboxed/.claude/skills

# Copy các skill theo §2.3
cd /tmp/everything-claude-code/skills
cp -r python-patterns python-testing \
      golang-patterns golang-testing \
      docker-patterns database-migrations api-design \
      continuous-learning-v2 security-review iterative-retrieval \
      /home/hopdev/Dev/Sandboxed/.claude/skills/
```

**Viết skill riêng cho domain FTMO:**

Tạo file `.claude/skills/ftmo-compliance/SKILL.md`:

```markdown
---
name: ftmo-compliance
description: Checklist tuân thủ FTMO khi thêm/sửa rule engine, risk limits, audit logging
---

# FTMO Compliance Checklist

## Daily loss limit
- [ ] Tính theo starting balance của NGÀY, reset 00:00 UTC+2 (giờ Prague)
- [ ] Ngưỡng warning: 80% của limit → gửi Telegram
- [ ] Ngưỡng block: 100% → close all + emergency stop

## Max drawdown
- [ ] Floating equity curve, không phải realized PnL
- [ ] Tham chiếu high-water mark lưu trong Redis `account:{id}:hwm`

## Audit trail
- [ ] Mỗi trade phải có record trong `trade_audit_log` (hypertable)
- [ ] Mỗi rule check phải có record trong `rule_check_log`
- [ ] Mỗi emergency stop phải có record trong `emergency_events`
```

### Bước 6 — Cấu hình Hooks (15 phút)

ECC cung cấp 3 profile hook: `minimal`, `standard`, `strict`. Với dự án trading (rủi ro cao), nên chọn **standard** làm baseline:

```bash
# Thêm vào ~/.zshrc (hoặc shell rc file)
echo 'export ECC_HOOK_PROFILE=standard' >> ~/.zshrc
echo 'export CLAUDE_PACKAGE_MANAGER=poetry' >> ~/.zshrc
source ~/.zshrc
```

**Tắt các hook không cần:**

Ví dụ: dự án không dùng tmux, tắt `tmux-reminder` hook:

```bash
export ECC_DISABLED_HOOKS="pre:bash:tmux-reminder"
```

**Thêm hook riêng** — ví dụ tự động chạy `ruff check` sau mỗi lần edit file Python:

Mở `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "if [[ \"$CLAUDE_FILE_PATH\" == *.py ]]; then cd /home/hopdev/Dev/Sandboxed && poetry run ruff check \"$CLAUDE_FILE_PATH\" 2>&1 | head -20; fi"
          }
        ]
      }
    ]
  }
}
```

### Bước 7 — Cập nhật CLAUDE.md với Workflow Matrix (10 phút)

Thêm section sau vào `CLAUDE.md` để toàn team biết khi nào dùng subagent/skill nào:

```markdown
## Workflow Matrix

| Tình huống | Công cụ ECC |
|---|---|
| Thiết kế module mới | `architect` subagent + `/ecc:plan` |
| Phân rã story thành task | `planner` subagent |
| Viết test trước (TDD) | `tdd-guide` subagent |
| Review code Python | `python-reviewer` subagent |
| Review code Go | `go-reviewer` subagent |
| Security gate (credentials/network/DB) | `security-reviewer` subagent |
| Review schema / migration | `database-reviewer` subagent |
| Lỗi build Go | `go-build-resolver` subagent |
| Lỗi build Python | Tự fix với context từ `python-patterns` skill |
| Refactor sau epic | `refactor-cleaner` subagent |
| Audit cấu hình ECC | `harness-optimizer` subagent |
| Tra cứu docs NautilusTrader/Redis | `docs-lookup` subagent + Context7 MCP |
```

### Bước 8 — Kiểm thử & Acceptance (30 phút)

**Test case 1 — Python review:**
1. Mở một file trong `services/trading-engine/src/rules/` có lỗi tiềm ẩn (ví dụ, hardcoded ngưỡng)
2. Gọi subagent `python-reviewer`: "Review file này theo rule FTMO"
3. ✅ Mong đợi: subagent phát hiện hardcoded, đề xuất fetch từ `settings`

**Test case 2 — Go review:**
1. Mở `services/tv-api/handlers/webhook.go`
2. Gọi `go-reviewer`: "Check error handling và context propagation"
3. ✅ Mong đợi: detect missing context timeout, wrap error không rõ nguồn gốc

**Test case 3 — Security scan:**
1. Tạo file test có fake `TELEGRAM_TOKEN="12345:ABCDEF..."`
2. Gọi `security-reviewer`
3. ✅ Mong đợi: cảnh báo credential leak

**Test case 4 — Orchestration song song:**
1. Lệnh: "Review đồng thời trading-engine (Python) và tv-api (Go) cho story 7.6"
2. ✅ Mong đợi: main agent gọi song song `python-reviewer` + `go-reviewer` (kiểm tra qua log tool calls trong cùng 1 message)

### Bước 9 — Thiết lập Learning Pipeline (tuần đầu tiên)

**Sau mỗi story done:**

```
/learn         # Trích xuất pattern từ session thành instinct
/instinct-status   # Xem danh sách instinct (có confidence score)
```

**Cuối tuần, Tech Lead review:**

```
/evolve        # Promote các instinct confidence cao thành skill
/prune         # Xoá instinct confidence thấp / trùng lặp
```

**Commit shared skills:**

```bash
git add .claude/skills/
git commit -m "chore: evolve weekly instincts into shared skills"
```

### Bước 10 — Commit & PR (10 phút)

```bash
git add .claude/ CLAUDE.md docs/team-setup-guide.md
git status   # Review kỹ trước khi commit
git commit -m "chore: setup ECC dev team for FTMO trading system"
git push -u origin chore/ecc-team-setup
gh pr create --title "chore: setup ECC dev team" --body "Triển khai team subagents theo docs/team-setup-guide.md"
```

---

## 4. Rollout Plan — 4 tuần

| Tuần | Mục tiêu | Deliverable |
|---|---|---|
| **1** | Cài đặt core (Bước 1–6), review & tuỳ chỉnh rules cho FTMO, test acceptance | PR `chore/ecc-team-setup` merged; `.claude/rules/` đã customize |
| **2** | Dùng thử subagents cho story đầu tiên của Epic 8; tuỳ chỉnh rules dựa vào feedback | Notes trong `docs/team-setup-retrospective-week1.md` |
| **3** | Chạy `/learn` sau mỗi story; thiết lập pipeline `/evolve` | Bộ instinct đầu tiên có confidence ≥ 0.7 |
| **4** | Evolve instinct → skill; document workflow chuẩn | `.claude/skills/ftmo-*/` đầy đủ; retrospective |

---

## 5. Rủi ro & Biện pháp giảm thiểu

| Rủi ro | Tác động | Biện pháp |
|---|---|---|
| Hook `standard` chặn nhiều thao tác bình thường | Giảm tốc độ dev | Bắt đầu `minimal`, nâng dần sau 1 tuần |
| Rules ECC xung đột với convention sẵn có | Subagent hoạt động sai | Install `.claude/` cấp project, không cấp user — dễ rollback; review từng file ở Bước 3.5 |
| Copy rule file lẻ thay vì cả thư mục | Link tương đối gãy, file collision | Dùng `cp -r` cho cả thư mục `common/`, `python/`, `golang/` (xem §3.3) |
| Rules quá generic, thiếu context FTMO | Agent bỏ qua rule domain | Bắt buộc làm Bước 3.5 + 3.6 (customize + sandboxed-domain.md) trước khi test |
| Tri thức FTMO nằm rải rác (prompt, rules, skills) | Duplicate / thiếu đồng bộ | Quy định: rule FTMO CHỈ viết trong `skills/ftmo-compliance/SKILL.md`, agent tham chiếu qua `@load ftmo-compliance` |
| Instincts kém chất lượng được propagate | Giảm chất lượng agent | Tech Lead bắt buộc review `/instinct-status` trước khi `/evolve` |
| Install.sh ghi đè settings sẵn có | Mất cấu hình hiện tại | Backup `~/.claude` trước ở Bước 1 |
| AgentShield báo false positive | Mất thời gian triage | Whitelist trong `.claude/agentshield.yaml` |

---

## 6. Checklist nhanh cho Dev

Sau khi setup xong, mỗi dev trong team làm như sau khi nhận story:

- [ ] Đọc story từ `docs/sprint-artifacts/` + load skill liên quan (`python-patterns` / `golang-patterns`)
- [ ] Gọi `planner` subagent để phân rã task
- [ ] Gọi `architect` subagent nếu cần quyết định thiết kế
- [ ] Gọi `tdd-guide` để viết test trước
- [ ] Implement — hooks tự động chạy `ruff`, `mypy`, `go vet`
- [ ] Self-review: gọi `python-reviewer` hoặc `go-reviewer`
- [ ] Security gate: gọi `security-reviewer` nếu đụng tới credentials / network / DB
- [ ] Database gate: gọi `database-reviewer` nếu đụng tới schema / migration
- [ ] Commit → PR → request review
- [ ] Cập nhật `docs/sprint-artifacts/sprint-status.yaml` sau khi merge
- [ ] Sau khi merge: `/learn` để trích xuất instinct

---

## 7. Tài liệu tham khảo

- **ECC Repo:** https://github.com/affaan-m/everything-claude-code
- **ECC Shorthand Guide:** `docs/shorthand.md` trong repo ECC
- **ECC Longform Guide:** `docs/longform.md` trong repo ECC (token optimization, memory, parallelization)
- **Security Guide:** `docs/security.md` — AgentShield, CVE scanning
- **AGENTS.md:** Full catalog của 38 agents
- **Project hiện tại:**
  - `docs/architecture.md` — kiến trúc Sandboxed
  - `docs/prd.md` — requirement tổng
  - `docs/sprint-artifacts/sprint-status.yaml` — trạng thái sprint
  - `CLAUDE.md` — convention hiện tại

---

## 8. Các câu hỏi cần làm rõ trước khi triển khai

1. **Team size:** Hiện tại có bao nhiêu dev cùng làm trên repo? Điều này ảnh hưởng xem `.claude/` nên commit lên git hay để mỗi dev tự quản.
2. **CI/CD:** CI hiện tại có chạy hook ECC không? Nếu có, cần thêm step install vào pipeline.
3. **Secrets:** `ECC_HOOK_PROFILE` và env vars nên để ở đâu (shell rc / direnv / 1Password)?
4. **FTMO evolution:** Bộ rule FTMO có thay đổi theo thời gian không? Nếu có, quy trình update `ftmo-compliance` skill như thế nào?

Trả lời các câu hỏi này trước Bước 1 để tránh phải rollback.

---

**Người viết:** Claude Code (Opus 4.6)
**Dành cho:** @hopdev
**Next action:** Review tài liệu, trả lời §8, sau đó chạy Bước 1
