---
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
---
# Rust Patterns

> This file extends [common/patterns.md](../common/patterns.md) with Rust specific content.

## Error Hierarchy

- Per-module domain errors via `thiserror`.
- Binary `main.rs` uses `anyhow::Result<()>` and `?` to unify.

## Newtype Pattern

Avoid primitive obsession for financial identifiers:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AccountId(u64);

#[derive(Debug, Clone, Copy)]
pub struct Price(i64);  // fixed-point, in 1/1000th of a pip
```

## Async Boundaries

- Use `tokio` for all async I/O in `mt5-bridge`.
- Keep async functions thin; do CPU work in `tokio::task::spawn_blocking`.
- Prefer bounded `mpsc` channels; document queue depth.

## Builder / Typestate

For multi-step connection setup (MT5 login → auth → subscribe), use typestate:

```rust
pub struct Connected;
pub struct Authenticated;

impl Bridge<Connected> {
    pub fn authenticate(self, creds: Credentials) -> Result<Bridge<Authenticated>> { ... }
}

impl Bridge<Authenticated> {
    pub fn place_order(&self, order: Order) -> Result<OrderId> { ... }
}
```

## FFI / C Interop

- Isolate all FFI in a `sys/` submodule with narrow safe wrappers.
- Convert C errors to domain errors at the boundary — never leak `c_int` outside.

## Reference

No dedicated Rust patterns skill exists. For crate discovery prefer `cargo search` + crates.io; use `docs-lookup` agent + Context7 MCP for crate docs.
