---
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
---
# Rust Security

> This file extends [common/security.md](../common/security.md) with Rust specific content.

## Dependency Audit

- Run `cargo audit` in CI — fail build on any advisory:
  ```bash
  cargo audit --deny warnings
  ```
- Pin transitive deps in `Cargo.lock` (commit it for the binary crate `mt5-bridge`).
- Use `cargo deny` to enforce license and dup-version policy.

## Secret Handling

- NEVER bake MT5 credentials, API keys, or broker passwords into the binary.
- Load via env vars at startup; fail loudly if missing:

```rust
let password = std::env::var("MT5_PASSWORD")
    .map_err(|_| BridgeError::MissingSecret("MT5_PASSWORD"))?;
```

- Wrap sensitive strings in [`secrecy::Secret<String>`](https://docs.rs/secrecy/) to prevent accidental logging.

## unsafe Blocks

- Every `unsafe` block requires a `// SAFETY:` comment describing the invariant upheld by the caller.
- PR touching `unsafe` MUST be reviewed by `rust-reviewer` + `security-reviewer`.

## Panics

- Panics in long-running services are a security issue (DoS). Prefer `Result` over `panic!`, `assert!`, `unwrap()` outside startup.
- Set `panic = "abort"` in release profile to avoid unwinding across FFI boundaries.

## Integer & Buffer Safety

- Use checked/saturating arithmetic for price/qty math: `.checked_mul()`, `.saturating_add()`.
- Never index raw slices from network input — use `.get(i)` and handle `None`.
- Reject inputs larger than a documented max at the boundary (MT5 framing, ZeroMQ payload).

## FTMO-specific

- `mt5-bridge` handles live broker credentials and order flow. Order/account mutations MUST log a correlation ID to the audit trail before any broker RPC.
- CURVE auth mandatory when ZeroMQ socket binds to a non-loopback interface.
