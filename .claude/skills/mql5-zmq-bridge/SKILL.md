---
name: mql5-zmq-bridge
description: ZeroMQ + JSON + HMAC integration patterns for the Sandboxed MT5 EA — DLL imports, transport, message dispatch, and reconnect. Use when working on Epic 14 stories 14.1-14.6 or anything that touches libzmq from MQL5.
origin: Sandboxed
---

# MQL5 ZMQ Bridge

Integration templates for `services/mt5-bridge/mql5-ea/`. Glue layer between MetaTrader 5 (MQL5) and `services/mt5-bridge` (Rust).

## When to Activate

- Implementing Epic 14 Phase A stories (14.1 scaffold → 14.6 snapshot broadcast)
- Adding new bridge message types (mirror `services/mt5-bridge/src/protocol.rs`)
- Debugging ZMQ DLL handle issues from MQL5
- Porting reference patterns from `dingmaotu/mql-zmq` upstream
- Implementing HMAC-SHA256 verification (RFC 2104)

## Dependencies (vendored as MQL5 includes)

| Library | Source | License | Folder |
|---|---|---|---|
| `libzmq.dll` | `dingmaotu/mql-zmq` precompiled (libzmq 4.2.x VC2010 or VC2015) | LGPLv3 + Static Linking Exception | `mql5-ea/Libraries/MT5/` |
| `libsodium.dll` | bundled with libzmq for CURVE auth | ISC | `mql5-ea/Libraries/MT5/` |
| `Zmq.mqh`, `Socket.mqh`, `ZmqMsg.mqh` | `dingmaotu/mql-zmq` | Apache-2.0 | `mql5-ea/Include/Zmq/` |
| `JAson.mqh` | `vivazzi/JAson` | MIT | `mql5-ea/Include/Json/` |
| `HmacSha256.mqh` | port from `mql5.com/en/articles/16357` | (article — confirm before commit) | `mql5-ea/Include/Sandboxed/` |

**Pin DLL versions in `docs/runbooks/mt5-ea-deployment.md`** with SHA-256 of binary. License notice for libzmq must accompany distribution per LGPLv3.

## Bridge Contract Reference

The EA's JSON wire format MUST match the Rust serde structs at:
- `services/mt5-bridge/src/protocol.rs` — `MessageType` enum (Tick, Order, OrderResult, Heartbeat, Ack, Error, plus Epic 14 additions: ModifyOrder, CancelOrder, ClosePosition, ModifyOrderResult, CancelOrderResult, PositionSnapshot)
- `services/mt5-bridge/src/models/order.rs` — `Order`, `OrderResult` schemas

Field names are **snake_case** (`order_id`, NOT `orderId`). A mismatch silently breaks decoding on the Rust side.

---

## 1. DLL Imports (`Include/Zmq/Zmq.mqh`)

```mql5
// Source: https://github.com/dingmaotu/mql-zmq/blob/master/Include/Zmq/Zmq.mqh
// License: Apache-2.0
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

    // Connect / Bind
    int zmq_bind(intptr_t s, const uchar &addr[]);
    int zmq_connect(intptr_t s, const uchar &addr[]);
    int zmq_unbind(intptr_t s, const uchar &addr[]);
    int zmq_disconnect(intptr_t s, const uchar &addr[]);

    // Send / Recv (buffer-based, simpler than zmq_msg_t)
    int zmq_send(intptr_t s, const uchar &buf[], size_t len, int flags);
    int zmq_recv(intptr_t s, uchar &buf[], size_t len, int flags);

    // Errors
    int      zmq_errno();
    intptr_t zmq_strerror(int errnum);
    void     zmq_version(int &major, int &minor, int &patch);
#import

// Socket types
#define ZMQ_PAIR    0
#define ZMQ_PUB     1
#define ZMQ_SUB     2
#define ZMQ_REQ     3
#define ZMQ_REP     4
#define ZMQ_DEALER  5
#define ZMQ_ROUTER  6
#define ZMQ_PUSH    8
#define ZMQ_PULL    9

// Send/Recv flags
#define ZMQ_DONTWAIT  1
#define ZMQ_SNDMORE   2

// Socket options
#define ZMQ_SUBSCRIBE  6
#define ZMQ_LINGER    17
#define ZMQ_RCVTIMEO  27
#define ZMQ_SNDTIMEO  28

// errno values commonly seen
#define ZMQ_EAGAIN  11
```

