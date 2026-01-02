# Epic 5: State Persistence & Crash Recovery - Technical Context

**Epic Goal:** Ensure trader positions and account state survive system crashes with zero data loss.

**User Value:** Trader's positions and compliance state are preserved through any system failure, enabling safe recovery.

**FR Coverage:** FR31-35, FR54

---

## Technology Research (Context7 - January 2026)

### Redis-py v6.x Latest Patterns

**Async Operations with redis.asyncio:**
```python
import redis.asyncio as aioredis

async def main():
    r = await aioredis.from_url(
        'redis://localhost:6379',
        encoding='utf-8',
        decode_responses=True
    )

    # Hash operations for state snapshots
    await r.hset('snapshot:ftmo-gold-001:latest', mapping={
        'timestamp': '2026-01-03T14:32:15.123456Z',
        'positions': json.dumps([...]),
        'equity': '99850.00',
        'checksum': 'sha256_hash'
    })

    # TTL management
    await r.expire('snapshot:ftmo-gold-001:latest', 3600)  # 1 hour TTL

    # Pipeline for atomic operations
    async with r.pipeline(transaction=True) as pipe:
        await pipe.hset('snapshot:account:latest', mapping={...})
        await pipe.expire('snapshot:account:latest', 3600)
        await pipe.execute()
```

**Hash Operations for Snapshots:**
- `HSET` with mapping for multi-field writes
- `HGETALL` for complete state retrieval
- `HSCAN_ITER` for large hash iteration (memory-efficient)
- `HINCRBY/HINCRBYFLOAT` for atomic counter updates

**TTL/Expiry Management:**
- `expire(key, seconds)` - set expiration in seconds
- `pexpire(key, milliseconds)` - millisecond precision
- `ttl(key)` - check remaining time
- `persist(key)` - remove expiration

### NautilusTrader State Persistence Patterns

**Cache Configuration with Redis Backend:**
```python
from nautilus_trader.config import CacheConfig, DatabaseConfig

cache_config = CacheConfig(
    database=DatabaseConfig(
        type="redis",
        host="localhost",
        port=6379,
        timeout=2.0,
    ),
    encoding="msgpack",  # or "json"
    timestamps_as_iso8601=True,
    buffer_interval_ms=100,
    flush_on_start=False,
)
```

**Position State Snapshots:**
- `snapshot_position_state(position, ts_snapshot, unrealized_pnl, open_only=True)`
- Persists to backing cache database
- Includes unrealized PnL tracking
- `open_only` flag prevents race conditions

**Component Lifecycle (on_start, on_stop):**
- `load()` - Load all actor and strategy states from cache
- `save()` - Save all actor and strategy states to cache
- Recovery sequence: Start → Load State → Reconcile → Resume

**Order Persistence and Recovery:**
- Emulated orders reload from cache database on restart
- Ensures order state persistence across system restarts

---

## Existing Codebase Implementation

### Current RedisStateManager (src/state/redis_state.py)

Already implemented:
- Account status persistence (`account:{account_id}:status`)
- Account health with 60s TTL (`account:{account_id}:health`)
- Risk state persistence with 7-day TTL (`risk:{account_id}:state`)
- Risk violation tracking with 90-day TTL
- Account balance persistence
- Alert publishing via pub/sub

**Key Patterns Established:**
```python
class RedisStateManager:
    RISK_STATE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

    async def connect(self) -> None:
        self._client = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def save_risk_state(self, account_id: str, state: RiskState) -> None:
        key = f"risk:{account_id}:state"
        await self.client.hset(key, mapping=state.to_dict())
        await self.client.expire(key, self.RISK_STATE_TTL_SECONDS)
```

### Current RedisAdapter (src/adapters/redis_adapter.py)

Pub/sub adapter for market data:
- Async subscription to bar channels
- Automatic reconnection with exponential backoff
- Bar callback integration for signal routing

---

## Architecture Requirements (docs/architecture.md)

### Redis Key Patterns for Epic 5

```
# Account State Snapshots (Hash) - NEW for Story 5.1
Key: snapshot:{account_id}:latest
Fields:
  timestamp: "2026-01-03T14:32:15.123456Z"
  positions: JSON array of open positions
  pending_orders: JSON array
  account_balance: 100000.00
  equity: 99850.00
  peak_balance: 102500.00
  daily_starting_balance: 100500.00
  checksum: SHA256 hash
TTL: 1 hour

# Historical Snapshots (Sorted Set) - for recovery
Key: snapshot:{account_id}:history
Score: timestamp (unix milliseconds)
Value: JSON snapshot
TTL: 24 hours
```

