---
paths:
  - "**/*.mq5"
  - "**/*.mqh"
---
# MQL5 Patterns

> This file extends [common/patterns.md](../common/patterns.md) with MQL5-specific content.

## Trade Operations Cookbook

The five `TRADE_ACTION_*` patterns the Sandboxed EA needs. Full templates are in `skill: mql5-patterns` — this file is the rule index.

| Action | Use for | Required `MqlTradeRequest` fields |
|---|---|---|
| `TRADE_ACTION_DEAL` | Market open / close | `symbol, volume, type, price, sl, tp, deviation, magic, type_filling, comment` (`position` for hedging close) |
| `TRADE_ACTION_PENDING` | Limit / Stop | `symbol, volume, type (BUY_LIMIT…), price, sl, tp, magic, type_time, type_filling` |
| `TRADE_ACTION_SLTP` | Modify position SL/TP | `position, symbol, sl, tp, magic` |
| `TRADE_ACTION_REMOVE` | Cancel pending | `order` |
| `TRADE_ACTION_MODIFY` | Modify pending price/SL/TP | `order, price, sl, tp, type_time, expiration` |

Three invariants on EVERY trade:

1. **`OrderSend()` returning `true` is NOT success.** Check `result.retcode == TRADE_RETCODE_DONE` (10009) for deals or `TRADE_RETCODE_PLACED` (10008) for pending.
2. **Reset error before, capture after.** `ResetLastError()` immediately before `OrderSend`; on failure, log `result.retcode`, `result.comment`, `GetLastError()`.
3. **Filling mode probe per symbol.** Some brokers reject `ORDER_FILLING_FOK`. Probe via `SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE)` and fall back to IOC then RETURN.

## Volume & Price Normalization

```mql5
// Volume — MUST round to step, NOT NormalizeDouble
double NormalizeVolume(string symbol, double raw) {
    double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    double minv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    double maxv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
    double v    = MathFloor(raw / step) * step;
    return MathMax(minv, MathMin(maxv, v));
}

// Price — round to tick size, NOT decimal digits
double NormalizePrice(string symbol, double price) {
    double tick = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
    return MathRound(price / tick) * tick;
}
```

`NormalizeDouble(value, digits)` rounds to N decimal places — useless for instruments where tick size is e.g. 0.25 (futures-style). Always use the tick-size form above.

## SL/TP Distance Validation

`SYMBOL_TRADE_STOPS_LEVEL` (in points, can change live) sets the minimum distance between entry and SL/TP. `SYMBOL_TRADE_FREEZE_LEVEL` is the freeze zone (no modification). Always query both per trade:

```mql5
double point     = SymbolInfoDouble(symbol, SYMBOL_POINT);
double min_dist  = MathMax(SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL),
                           SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * point;
```

If `|entry - sl| < min_dist`, push SL outside the band before sending or reject the command back to the bridge.

## Hedging vs Netting

```mql5
bool IsHedgingAccount() {
    return ((int)AccountInfoInteger(ACCOUNT_MARGIN_MODE)
            == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
}
```

- Hedging (FTMO MT5 default): `TRADE_ACTION_SLTP` and reverse-close `TRADE_ACTION_DEAL` REQUIRE `req.position = ticket`.
- Netting: position aggregation is implicit; `req.position` not needed for netting accounts.

Code paths must branch on `IsHedgingAccount()` once at startup, not per trade.

## Position Iteration

```mql5
// Collect tickets first — index shifts if a position closes mid-loop
ulong tickets[];
int total = PositionsTotal();
ArrayResize(tickets, total);
for(int i = 0; i < total; i++) tickets[i] = PositionGetTicket(i);

// Now iterate stable copy
for(int i = 0; i < ArraySize(tickets); i++) {
    if(!PositionSelectByTicket(tickets[i])) continue;
    // ... read fields, modify, etc.
}
```

`PositionGetTicket(i)` doubles as `PositionSelect` for the iteration index — but that selection is invalidated as soon as positions change.

## ZMQ Polling Loop (OnTimer)

```mql5
void OnTimer() {
    if(IsStopped()) return;

    // Drain inbound queue, bounded by max-iterations to keep timer responsive
    string msg;
    int max_per_tick = 32;
    while(max_per_tick-- > 0 && g_zmq.Recv(msg, ZMQ_DONTWAIT)) {
        ProcessMessage(msg);
    }

    SendHeartbeatIfDue();
    BroadcastPositionSnapshotIfDue();
}
```

