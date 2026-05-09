# Research: MQL5 EA Patterns cho Epic 14 — MT5 Bridge EA

**Date:** 2026-05-07
**Requested for:** Epic 14 — MT5 EA MQL5 (ZMQ Bridge cho services/mt5-bridge)
**Status:** complete

---

## 1. Executive Summary (10 dòng)

Năm pattern quan trọng nhất cần nắm trước khi code:

1. **ZMQ DLL binding:** Dùng `dingmaotu/mql-zmq` (Apache-2.0, precompiled libzmq 4.2.x Win64 DLL có sẵn). String encode bắt buộc phải qua `StringToUtf8()` vì MQL5 dùng UTF-16. Polling ZMQ dùng `ZMQ_DONTWAIT` flag trong `OnTimer()` — EA không có thread nên không thể block.
2. **Trade operations:** `MqlTradeRequest` + `OrderSend()` là API chính. Không dùng `OrderModify/OrderSelect` (MT4 legacy). TRADE_ACTION_SLTP cho modify SL/TP, TRADE_ACTION_REMOVE cho cancel pending, TRADE_ACTION_DEAL cho market order, TRADE_ACTION_CLOSE_BY cho hedging close.
3. **SL/TP + Volume normalization:** Lỗi INVALID_STOPS và INVALID_VOLUME rất phổ biến. Phải dùng `MathFloor(vol/step)*step` cho volume (không dùng NormalizeDouble một mình), và kiểm tra `SYMBOL_TRADE_STOPS_LEVEL` + `SYMBOL_TRADE_FREEZE_LEVEL` cho SL/TP.
4. **HMAC-SHA256:** MQL5 có `CryptEncode(CRYPT_HASH_SHA256, ...)` nhưng KHÔNG implement HMAC natively. Phải dùng pure-MQL5 HMAC class (porting RFC 2104) — đã có implementation trên mql5.com.
5. **Strategy Tester + DLL:** DLL calls bị block trên remote test agents. Local tester cần enable "Allow DLL imports" và copy libsodium.dll vào `MQL5/Libraries` của tester. Đây là constraint quan trọng cho CI/test plan.

---

## 2. Reference Repos — Bảng Đánh Giá