### State Persistence Flow

```
Runtime State (Memory)
┌──────────────────────────────────────────────────────────────┐
│ - Open positions per account                                  │
│ - Pending orders per account                                  │
│ - Daily P&L per account                                       │
│ - Rule engine state                                           │
└──────────────────────────────────────────────────────────────┘
                          │
                          │ Every 5 seconds
                          ▼
Redis Snapshots (Hot)
┌──────────────────────────────────────────────────────────────┐
│ Key: snapshot:{account_id}:latest                            │
│ TTL: 1 hour                                                   │
└──────────────────────────────────────────────────────────────┘
                          │
                          │ Every 1 minute
                          ▼
TimescaleDB (Cold)
┌──────────────────────────────────────────────────────────────┐
│ Table: state_snapshots (per account, timestamped)            │
│ Retention: 7 days                                             │
└──────────────────────────────────────────────────────────────┘
```

### Crash Recovery Sequence

```
1. Engine Startup
2. Load account configurations from YAML
3. For each account:
   ├── Check Redis snapshot exists?
   │   ├── YES: Load snapshot, validate checksum
   │   └── NO: Query TimescaleDB for latest state
4. Connect to MT5 (per account)
5. Reconcile positions:
   ├── Compare snapshot positions vs MT5 actual
   ├── Log discrepancies
   └── Use MT5 as source of truth
6. Recalculate daily P&L from trade history
7. Resume normal operation
```

---

## Epic 5 Stories Overview

| Story | Title | Description | Dependencies |
|-------|-------|-------------|--------------|
| 5.1 | Redis State Snapshots | 5-second interval snapshots to Redis | Epic 4 complete |
| 5.2 | Crash Detection and Recovery Initiation | Detect crash, initiate recovery | 5.1 |
| 5.3 | Position Reconciliation with MT5 | Compare Redis vs MT5 positions | 5.2 |
| 5.4 | Daily P&L Recalculation | Recalculate P&L from trade history | 5.3 |
| 5.5 | Trading Resume After Recovery | Safe resume after reconciliation | 5.4 |
| 5.6 | Graceful Shutdown with State Persistence | Save all state before shutdown | 5.1 |
| 5.7 | TimescaleDB Cold Storage Backup | 1-minute snapshots to database | 5.1 |

---

## Story 5.1 Specific Requirements

### From epics.md:

**User Story:**
> As a trader, I want the engine to snapshot account state every 5 seconds, so that I have recent recovery data.

**Acceptance Criteria:**
1. State snapshot occurs every 5 seconds while engine is running
2. Snapshot includes: positions, pending_orders, balance, equity, peak_balance, daily_starting_balance
3. Snapshot stored in Redis hash with TTL of 1 hour
4. Checksum included for data integrity validation
5. Snapshot timestamp in ISO8601 format with microseconds

**Technical Requirements:**
- Use async Redis operations (redis.asyncio)
- Hash key pattern: `snapshot:{account_id}:latest`
- Implement `to_dict()` and `from_dict()` for snapshot serialization
- Use SHA256 for checksum calculation
- Support concurrent snapshots for multiple accounts

**Test Requirements:**
- Unit tests for snapshot creation and serialization
- Unit tests for checksum calculation and validation
- Integration tests with Redis for persistence
- Performance test: snapshot < 10ms per account

---

## File Locations for Implementation

```
services/trading-engine/
├── src/
│   ├── state/
│   │   ├── __init__.py
│   │   ├── redis_state.py      # Extend with snapshot methods
│   │   ├── snapshot.py         # NEW: Snapshot model and serialization
│   │   └── snapshot_service.py # NEW: 5-second interval service
│   └── ...
└── tests/
    └── unit/
        ├── test_redis_state.py  # Extend with snapshot tests
        ├── test_snapshot.py     # NEW: Snapshot model tests
        └── test_snapshot_service.py # NEW: Service tests
```

---

**Context Generated:** 2026-01-03
**Epic Status:** contexted (ready for story drafting)
