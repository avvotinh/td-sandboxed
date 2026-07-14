Check health status of all project services and infrastructure.

> Redis/TimescaleDB checks bên dưới chỉ cần cho **live path** — research loop (backtest + chart viewer) không cần Docker/DB (xem docs/v2/01-architecture.md D6).

## 1. Container status
```bash
docker ps --filter "name=trading-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

## 2. Redis connectivity
```bash
docker exec trading-redis redis-cli ping
```

## 3. TimescaleDB connectivity
```bash
docker exec trading-timescaledb pg_isready -U trading -d trading
```

## 4. Port conflicts (if containers not running)
```bash
for port in 6379 5432 5555 5556 5557; do
  echo "Port $port: $(ss -tlnp | grep ":$port " || echo 'free')"
done
```

Report status for each service with clear pass/fail indicators.