**Win64 calling convention**: MetaTrader 5 (64-bit) uses Microsoft x64 ABI — no stdcall vs cdecl confusion. The runtime auto-wraps. (MT4/Win32 had this issue; MT5 does not.)

---

## 2. UTF-16 → UTF-8 Conversion

MQL5 strings are UTF-16. libzmq C API expects UTF-8. Convert on EVERY boundary.

```mql5
// String → UTF-8 bytes (drops trailing null terminator)
void StringToUtf8(string text, uchar &utf8[]) {
    int len = StringToCharArray(text, utf8, 0, StringLen(text));
    if(len > 0) ArrayResize(utf8, len);    // StringToCharArray adds null terminator past StringLen
}

// UTF-8 bytes → string (with explicit length)
string Utf8ToString(const uchar &buf[], int len) {
    return CharArrayToString(buf, 0, len, CP_UTF8);
}

// Set sockopt with int value (libzmq expects little-endian int32)
void IntToBytes(int value, uchar &arr[]) {
    ArrayResize(arr, 4);
    arr[0] = (uchar)(value & 0xFF);
    arr[1] = (uchar)((value >> 8)  & 0xFF);
    arr[2] = (uchar)((value >> 16) & 0xFF);
    arr[3] = (uchar)((value >> 24) & 0xFF);
}
```

---

## 3. ZmqClient Wrapper (`Include/Sandboxed/ZmqClient.mqh`)

```mql5
#include <Zmq/Zmq.mqh>

class ZmqClient {
private:
    intptr_t m_ctx;
    intptr_t m_subSock;     // inbound commands from bridge
    intptr_t m_pubSock;     // outbound results / snapshots / heartbeat
    bool     m_connected;

    bool SetSockOpt(intptr_t sock, int opt, int value) {
        uchar buf[];
        IntToBytes(value, buf);
        return (zmq_setsockopt(sock, opt, buf, 4) == 0);
    }

    bool ConnectSocket(intptr_t sock, string address) {
        uchar addr[];
        StringToUtf8(address, addr);
        // libzmq expects null-terminated C string
        ArrayResize(addr, ArraySize(addr) + 1);
        addr[ArraySize(addr) - 1] = 0;
        return (zmq_connect(sock, addr) == 0);
    }

public:
    ZmqClient() : m_ctx(0), m_subSock(0), m_pubSock(0), m_connected(false) {}

    bool Init(string host, int sub_port, int pub_port) {
        m_ctx = zmq_ctx_new();
        if(m_ctx == 0) { Print("ERROR: zmq_ctx_new failed"); return false; }

        // SUB (or DEALER) — receive commands
        m_subSock = zmq_socket(m_ctx, ZMQ_DEALER);
        if(m_subSock == 0) { Print("ERROR: zmq_socket sub failed"); return false; }
        SetSockOpt(m_subSock, ZMQ_LINGER, 0);
        SetSockOpt(m_subSock, ZMQ_RCVTIMEO, 0);
        if(!ConnectSocket(m_subSock, StringFormat("tcp://%s:%d", host, sub_port))) {
            Print("ERROR: connect sub failed err=", zmq_errno()); return false;
        }

        // PUSH — send results / snapshots
        m_pubSock = zmq_socket(m_ctx, ZMQ_PUSH);
        if(m_pubSock == 0) { Print("ERROR: zmq_socket pub failed"); return false; }
        SetSockOpt(m_pubSock, ZMQ_LINGER, 0);
        SetSockOpt(m_pubSock, ZMQ_SNDTIMEO, 100);   // ms
        if(!ConnectSocket(m_pubSock, StringFormat("tcp://%s:%d", host, pub_port))) {
            Print("ERROR: connect pub failed err=", zmq_errno()); return false;
        }

        m_connected = true;
        return true;
    }

    void Deinit() {
        if(m_subSock != 0) { zmq_close(m_subSock); m_subSock = 0; }
        if(m_pubSock != 0) { zmq_close(m_pubSock); m_pubSock = 0; }
        if(m_ctx     != 0) { zmq_ctx_destroy(m_ctx); m_ctx     = 0; }
        m_connected = false;
    }

    int Send(const string &msg) {
        if(!m_connected) return -1;
        uchar buf[];
        StringToUtf8(msg, buf);
        return zmq_send(m_pubSock, buf, ArraySize(buf), 0);
    }

    bool Recv(string &out, int flags) {
        if(!m_connected) return false;
        uchar buf[65536];
        int rc = zmq_recv(m_subSock, buf, 65536, flags);
        if(rc < 0) return false;       // EAGAIN or error — caller treats as no-message
        if(rc > 65536) rc = 65536;     // truncated
        out = CharArrayToString(buf, 0, rc, CP_UTF8);
        return true;
    }

    bool IsConnected() const { return m_connected; }
};
```

