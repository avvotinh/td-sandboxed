Guide the user through first-time project setup. Check each prerequisite and report status before proceeding.

## Step 1 — Check prerequisites
Run these checks and report pass/fail for each:
```bash
docker --version          # Need Docker 24+
docker compose version    # Need Compose v2
go version                # Need Go 1.21+
rustc --version           # Need Rust 1.75+
python3 --version         # Need Python 3.11+
uv --version              # Need uv
```

## Step 2 — Environment config
Check if `configs/dev/.env` exists. If not, guide the user to create it from documentation.

## Step 3 — Start infrastructure
```bash
cd /home/hopdev/Dev/Sandboxed && make infra-up
```
Wait for health checks to pass.

## Step 4 — Run database migrations
```bash
cd /home/hopdev/Dev/Sandboxed
export POSTGRES_PASSWORD=devpassword
for f in infra/timescaledb/migrations/*.sql; do
  echo "Applying $f..."
  docker exec -i trading-timescaledb psql -U trading -d trading < "$f"
done
```

## Step 5 — Install Python dependencies
```bash
cd /home/hopdev/Dev/Sandboxed/services/trading-engine && uv sync
```

## Step 6 — Verify
```bash
cd /home/hopdev/Dev/Sandboxed && make test
```

Report final status for each step.
