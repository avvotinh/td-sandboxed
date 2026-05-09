Run all pending database migrations on TimescaleDB.

Check TimescaleDB is running first:
```bash
docker exec trading-timescaledb pg_isready -U trading -d trading
```

If not running, suggest the user run `/up` first.

Apply migrations in order:
```bash
cd /home/hopdev/Dev/Sandboxed
for f in $(ls infra/timescaledb/migrations/*.sql | sort); do
  echo "Applying $(basename $f)..."
  docker exec -i trading-timescaledb psql -U trading -d trading < "$f" 2>&1
done
```

Report results for each migration file.