**Socket topology** (open question §18 Q3 in research): the Rust bridge `zmq_server.rs` topology determines whether the EA uses `DEALER` (this template) or `SUB` for inbound. Confirm with bridge dev before committing.

---

## 4. Reconnect Pattern

```mql5
class BridgeHealth {
private:
    int      m_missedHeartbeats;
    datetime m_lastBridgeAck;
public:
    void NoteAck()         { m_lastBridgeAck = TimeCurrent(); m_missedHeartbeats = 0; }
    void Tick(ZmqClient &zmq, string host, int sub_port, int pub_port) {
        if(TimeCurrent() - m_lastBridgeAck <= HEARTBEAT_TIMEOUT_S) return;
        if(++m_missedHeartbeats < MAX_MISSED_HEARTBEATS) return;

        Print("WARN: Bridge timeout — reconnecting");
        zmq.Deinit();
        Sleep(ZMQ_RECONNECT_DELAY_MS);
        if(zmq.Init(host, sub_port, pub_port)) m_missedHeartbeats = 0;
    }
};
```

---

## 5. JSON Serialize / Deserialize (JAson)

```mql5
#include <Json/JAson.mqh>

// Inbound — parse + dispatch
class MessageParser {
public:
    bool Process(const string &raw, TradeExecutor &exec) {
        CJAVal msg;
        if(!msg.Deserialize(raw)) {
            PrintFormat("ERROR: Malformed JSON: %s", raw);
            return false;
        }

        // HMAC verify FIRST — see section 6
        string sig   = msg["hmac"].ToStr();
        string canon = CanonicalSerialize(msg);
        if(!VerifyHmac(canon, sig, InpHmacKey)) {
            PrintFormat("ERROR: HMAC mismatch order_id=%s", msg["order_id"].ToStr());
            EmitErrorResponse(msg["order_id"].ToStr(), "hmac_mismatch");
            return false;
        }

        string t = msg["type"].ToStr();
        if(t == "order")           return exec.HandleOrder(msg);
        if(t == "modify_order")    return exec.HandleModify(msg);
        if(t == "cancel_order")    return exec.HandleCancel(msg);
        if(t == "close_position")  return exec.HandleClose(msg);
        PrintFormat("WARN: Unknown message type=%s", t);
        return false;
    }
};

// Outbound — build OrderResult
string BuildOrderResult(string order_id, string status, double fill_price,
                        double slippage, uint retcode, string error) {
    CJAVal out;
    out["type"]       = "order_result";
    out["order_id"]   = order_id;
    out["status"]     = status;
    out["fill_price"] = fill_price;
    out["slippage"]   = slippage;
    out["retcode"]    = (int)retcode;
    out["error"]      = error;
    out["timestamp"]  = TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS);
    return out.Serialize();
}
```

---

## 6. HMAC-SHA256 (RFC 2104) — Pure MQL5

`CryptEncode(CRYPT_HASH_SHA256, ...)` is plain SHA-256, **NOT** HMAC. Implement HMAC manually.

