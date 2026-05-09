---
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
---
# Rust Testing

> This file extends [common/testing.md](../common/testing.md) with Rust specific content.

## Framework

- Built-in `#[test]` for unit tests, collocated in `#[cfg(test)] mod tests { ... }`.
- Integration tests under `tests/` directory per crate.
- Prefer `rstest` for parametric tests when matrix grows.

## Running

```bash
cd services/mt5-bridge && cargo test --all-features
cd services/mt5-bridge && cargo test -- --nocapture    # print output
cd services/mt5-bridge && cargo test --release         # perf-sensitive paths
```

## Coverage

- Use `cargo-llvm-cov` for coverage reports:
  ```bash
  cargo llvm-cov --workspace --html
  ```
- Minimum 80% line coverage per `common/testing.md`.

## Async Tests

- Use `#[tokio::test]` for async; never block a runtime thread in assertions.
- Avoid `tokio::time::sleep` in tests — use `tokio::time::pause()` + `advance()`.

## Property Testing

For protocol parsers (MT5 messages), use `proptest` on decode/encode round-trips:

```rust
proptest! {
    #[test]
    fn order_roundtrip(order in any::<Order>()) {
        let bytes = order.encode();
        let decoded = Order::decode(&bytes).unwrap();
        prop_assert_eq!(order, decoded);
    }
}
```

## Mocking

- Prefer trait-based injection over `mockall` when a 3-line fake suffices.
- Use `mockall` for complex third-party traits (MT5 client, Redis).
