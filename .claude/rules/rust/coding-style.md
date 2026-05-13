---
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
  - "**/Cargo.lock"
---
# Rust Coding Style

> This file extends [common/coding-style.md](../common/coding-style.md) with Rust specific content.

## Formatting

- **rustfmt** is mandatory — run `cargo fmt` before commit, no style debates.
- Line length follows workspace `rustfmt.toml`; default 100.

## Linting

- `cargo clippy --all-targets --all-features -- -D warnings` must be clean before commit.
- Prefer `clippy::pedantic` advisory for new modules; suppress with justified `#[allow(...)]`.

## Error Handling

- Library crates: return `Result<T, E>` with a concrete error type (`thiserror` for enum errors).
- Binary crates (`mt5-bridge` main): propagate with `anyhow::Result` at boundaries; convert to domain errors internally.
- Never `unwrap()` or `expect()` in production paths outside `main.rs` startup or tests. Use `?` and bubble up.

```rust
use thiserror::Error;

#[derive(Debug, Error)]
pub enum BridgeError {
    #[error("mt5 connection failed: {0}")]
    Connect(#[from] std::io::Error),
    #[error("invalid order payload")]
    InvalidOrder,
}
```

## Unsafe

- `unsafe` blocks require a `// SAFETY:` comment explaining invariants.
- Prefer safe abstractions (`bytes`, `zerocopy`) over hand-rolled pointer math.

## Ownership & Borrowing

- Accept `&str` / `&[T]` in function signatures; take `String` / `Vec<T>` only when ownership is required.
- Return owned types from constructors; return borrowed types from accessors.

## Design Principles

- Small, focused modules (< 400 lines). Split large modules by responsibility.
- Prefer composition over trait inheritance chains.
- Use newtypes (`struct AccountId(u64)`) to avoid primitive obsession around IDs, amounts, symbols.

## Reference

Project uses `mt5-bridge` (Rust) as MT5 bridge service. See `services/mt5-bridge/Cargo.toml` for crate dependencies.
