---
paths:
  - "**/*.py"
  - "**/*.pyi"
---
# Python Patterns

> This file extends [common/patterns.md](../common/patterns.md) with Python specific content.

## Protocol (Duck Typing)

```python
from typing import Protocol

class Repository(Protocol):
    def find_by_id(self, id: str) -> dict | None: ...
    def save(self, entity: dict) -> dict: ...
```

## Dataclasses as DTOs

```python
from dataclasses import dataclass

@dataclass
class CreateUserRequest:
    name: str
    email: str
    age: int | None = None
```

## Context Managers & Generators

- Use context managers (`with` statement) for resource management
- Use generators for lazy evaluation and memory-efficient iteration

## Reference

See skill: `python-patterns` for comprehensive patterns including decorators, concurrency, and package organization.

## Project-specific: Sandboxed FTMO

### Rule engine
- Every rule check function: `def check(context: RuleContext) -> RuleResult`
- RuleResult MUST be immutable (`@dataclass(frozen=True)`)
- Rule violation MUST log to `rule_check_log` hypertable before raising

### Async patterns
- `asyncio.gather()` for independent calls; `asyncio.wait()` with timeout for external APIs
- MT5 bridge calls: always wrap in `asyncio.wait_for(timeout=5.0)` to prevent hang
- NEVER use `time.sleep()` in async code — use `asyncio.sleep()`
