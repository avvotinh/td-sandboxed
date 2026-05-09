Run linters across all services and report issues.

1. Python (trading-engine): `cd services/trading-engine && uv run ruff check .`
2. Go (tv-api): `cd services/tv-api && go vet ./...`
3. Go (notification): `cd services/notification && go vet ./...`
4. Rust (mt5-bridge): `cd services/mt5-bridge && cargo clippy 2>&1 | tail -30`

Report any issues found, grouped by service.
