Audit the `.claude/` harness configuration for drift, bugs, and missed leverage. Report a prioritized action list.

## Checks

1. **Structure completeness**
   - `agents/`, `commands/`, `rules/`, `skills/`, `settings.local.json` exist.
   - Every active service language has a matching `rules/<lang>/` directory.
     - Project services: trading-engine (python), tv-api & notification (golang), mt5-bridge (rust), + database for TimescaleDB/Alembic.

2. **Agent ↔ CLAUDE.md alignment**
   - Every agent in `.claude/agents/` is referenced in CLAUDE.md's Workflow Matrix (or an alternative surface).
   - Every agent named in CLAUDE.md has a corresponding `.md` file.
   - Flag unused agents (dead weight) and documented-but-missing agents (broken reference).

3. **Command ↔ CLAUDE.md alignment**
   - Every slash command in `commands/` is documented in CLAUDE.md's command table.
   - Every documented command has a corresponding `.md`.
   - Detect duplicate commands (e.g., `test` + `test-<service>`).

4. **Hook correctness** (`settings.local.json`)
   - Shell quoting robust against paths with spaces.
   - Go hook: uses `gofmt -w` (not `-l`); `go vet ./...` runs inside package dir, not via glob.
   - Python hook: ruff check scoped to edited file; per-service invocation via `uv run` when inside `services/<svc>/`.
   - Rust hook: walks up to `Cargo.toml` before invoking cargo.
   - Hook description in rules/<lang>/hooks.md matches actual commands (no phantom mypy/staticcheck claims).

5. **Rule consistency**
   - Rules reference only files/dirs that exist (e.g., `services/_shared/` — exists? if not, document as TODO).
   - No contradictions between `common/` and language-specific rules.
   - Each rule has its `paths:` frontmatter where auto-loading is intended.

6. **Model / cost routing**
   - Lightweight, high-frequency agents use `model: haiku` (docs-lookup, simple lookups).
   - Deep-reasoning agents use `model: opus` only when necessary (architect, harness-optimizer).
   - Bulk of coding work defaults to `sonnet`.

7. **Skills hygiene**
   - Each skill under `skills/` is either actively wired (hook/slash command/agent references it) or removed.
   - Flag skills with `observer.enabled: false` or equivalent dormant state.

8. **Secrets & gitignore**
   - `settings.local.json` is gitignored.
   - No committed files under `.claude/` contain tokens, passwords, or absolute secret paths.

## Output

Produce sections:
- **Inventory** — one-line summary of counts (agents, commands, rules, skills).
- **Issues** — grouped by severity (HIGH/MED/LOW), each with file path + recommended fix.
- **Model routing table** — current model per agent vs. recommended.
- **Next actions** — top 5 changes ranked by leverage/effort ratio.

Do not modify files — audit only. For modifications, hand off to the `harness-optimizer` agent.
