---
name: mql5-patterns
description: Idiomatic MQL5 patterns for MT5 Expert Advisors — trade operations, position management, lifecycle hooks, and order safety. Use when writing or reviewing .mq5 / .mqh code.
origin: Sandboxed
---

# MQL5 Patterns

Copy-paste-ready templates for the Sandboxed MT5 EA. Every snippet is verified against MQL5 official docs and `docs/research/mql5-ea-patterns.md` (cited).

## When to Activate

- Writing new MQL5 code (`.mq5` entry, `.mqh` includes)
- Reviewing MQL5 trade-operations code
- Porting reference EAs into Sandboxed style
- Designing the Sandboxed EA Phase A scaffold (Epic 14 stories 14.1–14.6)

## Core Principles

1. **`OrderSend()` returning `true` is NOT success.** Always check `result.retcode`.
2. **MT4 legacy API (`OrderSelect`/`OrderModify`/`OrderClose`) does NOT exist.** Use `MqlTradeRequest` + `OrderSend`.
3. **Volume rounding uses `MathFloor(vol/step)*step`, not `NormalizeDouble`.**
4. **SL/TP distance comes from `SYMBOL_TRADE_STOPS_LEVEL` queried per trade.**
5. **`OnTimer` is single-threaded — never block.**

---

## 1. EA Skeleton

```mql5
// File: Experts/Sandboxed/Sandboxed_EA.mq5
#property copyright   "Sandboxed Trading"
#property link        "https://github.com/hopdev/Sandboxed"
#property version     "1.00"
#property description "ZMQ Bridge EA for Sandboxed mt5-bridge"
#property strict

#include <Sandboxed/Config.mqh>
#include <Sandboxed/ZmqClient.mqh>
#include <Sandboxed/MessageParser.mqh>
#include <Sandboxed/TradeExecutor.mqh>
#include <Sandboxed/PositionSnapshot.mqh>

ZmqClient        g_zmq;
TradeExecutor    g_executor;
MessageParser    g_parser;
PositionReporter g_reporter;

int OnInit() {
    if(!ValidateInputs())                    return INIT_PARAMETERS_INCORRECT;
    if(MQLInfoInteger(MQL_TESTER))           return INIT_SUCCEEDED;
    if(!g_zmq.Init(InpBridgeHost, InpSubPort, InpPubPort)) return INIT_FAILED;

    EventSetTimer(InpTimerIntervalS);
    PrintFormat("INFO: Sandboxed EA initialized magic=%d account=%s",
                InpMagicNumber, InpAccountId);
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
    EventKillTimer();
    g_zmq.Deinit();
    PrintFormat("INFO: Deinit reason=%d", reason);
}

void OnTick() {
    // Bridge EA does not trade per tick — intentionally empty
}

void OnTimer() {
    if(IsStopped()) return;

    string msg;
    int max_drain = 32;
    while(max_drain-- > 0 && g_zmq.Recv(msg, ZMQ_DONTWAIT)) {
        g_parser.Process(msg, g_executor);
    }

    g_reporter.SendHeartbeatIfDue(g_zmq);
    g_reporter.SendSnapshotIfDue(g_zmq);
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,
                        const MqlTradeResult &res) {
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
    if(req.magic != InpMagicNumber)              return;
    g_reporter.EmitFillEvent(g_zmq, trans);
}
```

---

## 2. Inputs / Config (`Include/Sandboxed/Config.mqh`)

```mql5
//+------------------------------------------------------------------+
//| Config.mqh — Inputs and constants                                |
//+------------------------------------------------------------------+
#define SANDBOXED_BASE_MAGIC          20260001UL
#define HEARTBEAT_INTERVAL_S          1
#define SNAPSHOT_INTERVAL_S           5
#define HEARTBEAT_TIMEOUT_S           10
#define MAX_MISSED_HEARTBEATS         5
#define ZMQ_RECONNECT_DELAY_MS        5000
#define MAX_MESSAGES_PER_TICK         32

input string InpBridgeHost           = "127.0.0.1";
input int    InpSubPort              = 5555;
input int    InpPubPort              = 5556;
input int    InpTimerIntervalS       = 1;
input string InpAccountId            = "";              // operator must set
input string InpHmacKey              = "";              // operator must set; 32+ chars
input ulong  InpMagicNumber          = 0;               // 0 = derive from account
input int    InpDeviation            = 20;              // points (slippage allowance)

bool ValidateInputs() {
    if(StringLen(InpAccountId) == 0)  { Print("ERROR: InpAccountId required"); return false; }
    if(StringLen(InpHmacKey) < 32)    { Print("ERROR: InpHmacKey too short");  return false; }
    if(InpSubPort <= 0 || InpPubPort <= 0) { Print("ERROR: ports invalid");    return false; }
    return true;
}
```

