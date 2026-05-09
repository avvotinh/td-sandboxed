---
paths:
  - "**/*.py"
  - "**/*.pyi"
---
# Python Hooks

> This file extends [common/hooks.md](../common/hooks.md) with Python specific content.

## PostToolUse Hooks

Configured in `.claude/settings.local.json`:

- **ruff check**: Lint `.py` files after edit (limited to 20 lines of output). Runs per-service via `uv run ruff check` when edited file is under `services/<svc>/`, else falls back to repo-root `ruff check`.

Not currently enabled (add manually if desired):
- **black/ruff format**: auto-format on save
- **mypy/pyright**: type-check on save
- **print() → logging** warning

## Warnings

- Prefer `logging` module over `print()` in service code.
