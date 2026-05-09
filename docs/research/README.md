# Research

Pre-implementation research output. Written by the `researcher` agent (invoke via `/research <topic>`).

## Purpose

Before implementing a non-trivial feature, we research:
1. Existing implementations on GitHub (battle-tested, adoptable)
2. Current library APIs via Context7 (not training-data memory)
3. Broader web only when the first two are insufficient

Findings live here so the next person doesn't repeat the same search.

## File naming

`<topic-slug>-<YYYY-MM-DD>.md`

Examples:
- `trailing-drawdown-rule-2026-04-18.md`
- `python-ta-indicators-2026-05-02.md`
- `zmq-curve-auth-2026-06-10.md`

## When to add

- Non-obvious: library choice, algorithm selection, unfamiliar pattern
- Reusable: likely someone on the team will ask the same question later
- Costly: research took more than ~20 minutes

**Skip** if the answer was a 10-minute Google or lives inline in code/tests.

## When to remove

Outdated research (>12 months, superseded by a shipped decision) can be deleted or moved to `docs/research/_archive/`. Don't let the folder become an attic.

## Related agents / commands

- `/research <topic>` — kick off a research session
- `researcher` agent — the one doing the work
- `planner` / `architect` — typically read research output as input
