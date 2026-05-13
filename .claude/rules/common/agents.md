# Agent Orchestration

## Available Agents

Located in `~/.claude/agents/`:

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| planner | Implementation planning | Complex features, refactoring |
| architect | System design | Architectural decisions |
| tdd-guide | Test-driven development | New features, bug fixes |
| python-reviewer | Python code review | After writing/modifying `.py` files |
| go-reviewer | Go code review | After writing/modifying `.go` files |
| rust-reviewer | Rust code review | After writing/modifying `.rs` files |
| security-reviewer | Security analysis | Before commits |
| go-build-resolver | Fix Go build errors | When Go build fails |
| refactor-cleaner | Dead code cleanup | Code maintenance |
| doc-updater | Documentation | Updating docs |

## Immediate Agent Usage

No user prompt needed:
1. Complex feature requests - Use **planner** agent
2. Python code written/modified - Use **python-reviewer** agent
3. Go code written/modified - Use **go-reviewer** agent
4. Rust code written/modified - Use **rust-reviewer** agent
5. Bug fix or new feature - Use **tdd-guide** agent
6. Architectural decision - Use **architect** agent

## Parallel Task Execution

ALWAYS use parallel Task execution for independent operations:

```markdown
# GOOD: Parallel execution
Launch 3 agents in parallel:
1. Agent 1: Security analysis of auth module
2. Agent 2: Performance review of cache system
3. Agent 3: Type checking of utilities

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
