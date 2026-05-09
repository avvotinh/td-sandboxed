---
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
---
# Rust Hooks

> This file extends [common/hooks.md](../common/hooks.md) with Rust specific content.

## PostToolUse Hooks

Configured in `.claude/settings.local.json`:

- **cargo fmt --check**: verifies formatting on `.rs` edits. Walks up to the nearest `Cargo.toml`.

Not currently enabled (add manually if desired):
- **cargo clippy**: run on save — slow on cold cache, prefer pre-commit.
- **cargo check**: fast type check against edited crate.

## Pre-commit Recommendations

Run locally before committing mt5-bridge changes:

```bash
cd services/mt5-bridge && cargo fmt --all
cd services/mt5-bridge && cargo clippy --all-targets --all-features -- -D warnings
cd services/mt5-bridge && cargo test
```