---

## 3. Trade Operations

### 3.1 Market Order (`TRADE_ACTION_DEAL`)

```mql5
// Source: https://www.mql5.com/en/docs/constants/structures/mqltraderequest
bool SendMarketOrder(string symbol, ENUM_ORDER_TYPE type, double volume,
                     double sl, double tp, ulong magic, string comment,
                     ulong &out_ticket) {
    if(!CanTrade()) return false;

    volume = NormalizeVolume(symbol, volume);

    double point     = SymbolInfoDouble(symbol, SYMBOL_POINT);
    double min_dist  = MathMax(SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL),
                               SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * point;
    double ask       = SymbolInfoDouble(symbol, SYMBOL_ASK);
    double bid       = SymbolInfoDouble(symbol, SYMBOL_BID);
    double ref_price = (type == ORDER_TYPE_BUY) ? ask : bid;

    if(sl > 0 && MathAbs(ref_price - sl) < min_dist) {
        sl = (type == ORDER_TYPE_BUY) ? ref_price - min_dist - point
                                      : ref_price + min_dist + point;
        PrintFormat("WARN: SL adjusted to respect STOPS_LEVEL: %.5f", sl);
    }
    if(tp > 0 && MathAbs(ref_price - tp) < min_dist) {
        tp = (type == ORDER_TYPE_BUY) ? ref_price + min_dist + point
                                      : ref_price - min_dist - point;
    }

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action       = TRADE_ACTION_DEAL;
    req.symbol       = symbol;
    req.volume       = volume;
    req.type         = type;
    req.price        = ref_price;
    req.sl           = NormalizePrice(symbol, sl);
    req.tp           = NormalizePrice(symbol, tp);
    req.deviation    = InpDeviation;
    req.magic        = magic;
    req.comment      = comment;
    req.type_filling = ProbeFillingMode(symbol);

    ResetLastError();
    if(!OrderSend(req, res)) {
        PrintFormat("ERROR: OrderSend failed retcode=%d comment=%s err=%d",
                    res.retcode, res.comment, GetLastError());
        return false;
    }
    if(res.retcode != TRADE_RETCODE_DONE) {
        PrintFormat("ERROR: Trade rejected retcode=%d comment=%s",
                    res.retcode, res.comment);
        return false;
    }
    out_ticket = res.order;
    return true;
}
```

### 3.2 Modify SL/TP (`TRADE_ACTION_SLTP`)

```mql5
bool ModifyPositionSLTP(ulong ticket, double new_sl, double new_tp) {
    if(!PositionSelectByTicket(ticket)) {
        PrintFormat("ERROR: ModifyPositionSLTP: ticket %d not found", ticket);
        return false;
    }
    string symbol = PositionGetString(POSITION_SYMBOL);

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action   = TRADE_ACTION_SLTP;
    req.position = ticket;            // REQUIRED on hedging accounts
    req.symbol   = symbol;
    req.sl       = NormalizePrice(symbol, new_sl);
    req.tp       = NormalizePrice(symbol, new_tp);
    req.magic    = InpMagicNumber;

    ResetLastError();
    if(!OrderSend(req, res)) {
        PrintFormat("ERROR: ModifyPositionSLTP retcode=%d err=%d",
                    res.retcode, GetLastError());
        return false;
    }
    return (res.retcode == TRADE_RETCODE_DONE);
}
```

### 3.3 Cancel Pending (`TRADE_ACTION_REMOVE`)

```mql5
bool CancelPendingOrder(ulong order_ticket) {
    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action = TRADE_ACTION_REMOVE;
    req.order  = order_ticket;

    ResetLastError();
    if(!OrderSend(req, res)) {
        PrintFormat("ERROR: CancelPendingOrder retcode=%d err=%d",
                    res.retcode, GetLastError());
        return false;
    }
    return (res.retcode == TRADE_RETCODE_DONE);
}
```

