---
paths:
  - "**/*.mq5"
  - "**/*.mqh"
---
# MQL5 Hooks

> This file extends [common/hooks.md](../common/hooks.md) with MQL5-specific content.

## EA Lifecycle Events

The MT5 terminal calls these in a fixed pattern. Implement only what you use.

| Event | When | Typical use in Sandboxed EA |
|---|---|---|
| `OnInit()` | Attach, recompile, parameters change, account change | Validate inputs, initialize ZMQ context+sockets, set timer, log start |
| `OnTick()` | New tick on EA's chart symbol | Minimal — bridge EA does NOT trade per tick |
| `OnTimer()` | Every `EventSetTimer(N)` interval | Main event loop: drain ZMQ queue, send heartbeat, broadcast snapshot |
| `OnTrade()` | Trade event (order placed/modified/filled/closed) | Optional — emit `OrderUpdate` to bridge for stronger sync |
| `OnTradeTransaction()` | Granular trade event with `MqlTradeTransaction` | Recommended over `OnTrade` for multi-EA disambiguation by ticket |
| `OnDeinit()` | Detach, recompile, terminal close, account change | Kill timer, close sockets, destroy ZMQ context (in this order) |
| `OnChartEvent()` | UI events on chart | Not used in bridge EA |

## OnInit Return Codes

```mql5
int OnInit() {
    // Validate inputs first
    if(InpMagicNumber <= 0 || StringLen(InpHmacKey) < 32) {
        Print("ERROR: Invalid inputs");
        return INIT_PARAMETERS_INCORRECT;   // Optimizer skips this combo
    }

    // Strategy Tester guard
    if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION)) {
        Print("INFO: Tester detected — skipping ZMQ");
        return INIT_SUCCEEDED;
    }

    if(!g_zmq.Init(InpBridgeHost, InpSubPort, InpPubPort)) {
        return INIT_FAILED;                  // Unloads EA from chart
    }

    EventSetTimer(InpTimerIntervalS);
    Print("INFO: Sandboxed EA initialized magic=", InpMagicNumber);
    return INIT_SUCCEEDED;
}
```

| Constant | Value | Meaning |
|---|---|---|
| `INIT_SUCCEEDED` | 0 | OK, EA runs |
| `INIT_FAILED` | -1 | Fatal error — terminal unloads EA |
| `INIT_PARAMETERS_INCORRECT` | -2 | Bad inputs — optimizer skips this set |
| `INIT_AGENT_NOT_SUITABLE` | -3 | Tester agent too weak — skip |

## OnDeinit Cleanup Order

```mql5
void OnDeinit(const int reason) {
    // 1. Stop receiving events
    EventKillTimer();

    // 2. Close sockets BEFORE destroying context
    g_zmq.Deinit();   // zmq_close() each socket → zmq_ctx_destroy()

    // 3. Log reason for postmortem
    PrintFormat("INFO: EA deinit reason=%d (%s)", reason, ReasonString(reason));
}
```

| Code | Constant | Meaning |
|---|---|---|
| 0 | `REASON_PROGRAM` | `ExpertRemove()` called |
| 1 | `REASON_REMOVE` | EA removed from chart |
| 2 | `REASON_RECOMPILE` | EA recompiled |
| 3 | `REASON_CHARTCHANGE` | Symbol/timeframe changed |
| 4 | `REASON_CHARTCLOSE` | Chart closed |
| 5 | `REASON_PARAMETERS` | Inputs changed |
| 6 | `REASON_ACCOUNT` | Account changed/reconnected |
| 7 | `REASON_TEMPLATE` | Template applied |
| 8 | `REASON_INITFAILED` | OnInit returned non-zero |
| 9 | `REASON_CLOSE` | Terminal closed |

`REASON_RECOMPILE` (2) and `REASON_PARAMETERS` (5) imply the EA is about to re-init. Persist necessary state to terminal globals if you need continuity across these events.

## OnTimer Pattern

```mql5
void OnTimer() {
    if(IsStopped()) return;
    DrainZmq(MAX_MESSAGES_PER_TICK);
    SendHeartbeatIfDue();
    BroadcastSnapshotIfDue();
    CheckBridgeHealth();
}
```

- Single-threaded — `OnTimer` and `OnTick` share the strategy thread.
- Bound the work per call. A 1s timer with 200 ms of work per call yields a 20% CPU budget.
- Use `EventSetTimer(seconds)` for ≥ 1s; `EventSetMillisecondTimer(ms)` for sub-second (rarely needed for bridge EA).

## OnTradeTransaction (recommended for sync)

```mql5
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,
                        const MqlTradeResult &res) {
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;     // only fills
    if(req.magic != InpMagicNumber)              return;     // not ours

    // Forward fill event to bridge with order_id correlation
    EmitDealEvent(trans.deal, trans.symbol, trans.price, trans.volume);
}
```

`OnTrade()` fires for every trade event but lacks the granular transaction info. `OnTradeTransaction` is preferred for bridge sync.

## Hooks NOT used in bridge EA

- `OnTick`: keep minimal (e.g., empty or just `IsStopped()` check). Trading is command-driven, not signal-driven.
- `OnChartEvent`: no UI.
- `OnBookEvent`: no DOM use.
- `OnTester` / `OnTesterInit` / `OnTesterDeinit` / `OnTesterPass`: tester does not exercise the bridge — provide stubs only.

## TodoWrite Discipline

Per `common/hooks.md`, use TodoWrite to:
- Track multi-step EA implementation (one item per Phase A story 14.1-14.6).
- Reveal out-of-order steps (e.g., wiring before scaffold).
- Confirm DLL-deploy + compile + attach steps for the operator runbook (story 14.19).

## Reference

- `docs/research/mql5-ea-patterns.md` §4.
- MQL5 docs: https://www.mql5.com/en/docs/event_handlers
