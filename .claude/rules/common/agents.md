# Agent Orchestration

## Available Agents

Located in `.claude/agents/` (project-local, not `~/.claude/agents/`):

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| planner | Implementation planning | Complex features, refactoring |
| architect | System design | Architectural decisions |
| tdd-guide | Test-driven development | New features, bug fixes |
| python-reviewer | Python code review | After writing/modifying `.py` files |
| rust-reviewer | Rust code review | After writing/modifying `.rs` files |
| mql5-reviewer | MQL5 code review (MT5 EA trade ops, ZMQ DLL safety, FTMO guards) | After writing/modifying `.mq5`/`.mqh` files (Epic 14) |
| security-reviewer | Security analysis | Before commits touching credentials/network/DB |
| doc-updater | Documentation | Syncing prd/architecture/epic-context/sprint-status after epic/story |
| researcher | Feature research (GitHub/Context7/web) before implementing | Before implementing a new feature or picking a library |
| docs-lookup | Up-to-date library/framework/API docs via Context7 MCP | Docs/API/setup questions |
| harness-optimizer | Audit and improve `.claude/` harness configuration | After running `/harness-audit` |
| quant-reviewer | Quant-strategy review (lookahead bias, survivorship, overfit, train-test leakage, sizing/fee errors) | After writing/modifying strategy code under `src/strategies/` or `src/kernel/` — MUST run for every new entry/exit model before backtest results are trusted |
| backtest-analyst | Reads `results/*.json` (Result Contract v2), compares against promotion gate D7, writes verdict markdown to `docs/v2/studies/` with run_ids | After backtest/sweep/walk-forward runs when a study verdict is needed (`/study`) |

> Removed in v2: `go-reviewer`, `go-build-resolver` (Go frozen — tv-cli fetch only), `refactor-cleaner`. `database-reviewer` returns at the live-path phase (P5) when schema work resumes.

## Immediate Agent Usage

No user prompt needed:
1. Complex feature requests - Use **planner** agent
2. Python code written/modified - Use **python-reviewer** agent
3. Rust code written/modified - Use **rust-reviewer** agent
4. Strategy/entry/exit model code written/modified - Use **quant-reviewer** agent
5. Bug fix or new feature - Use **tdd-guide** agent
6. Architectural decision - Use **architect** agent

## Parallel Agent Execution

ALWAYS use parallel `Agent` tool calls (subagent_type) for independent operations:

```markdown
# GOOD: Parallel execution
Launch 3 agents in parallel:
1. Agent call 1: Security analysis of auth module
2. Agent call 2: Performance review of cache system
3. Agent call 3: Type checking of utilities

# BAD: Sequential when unnecessary
First agent 1, then agent 2, then agent 3
```

## Multi-Perspective Analysis

For complex problems, use split role sub-agents:
- Factual reviewer
- Senior engineer
- Security expert
- Consistency reviewer
- Redundancy checker