### 3.4 Close Position (hedging account)

```mql5
bool ClosePositionByMarket(ulong ticket) {
    if(!PositionSelectByTicket(ticket)) return false;

    string         symbol    = PositionGetString(POSITION_SYMBOL);
    double         vol       = PositionGetDouble(POSITION_VOLUME);
    long           pos_type  = PositionGetInteger(POSITION_TYPE);
    ENUM_ORDER_TYPE close_type = (pos_type == POSITION_TYPE_BUY)
                                ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action       = TRADE_ACTION_DEAL;
    req.symbol       = symbol;
    req.volume       = vol;
    req.type         = close_type;
    req.position     = ticket;        // REQUIRED — close THIS position, not open new
    req.price        = (close_type == ORDER_TYPE_SELL)
                       ? SymbolInfoDouble(symbol, SYMBOL_BID)
                       : SymbolInfoDouble(symbol, SYMBOL_ASK);
    req.deviation    = InpDeviation;
    req.magic        = InpMagicNumber;
    req.type_filling = ProbeFillingMode(symbol);

    ResetLastError();
    if(!OrderSend(req, res)) {
        PrintFormat("ERROR: ClosePosition retcode=%d err=%d",
                    res.retcode, GetLastError());
        return false;
    }
    return (res.retcode == TRADE_RETCODE_DONE);
}
```

### 3.5 Pending Limit/Stop (`TRADE_ACTION_PENDING`)

```mql5
bool SendPendingOrder(string symbol, ENUM_ORDER_TYPE type, double volume,
                      double price, double sl, double tp, ulong magic) {
    if(!CanTrade()) return false;
    volume = NormalizeVolume(symbol, volume);

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action       = TRADE_ACTION_PENDING;
    req.symbol       = symbol;
    req.volume       = volume;
    req.type         = type;                 // ORDER_TYPE_BUY_LIMIT etc.
    req.price        = NormalizePrice(symbol, price);
    req.sl           = NormalizePrice(symbol, sl);
    req.tp           = NormalizePrice(symbol, tp);
    req.magic        = magic;
    req.type_time    = ORDER_TIME_GTC;
    req.type_filling = ORDER_FILLING_RETURN; // pending must use RETURN

    ResetLastError();
    if(!OrderSend(req, res)) return false;
    return (res.retcode == TRADE_RETCODE_PLACED || res.retcode == TRADE_RETCODE_DONE);
}
```

---

## 4. Helpers

### 4.1 Volume / Price Normalization

```mql5
double NormalizeVolume(string symbol, double raw) {
    double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    double minv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    double maxv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
    double v    = MathFloor(raw / step) * step;
    return MathMax(minv, MathMin(maxv, v));
}

double NormalizePrice(string symbol, double price) {
    if(price <= 0) return 0;
    double tick = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
    return MathRound(price / tick) * tick;
}
```

### 4.2 Filling Mode Probe

```mql5
ENUM_ORDER_TYPE_FILLING ProbeFillingMode(string symbol) {
    long flags = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
    if((flags & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
    if((flags & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
    return ORDER_FILLING_RETURN;
}
```

### 4.3 CanTrade pre-trade Guards

```mql5
bool CanTrade() {
    if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) {
        Print("ERROR: AutoTrading disabled in terminal"); return false;
    }
    if(!MQLInfoInteger(MQL_TRADE_ALLOWED)) {
        Print("ERROR: EA trade not allowed");             return false;
    }
    if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)) {
        Print("ERROR: Account trade not allowed");        return false;
    }
    if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT)) {
        Print("ERROR: Expert trading not allowed");       return false;
    }
    return true;
}

bool IsHedgingAccount() {
    return ((int)AccountInfoInteger(ACCOUNT_MARGIN_MODE)
            == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
}
```

### 4.4 Magic Number Derivation

```mql5
ulong DeriveMagic(string account_id) {
    if(InpMagicNumber > 0) return InpMagicNumber;        // operator override

    uchar bytes[];
    StringToCharArray(account_id, bytes);
    uint hash = 5381;
    for(int i = 0; i < ArraySize(bytes); i++)
        hash = ((hash << 5) + hash) + bytes[i];           // djb2
    return SANDBOXED_BASE_MAGIC + (hash % 1000000);
}
```