- `ZMQ_DONTWAIT` always — never block the timer thread.
- Bound the per-tick drain so a flooded socket cannot stall the timer.
- `IsStopped()` early-exit lets terminal close cleanly.

## Reconnect Pattern

```mql5
static int s_missedHeartbeats = 0;
static datetime s_lastBridgeAck = 0;

void CheckBridgeHealth() {
    if(TimeCurrent() - s_lastBridgeAck <= HEARTBEAT_TIMEOUT_S) return;

    s_missedHeartbeats++;
    if(s_missedHeartbeats < MAX_MISSED_HEARTBEATS) return;

    Print("WARN: Bridge timeout — reconnecting");
    g_zmq.Deinit();
    Sleep(ZMQ_RECONNECT_DELAY_MS);    // OK here — only path that may briefly block
    if(g_zmq.Init(InpBridgeHost, InpSubPort, InpPubPort)) {
        s_missedHeartbeats = 0;
    }
}
```

## Magic Number Convention

```mql5
// Derive per-account; never hardcode a literal
ulong DeriveMagic(string account_id) {
    uchar bytes[];
    StringToCharArray(account_id, bytes);
    uint hash = 0;
    for(int i = 0; i < ArraySize(bytes); i++) hash = hash * 31 + bytes[i];
    return SANDBOXED_BASE_MAGIC + (hash % 1000000);
}
```

- `SANDBOXED_BASE_MAGIC` documented in `Include/Sandboxed/Config.mqh`.
- Multi-EA on same chart: collisions break audit. Always derive.

## Symbol Info Cache

```mql5
// Cache static-per-session fields once; query live-changing fields per trade
struct SymbolStatic {
    double point;
    double tick_size;
    double volume_step;
    double volume_min;
    double volume_max;
    int    digits;
    int    margin_mode;
};

bool LoadSymbolStatic(string symbol, SymbolStatic &out) {
    if(!SymbolSelect(symbol, true)) return false;
    out.point        = SymbolInfoDouble(symbol, SYMBOL_POINT);
    out.tick_size    = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
    out.volume_step  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    out.volume_min   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    out.volume_max   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
    out.digits       = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    return true;
}
```

Live-changing fields (NEVER cache): `SYMBOL_BID`, `SYMBOL_ASK`, `SYMBOL_TRADE_STOPS_LEVEL`, `SYMBOL_TRADE_FREEZE_LEVEL`, `SYMBOL_FILLING_MODE`.

## Time Sources

| API | Returns | Use for |
|---|---|---|
| `TimeCurrent()` | Server time (broker timezone) | Trade timestamps, comparison with bar times |
| `TimeGMT()` | UTC | Heartbeat ISO 8601, sync with engine |
| `TimeLocal()` | Local OS time | Logging only — NEVER trading logic |
| `TimeTradeServer()` | Last tick server time | Detect stale ticks |

## Anti-patterns (reviewer flags these CRITICAL/HIGH)

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| `OrderSelect(ticket, SELECT_BY_TICKET)` | MT4 legacy, doesn't exist in MQL5 | `PositionSelectByTicket(ticket)` |
| `OrderModify(ticket, ...)` | MT4 legacy | `OrderSend(req, res)` with `TRADE_ACTION_SLTP` |
| `NormalizeDouble(volume, 2)` | Doesn't respect step size | `MathFloor(vol / step) * step` |
| Hardcoded `sl = bid - 200 * _Point` | Ignores `STOPS_LEVEL` | Compute `min_dist` per trade |
| `zmq_recv(s, buf, sz, 0)` | Blocks single-threaded EA | Always `ZMQ_DONTWAIT` |
| `if(OrderSend(req, res)) success!` | Doesn't check retcode | Check `res.retcode == TRADE_RETCODE_DONE` |
| `Sleep(1000)` in `OnTick` | Freezes terminal | Use `OnTimer` for periodic work |
| Recompute daily DD in EA | Race with engine | Engine is source of truth |

## Reference

- `docs/research/mql5-ea-patterns.md` §6 (trade ops), §7 (positions), §8 (normalization), §12 (pitfalls).
- Skill `mql5-patterns` — full copy-paste templates.
- Skill `mql5-zmq-bridge` — DLL imports, HMAC port, transport.