```mql5
// File: Include/Sandboxed/HmacSha256.mqh
// HMAC-SHA256 per RFC 2104
// Reference: https://www.mql5.com/en/articles/16357

#define HMAC_BLOCK_SIZE  64        // SHA-256 block size in bytes
#define HMAC_HASH_SIZE   32        // SHA-256 output size

void Sha256(const uchar &data[], uchar &out[]) {
    uchar empty[];
    CryptEncode(CRYPT_HASH_SHA256, data, empty, out);
}

// HMAC-SHA256(key, message) → 32-byte digest
void HmacSha256Bytes(const uchar &key[], const uchar &message[], uchar &out[]) {
    uchar k[];
    if(ArraySize(key) > HMAC_BLOCK_SIZE) {
        Sha256(key, k);                          // key' = SHA256(key)
    } else {
        ArrayCopy(k, key);
    }
    ArrayResize(k, HMAC_BLOCK_SIZE);             // pad with zeros to BLOCK_SIZE
    for(int i = ArraySize(key); i < HMAC_BLOCK_SIZE; i++) k[i] = 0;

    uchar ipad[], opad[];
    ArrayResize(ipad, HMAC_BLOCK_SIZE);
    ArrayResize(opad, HMAC_BLOCK_SIZE);
    for(int i = 0; i < HMAC_BLOCK_SIZE; i++) {
        ipad[i] = (uchar)(k[i] ^ 0x36);
        opad[i] = (uchar)(k[i] ^ 0x5C);
    }

    // inner = SHA256(ipad || message)
    uchar inner_input[], inner_hash[];
    ArrayResize(inner_input, HMAC_BLOCK_SIZE + ArraySize(message));
    ArrayCopy(inner_input, ipad, 0, 0, HMAC_BLOCK_SIZE);
    ArrayCopy(inner_input, message, HMAC_BLOCK_SIZE, 0, ArraySize(message));
    Sha256(inner_input, inner_hash);

    // outer = SHA256(opad || inner)
    uchar outer_input[];
    ArrayResize(outer_input, HMAC_BLOCK_SIZE + HMAC_HASH_SIZE);
    ArrayCopy(outer_input, opad, 0, 0, HMAC_BLOCK_SIZE);
    ArrayCopy(outer_input, inner_hash, HMAC_BLOCK_SIZE, 0, HMAC_HASH_SIZE);
    Sha256(outer_input, out);
}

string BytesToHex(const uchar &buf[]) {
    string hex = "";
    for(int i = 0; i < ArraySize(buf); i++)
        hex += StringFormat("%02x", buf[i]);
    return hex;
}

bool VerifyHmac(string canonical_message, string expected_hex, string shared_key) {
    uchar key_bytes[], msg_bytes[], computed[];
    StringToCharArray(shared_key, key_bytes, 0, StringLen(shared_key));
    StringToCharArray(canonical_message, msg_bytes, 0, StringLen(canonical_message));
    ArrayResize(key_bytes, StringLen(shared_key));
    ArrayResize(msg_bytes, StringLen(canonical_message));

    HmacSha256Bytes(key_bytes, msg_bytes, computed);
    string computed_hex = BytesToHex(computed);

    // Both sides are full-length hex digests (64 chars) — direct string compare is OK
    return (computed_hex == expected_hex);
}
```

### Canonical Serialize (CRITICAL — must match Python signer)

The Python engine in `services/trading-engine/` produces the canonical string the EA must reproduce. **Field ordering is open question §18 Q1** — until ADR-NN is committed, treat this as TODO and block deploy.

```mql5
// Placeholder — replace with ADR-confirmed field order
string CanonicalSerialize(CJAVal &msg) {
    // Example (subject to ADR): concat by sorted key, exclude "hmac"
    return StringFormat("type=%s|order_id=%s|account_id=%s|action=%s|symbol=%s|volume=%.2f|price=%.5f|timestamp=%s",
        msg["type"].ToStr(),
        msg["order_id"].ToStr(),
        msg["account_id"].ToStr(),
        msg["action"].ToStr(),
        msg["symbol"].ToStr(),
        msg["volume"].ToDbl(),
        msg["price"].ToDbl(),
        msg["timestamp"].ToStr());
}
```

Ship a Python golden vector test in `services/mt5-bridge/test-fixtures/hmac_vectors.json` and an MQL5 unit script that asserts byte-for-byte match.

---

## 7. Heartbeat / Snapshot Cadence

