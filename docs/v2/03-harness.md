# 03 — Redesign harness `.claude/` (Claude Code team)

Mục tiêu: harness phản ánh workflow v2 (research-first, 2 ngôn ngữ chính Python + Rust
+ MQL5, 1 account) thay vì hệ 4-service cũ. Nguyên tắc: **bỏ trước, thêm sau** —
harness sai gây nhiễu tệ hơn harness thiếu.

## 1. Agents

### Giữ nguyên
| Agent | Ghi chú |
|---|---|
| `planner`, `architect` | Không đổi |
| `researcher`, `docs-lookup` | Đổi output dir mặc định → `docs/v2/studies/` cho research chiến lược |
| `python-reviewer`, `rust-reviewer`, `mql5-reviewer` | Không đổi |
| `security-reviewer` | Không đổi (live path + credentials vẫn cần) |
| `tdd-guide` | Không đổi |
| `harness-optimizer` | Không đổi |
| `doc-updater` | **Retarget**: sync `docs/v2/*` + `studies/` thay vì prd/architecture/epic-context cũ |

### Bỏ
| Agent | Lý do |
|---|---|
| `go-reviewer`, `go-build-resolver` | Go chỉ còn tv-cli đóng băng (D4); khi cần sửa Go hiếm hoi thì review inline |
| `refactor-cleaner` | Quảng cáo knip/depcheck/ts-prune (JS-only) — vô dụng với repo này từ đầu |
| `database-reviewer` | Research loop không dùng DB (D6); thêm lại khi live path P5 đụng schema |

### Thêm mới
| Agent | Model | Tools | Vai trò |
|---|---|---|---|
| `quant-reviewer` | opus | Read, Grep, Glob | Review chiến lược/backtest code cho các lỗi quant: **lookahead bias, survivorship, overfit (quá nhiều params), sai sizing/fee model, train-test leakage**. BẮT BUỘC chạy cho mọi entry/exit model mới trước khi tin kết quả backtest |
| `backtest-analyst` | sonnet | Read, Grep, Glob, Bash | Đọc `results/*.json` (Contract v2), so với promotion gate (D7), sinh verdict markdown vào `docs/v2/studies/` đúng format các verdict cũ |

## 2. Skills

### Giữ
`python-patterns`, `python-testing`, `mql5-patterns`, `mql5-zmq-bridge`,
`ftmo-compliance` (dùng lại ở P6), `meta-labeling` (Track 5 sau này),
`iterative-retrieval`, `security-review`.

### Bỏ
`golang-patterns`, `golang-testing` (Go chết dần), `api-design` (không còn REST API ngoài
viewer nội bộ), `docker-patterns` (D6 — research loop không Docker), `database-migrations`
(đóng băng tới P5), `local-dev` (viết lại — xem dưới).

### Thêm / viết lại
| Skill | Nội dung |
|---|---|
| `strategy-lab` | Cách chạy backtest/sweep/WF/AB trên kernel v2, quy ước run-id, export Contract v2, kỷ luật validation (WF fixed-params, OOS reserve, gate D7) |
| `result-contract` | Schema Contract v2 + quy tắc versioning — nguồn chân lý cho mọi agent đọc/ghi result JSON |
| `chart-viewer` | Cách chạy viewer, cách thêm indicator series/pane mới, giới hạn (không recompute) |
| `local-dev` (viết lại) | Setup v2: uv + Python 3.12 pin, chạy lab + viewer KHÔNG Docker; live path riêng |

## 3. Commands

| Command | Hành động |
|---|---|
| `/test`, `/lint`, `/logs`, `/health` | **Sửa**: bỏ tv-api/notification khỏi danh sách target |
| `/up`, `/down`, `/migrate`, `/setup` | **Đóng băng/đánh dấu "live-path only"** — research loop không cần |
| `/review` | Sửa dispatch: bỏ go-reviewer, thêm quant-reviewer cho `src/kernel/**` |
| `/harness-audit` | Sửa checklist hardcode "4 services" → layout v2 |
| `/backtest <job>` **(mới)** | Chạy `backtest run --export`, in tóm tắt metrics + đường dẫn result JSON |
| `/study <slug>` **(mới)** | Vòng study trọn gói: chạy ma trận A/B hoặc WF → gọi `backtest-analyst` sinh verdict vào `docs/v2/studies/` |
| `/viewer [run-id]` **(mới)** | Start chart-viewer, in URL (kèm run cụ thể nếu có) |
| `/research` | Giữ, output → `docs/v2/studies/` khi topic là chiến lược |

## 4. Rules

| File | Hành động |
|---|---|
| `common/sandboxed-domain.md` | **Viết lại**: bỏ boundary tv-api/notification; thêm — (a) research loop không phụ thuộc DB/Redis, (b) `results/` gitignored + verdict phải reference run_id, (c) mọi số liệu performance trích dẫn phải kèm run_id, (d) FTMO threshold vẫn load từ preset (giữ), (e) quy tắc chống lookahead cho entry models |
| `common/agents.md` | Cập nhật ma trận: thêm quant-reviewer, backtest-analyst; bỏ go-* |
| `golang/*` (5 file) | Xóa cùng lúc với việc đóng băng Go |
| `database/*` | Giữ nhưng scope path chỉ còn live-path migrations |
| `python/`, `rust/`, `mql5/` | Giữ nguyên |
| CLAUDE.md gốc | Cập nhật Structure + Workflow Matrix theo v2 sau khi các mục trên xong (P0) |

## 5. Hooks

- Giữ `postedit-python.sh`, `postedit-rust.sh` (nhớ quy tắc `bash "$CLAUDE_PROJECT_DIR/..."`).
- Bỏ `postedit-go.sh` khỏi settings khi Go bị đóng băng.
- Cân nhắc thêm PostToolUse cho `services/chart-viewer/` (ruff — đã cover bởi hook python
  per-service sẵn có nếu viewer có `pyproject.toml` riêng → không cần hook mới).

## 6. Thứ tự thực hiện P-H

1. **H1** — Sửa nhiễu ngay: `/test`, `/lint`, `/review`, `/harness-audit`, `common/agents.md`,
   `sandboxed-domain.md` (cùng P0–P1).
2. **H2** — Thêm `quant-reviewer` + skill `result-contract` (trước khi viết kernel P3).
3. **H3** — Thêm `/backtest`, `/viewer`, skill `strategy-lab` + `chart-viewer` (cùng P2).
4. **H4** — Thêm `backtest-analyst` + `/study` (đầu P4).
5. **H5** — Dọn Go: xóa agents/skills/rules/hook Go (cùng P3 task 3.6).
6. **H6** — Retarget `doc-updater`, viết lại `local-dev`, cập nhật CLAUDE.md (chốt P3).
