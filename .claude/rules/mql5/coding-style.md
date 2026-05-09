---
paths:
  - "**/*.mq5"
  - "**/*.mqh"
---
# MQL5 Coding Style

> This file extends [common/coding-style.md](../common/coding-style.md) with MQL5-specific content.

## File Organization

```
mql5-ea/
├── Experts/
│   └── Sandboxed/
│       └── Sandboxed_EA.mq5      ← entry point ONLY: lifecycle hooks + wiring
├── Include/
│   ├── Sandboxed/                ← project code, all .mqh
│   │   ├── Config.mqh            ← input params + constants
│   │   ├── ZmqClient.mqh         ← ZMQ socket wrapper
│   │   ├── MessageParser.mqh     ← JSON dispatch
│   │   ├── HmacSha256.mqh        ← HMAC verify
│   │   ├── TradeExecutor.mqh     ← OrderSend wrappers
│   │   └── PositionSnapshot.mqh  ← snapshot broadcast
│   ├── Zmq/                      ← upstream dingmaotu/mql-zmq, do NOT modify
│   └── Json/                     ← upstream vivazzi/JAson, do NOT modify
└── Libraries/
    └── MT5/
        ├── libzmq.dll
        └── libsodium.dll
```

- `.mq5` = EA entry. **Zero business logic** — only `OnInit`/`OnTick`/`OnTimer`/`OnDeinit` + delegation to includes.
- `.mqh` = include header. All logic lives here.
- `#include <Zmq/Socket.mqh>` (angle brackets) → `MQL5/Include/`.
- `#include "../local.mqh"` (quotes) → relative path.

## Naming Conventions (de-facto MQL5 community)

```mql5
// Inputs (user-visible in EA dialog): prefix Inp
input int    InpMagicNumber       = 20260001;
input string InpBridgeHost        = "127.0.0.1";
input int    InpHeartbeatIntervalS = 1;

// Globals: prefix g_
intptr_t g_zmqContext;
intptr_t g_subSocket;

// Statics local to function: prefix s_
static datetime s_lastHeartbeat;

// Class members: prefix m_
class CTradeExecutor {
    int m_retryCount;
};

// Constants: UPPER_CASE via #define
#define HEARTBEAT_INTERVAL_MS 1000
#define MAX_MISSED_HEARTBEATS 5

// Functions: PascalCase
void SendHeartbeat();
bool VerifyHmac(const string &message, const string &signature);
```

## EA Properties Block (mandatory)

Place at the top of every `.mq5`:

```mql5
#property copyright   "Sandboxed Trading"
#property link        "https://github.com/hopdev/Sandboxed"
#property version     "1.00"
#property description "ZMQ Bridge EA for Sandboxed mt5-bridge"
#property strict
```

`#property strict` enables stronger type checks — never omit.

## Function & File Size

- Functions: ≤ 50 lines. Trade lifecycle helpers (`SendMarketOrder`, `ModifyPositionSLTP`, `BroadcastPositionSnapshot`) are the most common offenders — extract sub-helpers.
- Files: ≤ 800 lines per `.mqh`. Split by responsibility (parser vs executor vs transport).
- Nesting: ≤ 4 levels — early-return on guard failures.

## Logging

- Use `PrintFormat("...", a, b)` over `Print("...", a, " ", b)` — single allocation, fewer GC pressure points.
- Never `Print()` inside `OnTick` hot path unless behind a debug-flag guard.
- Log level convention (no syslog in MQL5 — emulate via prefix):
  - `Print("ERROR: ...")` for failures requiring operator attention.
  - `Print("WARN: ...")` for recoverable anomalies.
  - `Print("INFO: ...")` for lifecycle events.
- Never log HMAC keys, broker passwords, or full credentials.

## Strings & Allocation

- MQL5 strings are UTF-16 (Win32 UNICODE). Convert to UTF-8 with `StringToCharArray(text, buf, 0, StringLen(text))` before passing to libzmq DLL — drop the trailing null terminator (`ArrayResize(buf, len - 1)`).
- Avoid building strings inside `OnTick`. Build only when sending.
- Use `StringFormat` once per send, not concatenation chains.

## Comments & Sources

- When porting code from third-party (e.g. `dingmaotu/mql-zmq`), keep an upstream attribution at file head:
  ```mql5
  // Source: https://github.com/dingmaotu/mql-zmq/blob/master/Include/Zmq/Socket.mqh
  // License: Apache-2.0
  ```
- Within project code, follow `common/coding-style.md` — no narrative comments. WHY-only.

## Forbidden Patterns

- MT4 legacy API: `OrderSelect`, `OrderModify`, `OrderClose`, `OrderSend(int, ...)` (legacy 11-arg form). All replaced by `PositionSelectByTicket` + `OrderSend(MqlTradeRequest&, MqlTradeResult&)`.
- `NormalizeDouble(volume, digits)` for lot rounding — does not respect `SYMBOL_VOLUME_STEP`. Use `MathFloor(vol / step) * step`.
- Hardcoded SL/TP point distance — must be computed from `SYMBOL_TRADE_STOPS_LEVEL` per trade.
- Hardcoded magic numbers — derive per account.
- Direct DLL imports of anything other than `libzmq.dll` / `libsodium.dll` without a security review.

## Reference

- Official MQL5 reference: https://www.mql5.com/en/docs
- Style baseline: `docs/research/mql5-ea-patterns.md` §3