```mql5
class PositionReporter {
private:
    datetime m_lastHeartbeat;
    datetime m_lastSnapshot;

public:
    void SendHeartbeatIfDue(ZmqClient &zmq) {
        if(TimeCurrent() - m_lastHeartbeat < HEARTBEAT_INTERVAL_S) return;
        CJAVal hb;
        hb["type"]       = "heartbeat";
        hb["account_id"] = InpAccountId;
        hb["timestamp"]  = TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS);
        zmq.Send(hb.Serialize());
        m_lastHeartbeat = TimeCurrent();
    }

    void SendSnapshotIfDue(ZmqClient &zmq) {
        if(TimeCurrent() - m_lastSnapshot < SNAPSHOT_INTERVAL_S) return;

        CJAVal snap;
        snap["type"]       = "position_snapshot";
        snap["account_id"] = InpAccountId;
        snap["timestamp"]  = TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS);

        int total = PositionsTotal();
        for(int i = 0; i < total; i++) {
            ulong t = PositionGetTicket(i);
            if(t == 0) continue;
            if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;

            CJAVal pos;
            pos["ticket"]     = (long)t;
            pos["symbol"]     = PositionGetString(POSITION_SYMBOL);
            pos["type"]       = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            pos["volume"]     = PositionGetDouble(POSITION_VOLUME);
            pos["open_price"] = PositionGetDouble(POSITION_PRICE_OPEN);
            pos["sl"]         = PositionGetDouble(POSITION_SL);
            pos["tp"]         = PositionGetDouble(POSITION_TP);
            pos["profit"]     = PositionGetDouble(POSITION_PROFIT);
            pos["comment"]    = PositionGetString(POSITION_COMMENT);
            snap["positions"].Add(pos);
        }
        zmq.Send(snap.Serialize());
        m_lastSnapshot = TimeCurrent();
    }
};
```

---

## 8. Story Mapping (Epic 14 Phase A)

| Story | Skill section to use |
|---|---|
| 14.1 EA scaffold | §1 DLL imports, §2 UTF-8 helpers, §3 ZmqClient skeleton |
| 14.2 Heartbeat | §3 ZmqClient, §7 PositionReporter (heartbeat half) |
| 14.3 JSON parser + dispatch | §5 JAson + dispatch |
| 14.4 HMAC verify | §6 — full HMAC-SHA256 implementation |
| 14.5 OrderSend market | (uses `mql5-patterns` §3.1) + §5 outbound serialize |
| 14.6 Position snapshot | §7 PositionReporter (snapshot half) |

For ModifyOrder/CancelOrder/ClosePosition (Phase B/C engine work), the EA-side handlers re-use `mql5-patterns` §3.2/3.3/3.4 templates, parsed via §5 dispatch.

---

## 9. Common Errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `zmq_ctx_new()` returns 0 | DLL not loaded | Verify `libzmq.dll` in `MQL5/Libraries/MT5/`, "Allow DLL imports" enabled |
| All sends fail with errno=11 | EAGAIN — peer not connected | Bridge not running OR wrong port; check tcp://host:port |
| Garbled string on bridge side | UTF-16 not converted | Use `StringToUtf8` helper |
| EA freezes terminal | Blocking recv | Use `ZMQ_DONTWAIT` in every `Recv` call |
| `OnDeinit` leaves zombie connections | Wrong cleanup order | Sockets first, then context: `zmq_close → zmq_ctx_destroy` |
| HMAC always mismatches | Field order / encoding mismatch | Implement Python golden-vector test, fix `CanonicalSerialize` |

---

## 10. References

- `dingmaotu/mql-zmq` (Apache-2.0): https://github.com/dingmaotu/mql-zmq
- `vivazzi/JAson` (MIT): https://github.com/vivazzi/JAson
- HMAC-SHA256 in MQL5: https://www.mql5.com/en/articles/16357
- libzmq LGPL-SE clarification: https://github.com/zeromq/libzmq/blob/master/COPYING.LESSER
- Bridge contract: `services/mt5-bridge/src/protocol.rs`, `services/mt5-bridge/src/models/order.rs`
- Sandboxed research: `docs/research/mql5-ea-patterns.md` §5 (ZMQ), §10 (JSON), §11 (HMAC), §18 (open questions)
