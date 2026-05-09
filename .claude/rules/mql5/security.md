---
paths:
  - "**/*.mq5"
  - "**/*.mqh"
---
# MQL5 Security

> This file extends [common/security.md](../common/security.md) with MQL5-specific content.

## Threat Model (Sandboxed Epic 14)

The MT5 EA sits on Windows next to MetaTrader 5, holds broker credentials in terminal config, and accepts commands over ZMQ from `services/mt5-bridge`. Attackers we model:

1. **Compromised host on the bridge network** — can spoof commands toward EA. Mitigation: HMAC-SHA256 on every command.
2. **Malicious DLL injection** — replaces `libzmq.dll`. Mitigation: pin DLL version + checksum in runbook; `Libraries/` directory only.
3. **Strategy Tester misuse** — operator runs ZMQ EA in tester pointed at production bridge. Mitigation: hard skip ZMQ init under `MQLInfoInteger(MQL_TESTER)`.
4. **Log leak of secrets** — HMAC key or broker password in journal. Mitigation: never log inputs whose name starts with `InpHmac*`, `InpPassword`, `InpKey`.

## Secret Management

- HMAC shared key, account ID, magic seed: `input` parameters only — never literals.
- Document every secret-bearing input in `Config.mqh` with a comment "loaded by operator at attach time".
- The terminal stores attached-EA inputs in `.tpl` template files — those are NOT secret stores. Treat template files as PII.
- Never commit `.tpl` or `.set` files containing real keys. Provide `.example` variants only.

## HMAC Verification (mandatory on every inbound command)

Every command from the bridge MUST be HMAC-SHA256 verified before dispatch.

```mql5
// Pseudocode — see skill: mql5-zmq-bridge for full implementation
bool ProcessMessage(const string &raw_json) {
    CJAVal msg;
    if(!msg.Deserialize(raw_json))           return Reject("malformed JSON");

    string sig      = msg["hmac"].ToStr();
    string canon    = CanonicalSerialize(msg);    // exact field order, see ADR
    if(!VerifyHmac(canon, sig, InpHmacKey))  return Reject("hmac mismatch");

    return Dispatch(msg);
}
```

- **`CryptEncode(CRYPT_HASH_SHA256, ...)` is plain SHA-256, NOT HMAC.** Use the RFC 2104 port — see `skill: mql5-zmq-bridge` §HMAC.
- HMAC field-ordering must match the Python signer in `services/trading-engine/`. Open question (research §18 Q1): until ADR is committed, do NOT pick an arbitrary order — flag the code as TODO and block deploy.
- Reject = log + send `Error` response with `order_id` correlation, do NOT silently drop.

## Strategy Tester Guard

```mql5
int OnInit() {
    if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION)) {
        Print("INFO: Strategy Tester detected — skipping ZMQ init");
        return INIT_SUCCEEDED;
    }
    // real ZMQ wiring
    ...
}
```

DLL calls are blocked on remote test agents anyway, but skipping init prevents accidental real-bridge connection from a local tester run. See `.claude/rules/mql5/testing.md` for the 3-tier test approach.

## DLL Imports

- Whitelist: `libzmq.dll`, `libsodium.dll` only. Any other `#import` requires a security review.
- Pin upstream source: `dingmaotu/mql-zmq` Apache-2.0 release vXX, libzmq 4.2.x. Document SHA-256 of binary in `docs/runbooks/mt5-ea-deployment.md`.
- License: libzmq is LGPLv3 + Static Linking Exception → safe for closed-source EA via dynamic link. NEVER statically link libzmq into the EA binary (no benefit; would also strip the SLE protection).
- `libsodium` is ISC — no licensing constraint.

## ZMQ Socket Hardening

- `ZMQ_LINGER = 0` on every socket: pending messages must NOT survive close (a queued command containing position data is sensitive).
- `ZMQ_RCVTIMEO`: low (≤ 100 ms) so polls do not stall.
- CURVE auth (per `common/security.md`): mandatory once the bridge socket binds beyond `127.0.0.1`. Generate keypair via `zmq_curve_keypair`, persist server key in `input` (not embedded). Story 14.20 in Epic 14 plan.
- Never bind to `0.0.0.0` from the EA — the EA is a client, always `connect()`.

## Input Validation (every JSON field)

Every field parsed from the bridge command must be validated:

```mql5
double volume = msg["volume"].ToDbl();
if(volume <= 0 || volume > 1000.0) return Reject("volume out of range");

string symbol = msg["symbol"].ToStr();
if(StringLen(symbol) == 0 || StringLen(symbol) > 32) return Reject("symbol invalid");
if(!SymbolSelect(symbol, true)) return Reject("symbol not in MarketWatch");

string action = msg["action"].ToStr();
if(action != "BUY" && action != "SELL") return Reject("unknown action");
```

- Reject on type mismatch (`ToDbl()` of a non-number returns 0 — verify with `IsNumeric()` checks).
- Reject on out-of-range volumes.
- Reject on unknown action / order types.
- Reject on `order_id` collision (already-seen ID).

## Logging Discipline

- Never log: HMAC key, broker password, full account number (mask: `acc-XXXXX1234`).
- Always log: `order_id` (correlation), retcode, `GetLastError()`, ZMQ errno.
- Log target: MT5 Journal tab + Experts log (file-based, persisted). Operator can grep.
- Print errors with `PrintFormat("ERROR: ctx=%s err=%d retcode=%d", ctx, err, retcode)` so log parsers can extract.

## Network Boundary (per common/sandboxed-domain.md)

- EA sits inside the localhost trust boundary of the broker terminal. The bridge is the gateway.
- The EA MUST NOT reach out to anything except the configured bridge endpoint. No HTTP, no other ZMQ peers, no file I/O outside `MQL5/Files/`.
- Reconciliation snapshots leak position data — only emit on the configured PUB endpoint, never broadcast.

## Reference

- `docs/research/mql5-ea-patterns.md` §11 (HMAC), §18 (open questions on key/field order).
- `common/security.md` — FTMO baseline (CURVE auth, secret discipline).
- `.claude/skills/mql5-zmq-bridge/SKILL.md` — HMAC implementation template.
