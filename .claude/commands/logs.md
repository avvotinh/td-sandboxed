Show recent logs from project services.

$ARGUMENTS can be a service name: `redis`, `timescaledb`, `tv-api`, `mt5-bridge`, `trading-engine`, `notification`

If argument is provided:
```bash
docker logs trading-$ARGUMENTS --tail 50 2>&1
```

If no argument, show all:
```bash
cd /home/hopdev/Dev/Sandboxed && docker compose -f infra/docker/docker-compose.yml logs --tail 30
```

Highlight any errors or warnings found in the logs.
