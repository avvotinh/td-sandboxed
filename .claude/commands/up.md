Start all project services using Docker Compose and verify they're healthy.

```bash
cd /home/hopdev/Dev/Sandboxed && make up
```

Wait 10 seconds then check health:
```bash
cd /home/hopdev/Dev/Sandboxed && make infra-status
```

Report which services are running and any that failed to start.