| Repo | License | Stars (approx) | Last Commit | Fork-able? | Dùng để copy gì |
|------|---------|----------------|-------------|------------|-----------------|
| [dingmaotu/mql-zmq](https://github.com/dingmaotu/mql-zmq) | Apache-2.0 | ~500 | 2017-10-28 (v1.5, stale) | **YES** | DLL #import block, Socket.mqh pattern, StringToUtf8 conversion, non-blocking recv |
| [darwinex/dwx-zeromq-connector](https://github.com/darwinex/dwx-zeromq-connector) | BSD-3-Clause | ~800 | Archived | **Partial** | Message parsing pattern, OnTimer polling loop concept — nhưng code này MT4-only, đã archived. DWX Connect là successor (khác hẳn arch) |
| [ding9736/MQL5-ZeroMQ](https://github.com/ding9736/MQL5-ZeroMQ) | MIT | ~10 (mới) | 2024 | **YES (cẩn thận)** | ZAP auth wrapper, microsecond latency claim — nhưng quá mới, chưa battle-tested |
| [vivazzi/JAson](https://github.com/vivazzi/JAson) | MIT | ~100 | Active | **YES** | Pure-MQL5 JSON parser, không cần DLL |
| [ding9736/MQL5-JsonLib](https://github.com/ding9736/MQL5-JsonLib) | MIT | ~10 (mới) | 2024 | Partial | Nếu cần tính năng JSON nâng cao |

**Recommendation:** Core ZMQ binding lấy từ `dingmaotu/mql-zmq` (Apache-2.0, xác nhận license compatible). JSON lấy `vivazzi/JAson` (MIT). Không fork DWX — đã archived và MT4-centric.

---

## 3. Cấu Trúc File MQL5 Project

### 3.1 File extensions và folder

```
MQL5/
├── Experts/
│   └── Sandboxed/
│       └── Sandboxed_EA.mq5        ← entry point, chỉ chứa lifecycle hooks + wiring
├── Include/
│   └── Sandboxed/
│       ├── Config.mqh              ← input parameters + constants
│       ├── ZmqClient.mqh           ← ZMQ socket wrapper
│       ├── MessageParser.mqh       ← JSON parse + dispatch
│       ├── HmacSha256.mqh          ← HMAC verify
│       ├── TradeExecutor.mqh       ← OrderSend wrappers
│       └── PositionSnapshot.mqh    ← snapshot broadcast
│   └── Zmq/                       ← từ dingmaotu/mql-zmq (Apache-2.0)
│       ├── Zmq.mqh
│       ├── Socket.mqh
│       └── ZmqMsg.mqh
│   └── Json/
│       └── JAson.mqh              ← từ vivazzi/JAson (MIT)
└── Libraries/
    ├── MT5/
    │   ├── libzmq.dll             ← precompiled Win64, ZeroMQ 4.2.x
    │   └── libsodium.dll          ← precompiled Win64 (cần cho CURVE auth)
```

**Quy tắc:**
- `.mq5` = EA entry point. Không được chứa business logic trực tiếp.
- `.mqh` = include header. Mọi logic đặt ở đây, `#include` vào `.mq5`.
- `#include <File.mqh>` (angle bracket) → tìm trong `MQL5/Include/`.
- `#include "File.mqh"` (quotes) → tìm relative to current file.

### 3.2 Naming convention (cộng đồng MQL5 de-facto)

```mql5
// Global file-level variables: prefix g_
input int    InpMagicNumber = 20240001;   // EA inputs: prefix Inp
static int   s_retryCount;               // static local: prefix s_
int          g_zmqSocket;                // global: prefix g_
double       m_stopLoss;                 // class member: prefix m_

// Constants: UPPER_CASE
#define HEARTBEAT_INTERVAL_MS 1000
#define ZMQ_RECONNECT_DELAY_MS 5000

// Functions: PascalCase
void SendHeartbeat() { ... }
bool VerifyHmac(string msg, string sig) { ... }
```

### 3.3 EA properties block (đặt đầu file)

```mql5
#property copyright   "Sandboxed Trading"
#property link        "https://github.com/hopdev/Sandboxed"
#property version     "1.00"
#property description "ZMQ Bridge EA for Sandboxed mt5-bridge"
#property strict
```

---

## 4. Lifecycle Hooks — Chi Tiết

### 4.1 OnInit

```mql5
int OnInit()
{
    // 1. Validate inputs trước
    if(InpMagicNumber <= 0)
    {
        Print("ERROR: Magic number must be positive");
        return INIT_PARAMETERS_INCORRECT;  // Loại bỏ set param này khi optimize
    }

    // 2. Init ZMQ context + socket
    if(!g_zmqClient.Init(InpBridgeAddress, InpBridgePort))
    {
        Print("ERROR: Cannot connect to ZMQ bridge");
        return INIT_FAILED;  // EA unload khỏi chart
    }

    // 3. Set timer (milliseconds — dùng EventSetMillisecondTimer nếu cần < 1s)
    EventSetTimer(1);  // 1 giây

    Print("Sandboxed EA initialized. Magic=", InpMagicNumber,
          " Symbol=", _Symbol);
    return INIT_SUCCEEDED;
}
```

**ENUM_INIT_RETCODE values** (source: [mql5.com/en/docs/event_handlers/oninit](https://www.mql5.com/en/docs/event_handlers/oninit)):

| Constant | Meaning |
|----------|---------|
| `INIT_SUCCEEDED` (0) | Khởi tạo OK, EA chạy |
| `INIT_FAILED` | Lỗi không thể recover, EA unload |
| `INIT_PARAMETERS_INCORRECT` | Input params sai (khi optimize: skip set này) |
| `INIT_AGENT_NOT_SUITABLE` | Agent không phù hợp (dùng khi tester agent thiếu resource) |

### 4.2 OnDeinit

```mql5
void OnDeinit(const int reason)
{
    // Cleanup theo thứ tự ngược với Init
    EventKillTimer();
    g_zmqClient.Deinit();  // zmq_close + zmq_ctx_destroy

    string reasonStr;
    switch(reason)
    {
        case REASON_REMOVE:      reasonStr = "Removed from chart"; break;
        case REASON_RECOMPILE:   reasonStr = "Recompiled";         break;
        case REASON_CHARTCHANGE: reasonStr = "Symbol/TF changed";  break;
        case REASON_PARAMETERS:  reasonStr = "Inputs changed";     break;
        case REASON_ACCOUNT:     reasonStr = "Account changed";    break;
        case REASON_CLOSE:       reasonStr = "Terminal closed";    break;
        case REASON_INITFAILED:  reasonStr = "Init failed";        break;
        default:                 reasonStr = "Reason: " + reason;
    }
    Print("EA deinitialized. Reason: ", reasonStr);
}
```

**DEINIT REASON codes** (source: [mql5.com/en/docs/event_handlers/ondeinit](https://www.mql5.com/en/docs/event_handlers/ondeinit)):

| Code | Value | Constant |
|------|-------|----------|
| `REASON_PROGRAM` | 0 | ExpertRemove() called |
| `REASON_REMOVE` | 1 | EA removed from chart |
| `REASON_RECOMPILE` | 2 | EA recompiled |
| `REASON_CHARTCHANGE` | 3 | Symbol/period changed |
| `REASON_CHARTCLOSE` | 4 | Chart closed |
| `REASON_PARAMETERS` | 5 | Inputs changed |
| `REASON_ACCOUNT` | 6 | Account changed / reconnect |
| `REASON_TEMPLATE` | 7 | New template applied |
| `REASON_INITFAILED` | 8 | OnInit() returned non-zero |
| `REASON_CLOSE` | 9 | Terminal closed |

### 4.3 OnTimer — Event loop chính cho ZMQ

```mql5
void OnTimer()
{
    // 1. Guard: terminal còn cho phép trade không?
    if(IsStopped()) return;

    // 2. Heartbeat định kỳ
    static datetime s_lastHeartbeat = 0;
    if(TimeCurrent() - s_lastHeartbeat >= HEARTBEAT_INTERVAL_S)
    {
        SendHeartbeat();
        s_lastHeartbeat = TimeCurrent();
    }

    // 3. Poll ZMQ (non-blocking)
    string msg;
    while(g_zmqClient.Recv(msg, ZMQ_DONTWAIT))  // drain queue
    {
        if(!ProcessMessage(msg))
            Print("WARNING: Failed to process message: ", msg);
    }

    // 4. Periodic position snapshot
    static datetime s_lastSnapshot = 0;
    if(TimeCurrent() - s_lastSnapshot >= InpSnapshotIntervalS)
    {
        BroadcastPositionSnapshot();
        s_lastSnapshot = TimeCurrent();
    }
}
```

**Quan trọng:** MQL5 EA không có thread riêng. `OnTick()` và `OnTimer()` chạy trên cùng 1 thread. Nếu `OnTimer` block (do ZMQ blocking recv), tick sẽ bị miss. Luôn dùng `ZMQ_DONTWAIT`.

### 4.4 OnTick

Với EA này, OnTick không phải entry point chính (không trade theo signal tick). Tuy nhiên giữ lại để:

```mql5
void OnTick()
{
    // Với ZMQ bridge EA, OnTick chủ yếu để check trade permission
    // Không cần logic phức tạp ở đây
}
```

---

## 5. ZMQ Integration — Cookbook

### 5.1 DLL #import declarations (từ dingmaotu/mql-zmq)

Phần quan trọng nhất: khai báo DLL imports chính xác.

```mql5
// File: Include/Zmq/Zmq.mqh (lấy từ dingmaotu/mql-zmq, Apache-2.0)
#import "libzmq.dll"
    // Context
    intptr_t zmq_ctx_new();
    int      zmq_ctx_set(intptr_t context, int option_name, int option_value);
    int      zmq_ctx_destroy(intptr_t context);
    int      zmq_ctx_term(intptr_t context);

    // Socket
    intptr_t zmq_socket(intptr_t context, int type);
    int      zmq_close(intptr_t s);
    int      zmq_setsockopt(intptr_t s, int option_name, const uchar &option_value[], int option_len);
    int      zmq_getsockopt(intptr_t s, int option_name, uchar &option_value[], int &option_len);

    // Connect/Bind
    int zmq_bind(intptr_t s, const uchar &addr[]);
    int zmq_connect(intptr_t s, const uchar &addr[]);
    int zmq_unbind(intptr_t s, const uchar &addr[]);
    int zmq_disconnect(intptr_t s, const uchar &addr[]);

    // Send/Recv (buffer-based, không qua zmq_msg_t)
    int zmq_send(intptr_t s, const uchar &buf[], size_t len, int flags);
    int zmq_recv(intptr_t s, uchar &buf[], size_t len, int flags);

    // Error
    int      zmq_errno();
    intptr_t zmq_strerror(int errnum);
    void     zmq_version(int &major, int &minor, int &patch);
#import
```

**Socket type constants:**
```mql5
#define ZMQ_PAIR    0
#define ZMQ_PUB     1
#define ZMQ_SUB     2
#define ZMQ_REQ     3
#define ZMQ_REP     4
#define ZMQ_DEALER  5
#define ZMQ_ROUTER  6
#define ZMQ_PUSH    8
#define ZMQ_PULL    9

// Flags
#define ZMQ_DONTWAIT  1
#define ZMQ_SNDMORE   2

// Socket options
#define ZMQ_RCVTIMEO  27
#define ZMQ_SNDTIMEO  28
#define ZMQ_LINGER    17
#define ZMQ_SUBSCRIBE  6
```

Source: [github.com/dingmaotu/mql-zmq](https://github.com/dingmaotu/mql-zmq) — Apache-2.0.

### 5.2 String encoding — UTF-16 → UTF-8

MQL5 strings là UTF-16 (Win32 UNICODE). libzmq C API dùng UTF-8. **Phải convert** mọi string trước khi gửi qua DLL.

```mql5
// Helper: convert MQL5 string → UTF-8 byte array
void StringToUtf8(string text, uchar &utf8[])
{
    int len = StringToCharArray(text, utf8, 0, StringLen(text));
    ArrayResize(utf8, len - 1);  // bỏ null terminator
}

// Connect example
bool ConnectSocket(intptr_t socket, string address)
{
    uchar addr_utf8[];
    StringToUtf8(address, addr_utf8);
    int rc = zmq_connect(socket, addr_utf8);
    return (rc == 0);
}

// Send string message
int SendString(intptr_t socket, string msg, int flags = 0)
{
    uchar buf[];
    StringToUtf8(msg, buf);
    return zmq_send(socket, buf, ArraySize(buf), flags);
}

// Recv string message (non-blocking)
bool RecvString(intptr_t socket, string &msg)
{
    uchar buf[65536];
    int rc = zmq_recv(socket, buf, ArraySize(buf), ZMQ_DONTWAIT);
    if(rc < 0) return false;  // EAGAIN hoặc error
    if(rc == 0) return false;
    ArrayResize(buf, rc);
    msg = CharArrayToString(buf, 0, rc, CP_UTF8);
    return true;
}
```

Source: Pattern từ [github.com/dingmaotu/mql-zmq/blob/master/Include/Zmq/Socket.mqh](https://github.com/dingmaotu/mql-zmq/blob/master/Include/Zmq/Socket.mqh).

### 5.3 Calling convention (quan trọng)

- Win64: CHỈ có một calling convention (Microsoft x64). Không có stdcall vs cdecl confusion.
- Win32 (MT4): có thể có vấn đề — nhưng Epic 14 chỉ dùng MT5 (64-bit). An toàn.
- MQL5 Win64 hỗ trợ cả cdecl và stdcall DLL — runtime tự wrap.

### 5.4 ZMQ initialization pattern

```mql5
// Trong OnInit():
intptr_t g_ctx  = 0;
intptr_t g_subSock = 0;   // nhận command từ bridge (DEALER hoặc SUB)
intptr_t g_pubSock = 0;   // gửi result/snapshot về bridge (PUB hoặc PUSH)

bool ZmqInit(string bridgeHost, int subPort, int pubPort)
{
    g_ctx = zmq_ctx_new();
    if(g_ctx == 0) { Print("zmq_ctx_new failed"); return false; }

    // SUB socket — nhận orders từ bridge
    g_subSock = zmq_socket(g_ctx, ZMQ_DEALER);
    if(g_subSock == 0) { Print("zmq_socket failed"); return false; }

    // Set linger = 0: khi close, không block chờ pending messages
    uchar linger[4]; int zero = 0;
    IntToCharArray(zero, linger);
    zmq_setsockopt(g_subSock, ZMQ_LINGER, linger, 4);

    // Set recv timeout
    int timeout_ms = 0;
    IntToCharArray(timeout_ms, linger);
    zmq_setsockopt(g_subSock, ZMQ_RCVTIMEO, linger, 4);

    string subAddr = StringFormat("tcp://%s:%d", bridgeHost, subPort);
    if(!ConnectSocket(g_subSock, subAddr)) return false;

    // PUB socket — gửi kết quả về
    g_pubSock = zmq_socket(g_ctx, ZMQ_PUSH);
    if(g_pubSock == 0) return false;
    IntToCharArray(zero, linger);
    zmq_setsockopt(g_pubSock, ZMQ_LINGER, linger, 4);
    string pubAddr = StringFormat("tcp://%s:%d", bridgeHost, pubPort);
    if(!ConnectSocket(g_pubSock, pubAddr)) return false;

    return true;
}

void ZmqDeinit()
{
    if(g_subSock != 0) { zmq_close(g_subSock); g_subSock = 0; }
    if(g_pubSock != 0) { zmq_close(g_pubSock); g_pubSock = 0; }
    if(g_ctx != 0)     { zmq_ctx_destroy(g_ctx); g_ctx = 0; }
}
```

### 5.5 Reconnect pattern

```mql5
// Trong OnTimer — detect disconnect và reconnect
static int s_missedHeartbeats = 0;
static datetime s_lastAck = 0;

if(TimeCurrent() - s_lastAck > HEARTBEAT_TIMEOUT_S)
{
    s_missedHeartbeats++;
    if(s_missedHeartbeats >= MAX_MISSED_HEARTBEATS)
    {
        Print("Bridge timeout. Reconnecting...");
        ZmqDeinit();
        Sleep(ZMQ_RECONNECT_DELAY_MS);
        ZmqInit(InpBridgeHost, InpSubPort, InpPubPort);
        s_missedHeartbeats = 0;
    }
}
```

### 5.6 IntToCharArray helper (set sockopt)

MQL5 không có built-in `IntToCharArray` cho setsockopt. Cần viết:

```mql5
void IntToBytes(int value, uchar &arr[])
{
    ArrayResize(arr, 4);
    arr[0] = (uchar)(value & 0xFF);
    arr[1] = (uchar)((value >> 8) & 0xFF);
    arr[2] = (uchar)((value >> 16) & 0xFF);
    arr[3] = (uchar)((value >> 24) & 0xFF);
}
```

---

## 6. Trade Operations Cookbook

### 6.1 TRADE_ACTION_DEAL — Market Order BUY/SELL

```mql5
// Source: https://www.mql5.com/en/docs/constants/structures/mqltraderequest
bool SendMarketOrder(string symbol, ENUM_ORDER_TYPE type, double volume,
                     double sl, double tp, ulong magic, string comment,
                     ulong &out_ticket)
{
    // Step 1: Normalize volume
    double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    double lot_min  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    double lot_max  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
    volume = MathFloor(volume / lot_step) * lot_step;
    volume = MathMax(lot_min, MathMin(lot_max, volume));

    // Step 2: Validate SL/TP
    int stops_level  = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
    int freeze_level = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
    double point     = SymbolInfoDouble(symbol, SYMBOL_POINT);
    double min_dist  = MathMax(stops_level, freeze_level) * point;

    double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
    double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
    double ref_price = (type == ORDER_TYPE_BUY) ? ask : bid;

    // Kiểm tra SL/TP đủ xa ref_price
    if(sl > 0)
    {
        double sl_dist = MathAbs(ref_price - sl);
        if(sl_dist < min_dist)
        {
            PrintFormat("WARN: SL too close: dist=%.5f min=%.5f. Adjusting.", sl_dist, min_dist);
            sl = (type == ORDER_TYPE_BUY)
                 ? ref_price - min_dist - point
                 : ref_price + min_dist + point;
        }
    }

    // Step 3: Build request
    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action       = TRADE_ACTION_DEAL;
    req.symbol       = symbol;
    req.volume       = volume;
    req.type         = type;
    req.price        = ref_price;
    req.sl           = sl;
    req.tp           = tp;
    req.deviation    = InpDeviation;         // slippage allowance in points
    req.magic        = magic;
    req.comment      = comment;
    req.type_filling = ORDER_FILLING_FOK;    // broker-dependent, fallback to IOC

    ResetLastError();
    if(!OrderSend(req, res))
    {
        PrintFormat("OrderSend failed: retcode=%d comment=%s err=%d",
                    res.retcode, res.comment, GetLastError());
        return false;
    }
    if(res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_PLACED)
    {
        PrintFormat("Trade rejected: retcode=%d comment=%s", res.retcode, res.comment);
        return false;
    }
    out_ticket = res.order;
    return true;
}
```

**ORDER_FILLING policy:** FTMO MT5 thường là `ORDER_FILLING_FOK` (Fill or Kill). Nếu reject với `TRADE_RETCODE_INVALID_FILL`, thử `ORDER_FILLING_IOC`. Cách kiểm tra:

```mql5
long filling = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
if((filling & SYMBOL_FILLING_FOK) != 0)
    req.type_filling = ORDER_FILLING_FOK;
else if((filling & SYMBOL_FILLING_IOC) != 0)
    req.type_filling = ORDER_FILLING_IOC;
else
    req.type_filling = ORDER_FILLING_RETURN;
```

### 6.2 TRADE_ACTION_SLTP — Modify SL/TP của position

```mql5
bool ModifyPositionSLTP(ulong ticket, double new_sl, double new_tp)
{
    if(!PositionSelectByTicket(ticket))
    {
        PrintFormat("ModifyPositionSLTP: ticket %d not found", ticket);
        return false;
    }
    string symbol = PositionGetString(POSITION_SYMBOL);

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action   = TRADE_ACTION_SLTP;
    req.position = ticket;
    req.symbol   = symbol;
    req.sl       = new_sl;
    req.tp       = new_tp;
    // magic không bắt buộc cho SLTP nhưng tốt nên fill
    req.magic    = InpMagicNumber;

    ResetLastError();
    if(!OrderSend(req, res))
    {
        PrintFormat("ModifyPositionSLTP failed: retcode=%d err=%d",
                    res.retcode, GetLastError());
        return false;
    }
    return (res.retcode == TRADE_RETCODE_DONE);
}
```

**Hedging vs Netting:** Trên hedging account (FTMO MT5 thường dùng hedging), bắt buộc fill `position` ticket. Trên netting account, có thể bỏ qua ticket và dùng symbol. Luôn check:

```mql5
bool IsHedgingAccount()
{
    return ((int)AccountInfoInteger(ACCOUNT_MARGIN_MODE)
            == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
}
```

Source: [mql5.com/en/book/automation/account/account_netting_hedge](https://www.mql5.com/en/book/automation/account/account_netting_hedge).

### 6.3 TRADE_ACTION_REMOVE — Cancel pending order

```mql5
bool CancelPendingOrder(ulong order_ticket)
{
    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action = TRADE_ACTION_REMOVE;
    req.order  = order_ticket;

    ResetLastError();
    if(!OrderSend(req, res))
    {
        PrintFormat("CancelPendingOrder failed: retcode=%d err=%d",
                    res.retcode, GetLastError());
        return false;
    }
    return (res.retcode == TRADE_RETCODE_DONE);
}
```

### 6.4 TRADE_ACTION_CLOSE_BY — Close position (hedging mode)

Cách close position trên hedging account: gửi market order ngược chiều với volume bằng position.

```mql5
bool ClosePositionByMarket(ulong ticket)
{
    if(!PositionSelectByTicket(ticket))
        return false;

    string symbol    = PositionGetString(POSITION_SYMBOL);
    double vol       = PositionGetDouble(POSITION_VOLUME);
    long   pos_type  = PositionGetInteger(POSITION_TYPE);

    // Chiều ngược lại
    ENUM_ORDER_TYPE close_type = (pos_type == POSITION_TYPE_BUY)
                                 ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action   = TRADE_ACTION_DEAL;
    req.symbol   = symbol;
    req.volume   = vol;
    req.type     = close_type;
    req.position = ticket;  // QUAN TRỌNG: chỉ định position để close đúng
    req.price    = (close_type == ORDER_TYPE_SELL)
                   ? SymbolInfoDouble(symbol, SYMBOL_BID)
                   : SymbolInfoDouble(symbol, SYMBOL_ASK);
    req.deviation    = InpDeviation;
    req.magic        = InpMagicNumber;
    req.type_filling = ORDER_FILLING_FOK;

    ResetLastError();
    if(!OrderSend(req, res))
    {
        PrintFormat("ClosePosition failed: retcode=%d err=%d",
                    res.retcode, GetLastError());
        return false;
    }
    return (res.retcode == TRADE_RETCODE_DONE);
}
```

### 6.5 TRADE_ACTION_PENDING — Limit/Stop order

```mql5
// Ví dụ BUY_LIMIT
bool SendPendingOrder(string symbol, ENUM_ORDER_TYPE type, double volume,
                      double price, double sl, double tp, ulong magic)
{
    // Normalize volume (như trên)
    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action      = TRADE_ACTION_PENDING;
    req.symbol      = symbol;
    req.volume      = volume;
    req.type        = type;     // ORDER_TYPE_BUY_LIMIT, etc.
    req.price       = price;
    req.sl          = sl;
    req.tp          = tp;
    req.magic       = magic;
    req.type_time   = ORDER_TIME_GTC;
    req.type_filling = ORDER_FILLING_RETURN;

    ResetLastError();
    if(!OrderSend(req, res)) { /* handle */ return false; }
    return (res.retcode == TRADE_RETCODE_PLACED || res.retcode == TRADE_RETCODE_DONE);
}
```

### 6.6 MqlTradeResult retcode taxonomy

Source: [mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes](https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes)

| Code | Constant | Ý nghĩa |
|------|----------|---------|
| 10004 | TRADE_RETCODE_REQUOTE | Broker requote giá — retry với giá mới |
| 10006 | TRADE_RETCODE_REJECT | Server từ chối |
| 10008 | TRADE_RETCODE_PLACED | Pending order đã đặt |
| 10009 | TRADE_RETCODE_DONE | Market order hoàn thành |
| 10010 | TRADE_RETCODE_DONE_PARTIAL | Fill một phần (IOC) |
| 10013 | TRADE_RETCODE_INVALID | Request không hợp lệ (kiểm tra fields) |
| 10014 | TRADE_RETCODE_INVALID_VOLUME | Volume sai — check normalization |
| 10015 | TRADE_RETCODE_INVALID_PRICE | Price sai |
| 10016 | TRADE_RETCODE_INVALID_STOPS | SL/TP quá gần — check STOPS_LEVEL |
| 10017 | TRADE_RETCODE_TRADE_DISABLED | Trading bị disable ở server |
| 10018 | TRADE_RETCODE_MARKET_CLOSED | Thị trường đóng cửa |
| 10019 | TRADE_RETCODE_NO_MONEY | Không đủ margin |
| 10025 | TRADE_RETCODE_NO_CHANGES | SL/TP không đổi (SLTP request) |
| 10027 | TRADE_RETCODE_CLIENT_DISABLES_AT | Autotrading bị tắt ở terminal |
| 10029 | TRADE_RETCODE_FROZEN | Position/order đang freeze (check FREEZE_LEVEL) |
| 10030 | TRADE_RETCODE_INVALID_FILL | Filling type không được broker support |
| 10036 | TRADE_RETCODE_POSITION_CLOSED | Position đã đóng rồi |
| 10045 | TRADE_RETCODE_FIFO_CLOSE | Chỉ cho phép close theo FIFO |
| 10046 | TRADE_RETCODE_HEDGE_PROHIBITED | Hedging bị cấm ở account này |

---

## 7. Position Management

### 7.1 Iterate all open positions

```mql5
// Source: https://www.mql5.com/en/book/automation/experts/experts_position_list
void BroadcastPositionSnapshot()
{
    int total = PositionsTotal();
    // Collect vào JSON array
    string json = "{\"type\":\"position_snapshot\",\"positions\":[";

    for(int i = 0; i < total; i++)
    {
        ulong ticket = PositionGetTicket(i);  // cũng select position này
        if(ticket == 0) continue;

        string symbol   = PositionGetString(POSITION_SYMBOL);
        double volume   = PositionGetDouble(POSITION_VOLUME);
        double open_prc = PositionGetDouble(POSITION_PRICE_OPEN);
        double sl       = PositionGetDouble(POSITION_SL);
        double tp       = PositionGetDouble(POSITION_TP);
        double profit   = PositionGetDouble(POSITION_PROFIT);
        long   pos_type = PositionGetInteger(POSITION_TYPE);
        long   magic    = PositionGetInteger(POSITION_MAGIC);
        string comment  = PositionGetString(POSITION_COMMENT);

        if(i > 0) json += ",";
        json += StringFormat(
            "{\"ticket\":%d,\"symbol\":\"%s\",\"type\":\"%s\","
            "\"volume\":%.2f,\"open_price\":%.5f,"
            "\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f,"
            "\"magic\":%d,\"comment\":\"%s\"}",
            ticket, symbol,
            (pos_type == POSITION_TYPE_BUY) ? "BUY" : "SELL",
            volume, open_prc, sl, tp, profit, magic, comment
        );
    }
    json += "]}";
    SendString(g_pubSock, json);
}
```

**Thứ tự lặp:** `PositionGetTicket(i)` đồng thời select position đó. Khi lặp từ đầu đến cuối, index có thể shift nếu có position bị close trong vòng lặp — an toàn nhất là collect tickets trước rồi xử lý.

### 7.2 Select position theo magic number

```mql5
// Tìm position của EA này (lọc theo magic)
ulong FindPositionByOrderId(string order_id)
{
    int total = PositionsTotal();
    for(int i = 0; i < total; i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0) continue;
        if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
        if(PositionGetString(POSITION_COMMENT) == order_id) return ticket;
    }
    return 0;
}
```

**Convention:** Lưu `order_id` của bridge vào `comment` field khi mở lệnh. Dùng để correlate về sau.

---

## 8. Symbol Info và Normalization

```mql5
// Normalize volume đúng cách
// Source: https://www.mql5.com/en/forum/432769
double NormalizeVolume(string symbol, double raw_volume)
{
    double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    double minv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    double maxv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
    double vol  = MathFloor(raw_volume / step) * step;
    return MathMax(minv, MathMin(maxv, vol));
}

// Normalize price (SL/TP) đúng cách — dùng tick size, KHÔNG dùng NormalizeDouble
double NormalizePrice(string symbol, double price)
{
    double tick = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
    return MathRound(price / tick) * tick;
}

// Check SL/TP hợp lệ với stops_level
bool IsSLTPValid(string symbol, ENUM_ORDER_TYPE order_type,
                 double entry_price, double sl, double tp)
{
    long   stops_level  = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
    long   freeze_level = SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
    double point        = SymbolInfoDouble(symbol, SYMBOL_POINT);
    double min_dist     = MathMax(stops_level, freeze_level) * point;

    bool sl_ok = (sl == 0) ||
                 (order_type == ORDER_TYPE_BUY  && (entry_price - sl) >= min_dist) ||
                 (order_type == ORDER_TYPE_SELL && (sl - entry_price) >= min_dist);
    bool tp_ok = (tp == 0) ||
                 (order_type == ORDER_TYPE_BUY  && (tp - entry_price) >= min_dist) ||
                 (order_type == ORDER_TYPE_SELL && (entry_price - tp) >= min_dist);
    return sl_ok && tp_ok;
}
```

**Quan trọng:** `SYMBOL_TRADE_STOPS_LEVEL` đơn vị là POINTS (không phải pip). Một số broker dynamic thay đổi level này. Phải query live mỗi lần trade.

---

## 9. Error Handling Pattern

```mql5
// Pattern chuẩn: ResetLastError() trước OrderSend, check cả hai
void HandleTradeError(const MqlTradeResult &res, string context)
{
    int last_err = GetLastError();
    switch(res.retcode)
    {
        case TRADE_RETCODE_REQUOTE:
            // Retry với giá mới sau vài tick
            Print(context, ": Requote. Retry next tick.");
            break;
        case TRADE_RETCODE_NO_MONEY:
            Print(context, ": Insufficient margin. Check account balance.");
            break;
        case TRADE_RETCODE_INVALID_STOPS:
            Print(context, ": Invalid stops. Check STOPS_LEVEL. retcode=10016");
            break;
        case TRADE_RETCODE_INVALID_VOLUME:
            Print(context, ": Invalid volume. Check VOLUME_STEP normalization.");
            break;
        case TRADE_RETCODE_MARKET_CLOSED:
            Print(context, ": Market closed.");
            break;
        case TRADE_RETCODE_TRADE_DISABLED:
        case TRADE_RETCODE_CLIENT_DISABLES_AT:
            Print(context, ": Trading disabled. Check AutoTrading button.");
            break;
        default:
            PrintFormat("%s: retcode=%d comment=%s err=%d",
                        context, res.retcode, res.comment, last_err);
    }
}
```

**Thời gian:**
- `TimeCurrent()` — server time (timezone của broker). Dùng cho trade timestamps.
- `TimeGMT()` — UTC time. Dùng cho heartbeat, ISO 8601 sync với engine.
- `TimeLocal()` — local machine time. KHÔNG dùng cho trading logic.

---

## 10. JSON Parsing — JAson Library

### 10.1 Setup

Copy `JAson.mqh` từ [github.com/vivazzi/JAson](https://github.com/vivazzi/JAson) (MIT) vào `MQL5/Include/Json/JAson.mqh`.

```mql5
#include <Json/JAson.mqh>

// Parse incoming message
bool ParseCommand(string raw_json, string &msg_type, string &order_id,
                  double &volume, double &price, double &sl, double &tp)
{
    CJAVal data;
    if(!data.Deserialize(raw_json))
    {
        Print("JSON parse error: ", raw_json);
        return false;
    }

    msg_type = data["type"].ToStr();
    order_id = data["order_id"].ToStr();
    volume   = data["volume"].ToDbl();
    price    = data["price"].ToDbl();
    sl       = data["sl"].ToDbl();
    tp       = data["tp"].ToDbl();
    return true;
}
```

**Dispatch pattern:**

```mql5
void ProcessMessage(string raw)
{
    CJAVal msg;
    if(!msg.Deserialize(raw)) { Print("Malformed JSON: ", raw); return; }

    string t = msg["type"].ToStr();
    if(t == "order")           { HandleOrder(msg);        }
    else if(t == "modify_order") { HandleModifyOrder(msg); }
    else if(t == "cancel_order") { HandleCancelOrder(msg); }
    else if(t == "close_position") { HandleClosePosition(msg); }
    else { PrintFormat("Unknown message type: %s", t); }
}
```

---

## 11. HMAC-SHA256 — Implementation Options

### 11.1 Native CryptEncode — KHÔNG phải HMAC

```mql5
// CryptEncode native HỖ TRỢ SHA-256 HASH nhưng KHÔNG phải HMAC.
// Nếu chỉ cần SHA-256 (không key), dùng:
uchar data[], result[], empty_key[];
StringToCharArray("message", data);
CryptEncode(CRYPT_HASH_SHA256, data, empty_key, result);
// result[] chứa 32-byte SHA-256 hash
```

HMAC = hash(key XOR opad || hash(key XOR ipad || message)) — **phải implement thủ công**.

### 11.2 Pure-MQL5 HMAC class (recommended)

Source: [mql5.com/en/articles/16357](https://www.mql5.com/en/articles/16357) — pure MQL5, không cần DLL.

```mql5
// File: Include/Sandboxed/HmacSha256.mqh
// Based on: https://www.mql5.com/en/articles/16357
// Implement RFC 2104 HMAC-SHA256 using native CryptEncode(CRYPT_HASH_SHA256)
#include <Sandboxed/HmacSha256.mqh>

bool VerifyHmac(string message, string expected_hex, string shared_key)
{
    HMacSha256 hmac(shared_key, message);
    string computed = hmac.hexval;
    // Constant-time compare (đơn giản hóa — production cần timing-safe compare)
    return (computed == expected_hex);
}
```

**CryptEncode constants** (source: [mql5.com/en/docs/common/cryptencode](https://www.mql5.com/en/docs/common/cryptencode)):
- `CRYPT_HASH_SHA256` — SHA-256 hash (dùng làm building block HMAC)
- `CRYPT_HASH_SHA1` — SHA-1
- `CRYPT_HASH_MD5` — MD5
- `CRYPT_DES` — DES encrypt/decrypt
- `CRYPT_AES128`, `CRYPT_AES256` — AES
- `CRYPT_BASE64` — Base64 encode
- `CRYPT_ARCH_ZIP` — ZIP compress

### 11.3 Expected JSON command format (khớp với bridge schema)

```json
{
  "type": "order",
  "order_id": "uuid-v4",
  "account_id": "acc-123",
  "action": "BUY",
  "symbol": "EURUSD",
  "volume": 0.1,
  "price": 1.08500,
  "sl": 1.08200,
  "tp": 1.09000,
  "hmac": "hex-sha256-signature",
  "timestamp": "2026-05-07T10:00:00Z"
}
```

HMAC tính trên: `message = type + order_id + account_id + action + symbol + volume + price + timestamp` (exact field list cần đồng bộ với Python engine — open question #1).

---

## 12. Common Bugs và Pitfalls

### Bug 1: INVALID_STOPS do không check STOPS_LEVEL

```mql5
// WRONG: hardcode khoảng cách
double sl = close - 200 * _Point;  // 200 points — có thể < STOPS_LEVEL broker

// CORRECT: query động
double min_dist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
double sl = close - MathMax(200, min_dist + 10) * _Point;
```

### Bug 2: Volume rounding sai

```mql5
// WRONG: chỉ dùng NormalizeDouble
double vol = NormalizeDouble(raw_volume, 2);  // Không đảm bảo multiple of VOLUME_STEP

// CORRECT: floor to step
double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
double vol  = MathFloor(raw_volume / step) * step;
```

### Bug 3: Magic number collision multi-EA

```mql5
// Nếu chạy nhiều EA cùng lúc, dùng unique magic per account_id:
// magic = hash(account_id) % 1000000 + SANDBOXED_BASE_MAGIC
// Base magic được khai báo trong Config.mqh
#define SANDBOXED_BASE_MAGIC 20260001UL
```

### Bug 4: Blocking ZMQ recv trong OnTick/OnTimer

```mql5
// WRONG: blocking recv — freeze terminal
zmq_recv(socket, buf, sizeof(buf), 0);  // flags=0 = blocking

// CORRECT: non-blocking
zmq_recv(socket, buf, sizeof(buf), ZMQ_DONTWAIT);
// Nếu rc < 0, kiểm tra zmq_errno() == EAGAIN
```

### Bug 5: String allocation trong tight loop

```mql5
// WRONG: StringFormat trong OnTick hot path → GC pressure
void OnTick() {
    string msg = StringFormat("price=%.5f", Ask);  // allocate mỗi tick
    ...
}

// CORRECT: dùng static buffer hoặc chỉ build string khi cần gửi
```

### Bug 6: DLL import sau khi EA đã load (KHÔNG thể reload DLL)

Nếu libzmq.dll bị lock bởi process khác, EA không thể load. Phải restart MT5 terminal.

### Bug 7: OrderSend trả true nhưng chưa fill

```mql5
// OrderSend() = true chỉ nghĩa là request được chấp nhận,
// KHÔNG đảm bảo đã fill. Phải check result.retcode:
if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
    // Thực sự filled
}
```

### Bug 8: Dùng MT4 legacy API trong MQL5

```mql5
// SAI (MT4 style — không tồn tại trong MQL5):
OrderSelect(ticket, SELECT_BY_TICKET);
OrderModify(ticket, price, sl, tp, expiry, clrRed);

// ĐÚNG (MQL5):
PositionSelectByTicket(ticket);
// + TRADE_ACTION_SLTP để modify
```

---

## 13. FTMO Compliance Checks

### 13.1 Pre-trade guards

```mql5
bool CanTrade()
{
    // Check terminal autotrading
    if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
    {
        Print("AutoTrading disabled in terminal");
        return false;
    }

    // Check EA-level trade permission
    if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
    {
        Print("EA trade not allowed (check EA settings)");
        return false;
    }

    // Check account trade allowed
    if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
    {
        Print("Account trade not allowed");
        return false;
    }

    // Check account expert allowed
    if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
    {
        Print("Expert trading not allowed on this account");
        return false;
    }

    return true;
}
```

### 13.2 FTMO compliance: engine-side enforcement

**Quan trọng:** Theo Epic 14 design, Sandboxed EA **không** tự tính daily loss / max drawdown. Rule engine upstream (Python, Epic 8-11) đã enforce. EA chỉ:
1. Execute command nếu HMAC verify OK
2. Reject command với error response nếu `CanTrade()` = false
3. Forward retcode từ broker về engine

Không implement drawdown guard trùng lặp với engine — tránh race condition.

### 13.3 Magic number convention

```mql5
// Magic number encode: [FTMO_ACCOUNT_PREFIX][STRATEGY_ID]
// Example: account 123456 dùng strategy 1 → magic = 12345601
// Giúp audit trong MT5 trade history và FTMO compliance report
input ulong InpMagicNumber = 0;  // 0 = auto-derive từ account + strategy
```

### 13.4 Deviation (slippage) parameter

FTMO cho phép market execution với deviation hợp lý. Recommend:
- Forex majors: 10-20 points
- Indices/metals: 20-50 points
- Không set quá thấp (0-3) → nhiều reject do spread

### 13.5 Lot size limits cho FTMO Challenge

FTMO không có hard lot limit trong rules, nhưng max exposure per trade bị kiểm soát bởi risk rule. EA nên verify từ `Order.volume` của bridge — engine đã tính.

---

## 14. Testing MT5 EA

### 14.1 Strategy Tester + DLL limitations

**Critical constraint:** DLL calls bị chặn trên remote optimization agents. Chỉ local agent mới chạy được.

Source: [github.com/dingmaotu/mql-zmq/issues/19](https://github.com/dingmaotu/mql-zmq/issues/19)

Setup để test với DLL trong Strategy Tester:
1. Enable "Allow DLL imports" trong MT5 Options > Expert Advisors.
2. Copy `libzmq.dll` và `libsodium.dll` vào `[MT5_data]/MQL5/Libraries/`.
3. Copy cả hai DLLs vào thư mục tester agent: `[MT5_data]/tester/MQL5/Libraries/` (làm một lần).
4. Với local test, không cần ZMQ connection thực — EA init sẽ fail nếu bridge không chạy.

### 14.2 Testing strategy cho ZMQ-dependent EA

EA phụ thuộc ZMQ không thể test đầy đủ trong Strategy Tester. Approach:

```
Test tier 1 — Unit logic (no ZMQ):
  ├── Script test SL/TP normalization functions
  ├── Script test HMAC verify với known test vectors
  └── Script test JSON parse với JAson library

Test tier 2 — Integration (local MT5 + bridge):
  ├── Start mt5-bridge (Rust) locally
  ├── Attach EA to demo chart
  ├── Send mock order JSON qua bridge
  └── Verify OrderSend kết quả + OrderResult response

Test tier 3 — E2E (MT5 demo account):
  ├── Full lifecycle: submit → fill → modify → close
  ├── Measure latency P50/P95
  └── Verify position snapshot khớp với engine state
```

### 14.3 Expert log location

```
Windows: C:\Users\[user]\AppData\Roaming\MetaQuotes\Terminal\[hash]\logs\
         Hoặc: [MT5 data folder]\logs\
```

Log format: `YYYY.MM.DD HH:MM:SS.mmm  EA_name  [message]`

Dùng `PrintFormat()` cho log có format. Không dùng `Print()` trong hot path.

---

## 15. Build và Deploy

### 15.1 MetaEditor compile — command line

```bash
# Windows
metaeditor64.exe /compile:"C:\path\to\MQL5\Experts\Sandboxed\Sandboxed_EA.mq5" /log

# Windows — chỉ định include path
metaeditor64.exe /compile:"path\to\EA.mq5" /inc:"C:\MT5\MQL5"

# Linux (Wine) — xác nhận bằng mql5.com forum
wine ~/.wine/drive_c/Program\ Files/MetaTrader\ 5/metaeditor64.exe \
     /compile:"Z:/path/to/EA.mq5" /log
```

Source: [mql5.com/en/forum/367908](https://www.mql5.com/en/forum/367908).

**Note:** Linux Wine compile path cần thêm testing — chưa xác nhận với libzmq DLL presence. Xem Open Questions.

### 15.2 File deployment checklist

```
[MT5 data folder]/
├── MQL5/
│   ├── Experts/Sandboxed/
│   │   └── Sandboxed_EA.ex5      ← compiled EA
│   ├── Include/Sandboxed/        ← source headers
│   ├── Include/Zmq/              ← từ dingmaotu/mql-zmq
│   ├── Include/Json/             ← JAson.mqh
│   └── Libraries/
│       ├── MT5/libzmq.dll        ← precompiled Win64
│       └── MT5/libsodium.dll     ← precompiled Win64
```

### 15.3 DLL distribution và licensing

**libzmq** từ `dingmaotu/mql-zmq`:
- libzmq C library: LGPLv3 + Static Linking Exception.
- **LGPLv3 với Static Linking Exception cho phép link dynamic (DLL) với proprietary code** mà không yêu cầu open-source EA.
- Precompiled DLL trong repo: ZeroMQ 4.2.0 (VC2015) hoặc 4.2.2 (VC2010 — better WINE compat).
- DLL wrapper code trong `dingmaotu/mql-zmq` (`.mqh` files): **Apache-2.0** — hoàn toàn free dùng trong proprietary EA.

**Kết luận:** Dùng precompiled DLL từ `dingmaotu/mql-zmq` là license-safe cho closed-source FTMO bot. Chỉ cần note trong distribution rằng libzmq được distribute theo LGPLv3.

**libsodium**: ISC license — no restriction.

### 15.4 EA attach to chart

1. Mở MT5 → Navigator → Expert Advisors → tìm `Sandboxed_EA`.
2. Kéo vào chart symbol phù hợp (hoặc EURUSD general chart).
3. Inputs dialog: nhập `BridgeHost`, `SubPort`, `PubPort`, `MagicNumber`, `AccountId`.
4. Enable "Allow Autotrading" và "Allow DLL imports".
5. Verify trong Journal tab: `Sandboxed EA initialized`.

---

## 16. Existing Project Code

Không tìm thấy `.mq5` hay `.mqh` files trong project (chưa có MQL5 code).

**Bridge protocol** đã define tại `services/mt5-bridge/src/protocol.rs` và `src/models/order.rs`:
- `MessageType`: Tick, Order, OrderResult, Heartbeat, Ack, Error
- `Order` struct: action (BUY/SELL), symbol, volume, price, sl, tp, order_id, account_id
- `OrderResult`: order_id, status (filled/partially_filled/rejected/error), fill_price, slippage, timestamp, error

**EA phải produce/consume JSON khớp với Rust serde** — field names là snake_case (`order_id` không phải `orderId`). Xem `services/mt5-bridge/src/models/order.rs:1-64` cho schema chính xác.

---

## 17. Options Evaluated

### Option A: dingmaotu/mql-zmq

- **Source:** https://github.com/dingmaotu/mql-zmq
- **License:** Apache-2.0 (MQL binding code); libzmq precompiled DLL phân phối riêng
- **Stars / activity:** ~500 stars, last commit 2017 (stale nhưng stable)
- **Fit:** Precompiled libzmq 4.2.x Win64 DLL sẵn sàng. Apache-2.0 cho `.mqh` files. Cộng đồng đã dùng nhiều năm.
- **Pros:** Zero dependency thêm. Precompiled DLL có sẵn (không cần tự build). String conversion pattern đã có. ZMQ_DONTWAIT pattern documented.
- **Cons:** Last update 2017. Không có CURVE auth built-in. ZeroMQ version cũ (4.2.x thay vì 4.3.x hiện tại).
- **Integration cost:** Low — copy `.mqh` files, copy DLLs, `#include`.

### Option B: ding9736/MQL5-ZeroMQ

- **Source:** https://github.com/ding9736/MQL5-ZeroMQ
- **License:** MIT
- **Stars / activity:** ~10 stars, 2 commits, rất mới
- **Fit:** MIT. Có CURVE/ZAP auth built-in. Latency benchmark tốt.
- **Pros:** Mới hơn, MIT, ZAP auth.
- **Cons:** Chưa battle-tested. Quá ít stars. Không có community support. 2 commits = risk.
- **Integration cost:** Medium (vì phải verify kỹ trước khi dùng)

**Recommendation:** Dùng Option A (dingmaotu/mql-zmq) cho ZMQ core. Nếu cần CURVE auth (Epic 14.20), có thể port CURVE handshake từ Option B hoặc implement trực tiếp.

### Option C: vivazzi/JAson (cho JSON)

- **Source:** https://github.com/vivazzi/JAson
- **License:** MIT
- **Stars / activity:** ~100 stars, active forks
- **Fit:** Pure MQL5, MIT, no DLL, tested community. Simple API.
- **Pros:** MIT, no DLL, simple `CJAVal` API, well-tested.
- **Cons:** Không có JSONPath hoặc schema validation.
- **Integration cost:** Low — 1 header file.

---

## 18. Open Questions cho Operator

1. **HMAC field ordering:** Python engine ký HMAC trên concatenation của fields theo thứ tự nào? Cần exact spec để EA verify match. Xem `services/trading-engine/src/` — chưa tìm thấy HMAC signing code (có thể chưa implement ở engine side).

2. **DLL version:** Dùng libzmq 4.2.0 (VC2015) hay 4.2.2 (VC2010) từ dingmaotu/mql-zmq? VC2010 build được claim là WINE-compatible tốt hơn nếu team test trên Linux.

3. **ZMQ socket topology:** Bridge Rust zmq_server.rs hiện dùng socket pattern nào (REP/DEALER/ROUTER)? EA cần biết để chọn đúng loại socket (DEALER vs REQ). Xem `services/mt5-bridge/src/zmq_server.rs`.

4. **FTMO account mode:** Hedging hay Netting? FTMO MT5 challenge thường là hedging. Code đã assume hedging trong `ClosePositionByMarket`. Cần confirm trước E2E test.

5. **Linux Wine compile:** Workflow compile MQL5 trên CI (Linux) qua Wine chưa được xác nhận. Có thể cần Windows VM hoặc GitHub Actions Windows runner.

6. **libzmq.dll DLL version pin:** Sau khi chọn version, phải commit DLL binary vào repo (`services/mt5-bridge/mql5-ea/Libraries/`) hoặc dùng separate release asset. Binary trong git repo cần LFS.

7. **Bridge connection ports:** `SubPort` và `PubPort` cần document trong `configs/ftmo-presets.yaml`. Hiện chưa thấy trong config.

8. **CURVE auth key management:** Epic 14.20 plan enable CURVE auth cho non-loopback. Key generation và storage location chưa define. Liên quan `common/security.md` CURVE requirement.

9. **Replay/Strategy Tester integration:** Với ZMQ EA, Strategy Tester chỉ test logic không dùng ZMQ. Cần mock bridge hay skip ZMQ init khi `MQLInfoInteger(MQL_TESTER)` = true.

---

## 19. Sources

- [github.com/dingmaotu/mql-zmq](https://github.com/dingmaotu/mql-zmq) — Apache-2.0, ZMQ MQL5 binding, Socket.mqh pattern
- [github.com/darwinex/dwx-zeromq-connector](https://github.com/darwinex/dwx-zeromq-connector) — BSD-3-Clause, archived, MT4-only
- [github.com/vivazzi/JAson](https://github.com/vivazzi/JAson) — MIT, pure MQL5 JSON library
- [github.com/ding9736/MQL5-ZeroMQ](https://github.com/ding9736/MQL5-ZeroMQ) — MIT, newer ZMQ binding
- [mql5.com/en/docs/constants/tradingconstants/enum_trade_request_actions](https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_request_actions) — Trade action types
- [mql5.com/en/docs/constants/structures/mqltraderequest](https://www.mql5.com/en/docs/constants/structures/mqltraderequest) — MqlTradeRequest struct
- [mql5.com/en/docs/constants/structures/mqltraderesult](https://www.mql5.com/en/docs/constants/structures/mqltraderesult) — MqlTradeResult struct
- [mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes](https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes) — Full retcode table
- [mql5.com/en/docs/trading/ordersend](https://www.mql5.com/en/docs/trading/ordersend) — OrderSend function reference
- [mql5.com/en/docs/event_handlers/oninit](https://www.mql5.com/en/docs/event_handlers/oninit) — ENUM_INIT_RETCODE values
- [mql5.com/en/docs/event_handlers/ondeinit](https://www.mql5.com/en/docs/event_handlers/ondeinit) — DEINIT reason codes
- [mql5.com/en/docs/common/cryptencode](https://www.mql5.com/en/docs/common/cryptencode) — CryptEncode CRYPT_HASH_SHA256
- [mql5.com/en/articles/16357](https://www.mql5.com/en/articles/16357) — Pure MQL5 SHA-256 + HMAC-SHA256 implementation
- [mql5.com/en/book/automation/account/account_netting_hedge](https://www.mql5.com/en/book/automation/account/account_netting_hedge) — Hedging vs Netting account detection
- [mql5.com/en/book/automation/experts/experts_position_list](https://www.mql5.com/en/book/automation/experts/experts_position_list) — PositionsTotal / PositionGetTicket iteration pattern
- [github.com/dingmaotu/mql-zmq/issues/19](https://github.com/dingmaotu/mql-zmq/issues/19) — Strategy Tester + DLL limitation
- [mql5.com/en/forum/367908](https://www.mql5.com/en/forum/367908) — MetaEditor command-line compile
- `services/mt5-bridge/src/protocol.rs` — existing message types (local)
- `services/mt5-bridge/src/models/order.rs` — Order/OrderResult struct schema (local)
