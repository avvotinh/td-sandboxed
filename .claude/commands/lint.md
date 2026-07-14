Run linters across all services and report issues.

1. Python (trading-engine): `cd services/trading-engine && uv run ruff check .`
2. Rust (mt5-bridge): `cd services/mt5-bridge && cargo clippy 2>&1 | tail -30`

Report any issues found, grouped by service.