---

## 5. Position Iteration

```mql5
// Collect tickets first — index shifts if positions close mid-loop
void ForEachOurPosition(void (*callback)(ulong ticket)) {
    ulong tickets[];
    int total = PositionsTotal();
    ArrayResize(tickets, total);
    int n = 0;
    for(int i = 0; i < total; i++) {
        ulong t = PositionGetTicket(i);
        if(t == 0) continue;
        if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
        tickets[n++] = t;
    }
    for(int i = 0; i < n; i++) callback(tickets[i]);
}

ulong FindPositionByOrderId(string order_id) {
    int total = PositionsTotal();
    for(int i = 0; i < total; i++) {
        ulong t = PositionGetTicket(i);
        if(t == 0) continue;
        if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
        if(PositionGetString(POSITION_COMMENT) == order_id) return t;
    }
    return 0;
}
```

---

## 6. Error Handling

```mql5
void HandleTradeError(const MqlTradeResult &res, string ctx) {
    int last_err = GetLastError();
    PrintFormat("ERROR: %s retcode=%d (%s) comment=%s err=%d",
                ctx, res.retcode, RetcodeName(res.retcode), res.comment, last_err);

    switch(res.retcode) {
        case TRADE_RETCODE_REQUOTE:        /* retry once with refresh */ break;
        case TRADE_RETCODE_INVALID_STOPS:  /* check STOPS_LEVEL */       break;
        case TRADE_RETCODE_INVALID_VOLUME: /* check VOLUME_STEP */       break;
        case TRADE_RETCODE_INVALID_FILL:   /* fall back IOC/RETURN */    break;
        case TRADE_RETCODE_NO_MONEY:       /* margin insufficient */     break;
        case TRADE_RETCODE_TRADE_DISABLED:
        case TRADE_RETCODE_CLIENT_DISABLES_AT:
                                            /* operator action */         break;
    }
}

string RetcodeName(uint code) {
    switch(code) {
        case 10004: return "REQUOTE";
        case 10006: return "REJECT";
        case 10008: return "PLACED";
        case 10009: return "DONE";
        case 10010: return "DONE_PARTIAL";
        case 10013: return "INVALID";
        case 10014: return "INVALID_VOLUME";
        case 10015: return "INVALID_PRICE";
        case 10016: return "INVALID_STOPS";
        case 10017: return "TRADE_DISABLED";
        case 10018: return "MARKET_CLOSED";
        case 10019: return "NO_MONEY";
        case 10025: return "NO_CHANGES";
        case 10027: return "CLIENT_DISABLES_AT";
        case 10029: return "FROZEN";
        case 10030: return "INVALID_FILL";
        case 10036: return "POSITION_CLOSED";
        case 10046: return "HEDGE_PROHIBITED";
    }
    return "UNKNOWN";
}
```

Full retcode table: https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes

---

## 7. Symbol Info Cache Pattern

```mql5
struct SymbolStatic {
    double point;
    double tick_size;
    double volume_step;
    double volume_min;
    double volume_max;
    int    digits;
};

class SymbolCache {
private:
    string         m_symbols[];
    SymbolStatic   m_cache[];
public:
    SymbolStatic* Get(string symbol);  // load on first miss; do NOT cache live fields
};
```

Live-only fields (never cache): `SYMBOL_BID`, `SYMBOL_ASK`, `SYMBOL_TRADE_STOPS_LEVEL`, `SYMBOL_TRADE_FREEZE_LEVEL`, `SYMBOL_FILLING_MODE`.

---

## 8. References

- MQL5 docs: https://www.mql5.com/en/docs
- Trade actions: https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_request_actions
- MqlTradeRequest: https://www.mql5.com/en/docs/constants/structures/mqltraderequest
- Retcode table: https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
- Hedging vs netting: https://www.mql5.com/en/book/automation/account/account_netting_hedge
- Position iteration: https://www.mql5.com/en/book/automation/experts/experts_position_list
- Sandboxed research synthesis: `docs/research/mql5-ea-patterns.md`
