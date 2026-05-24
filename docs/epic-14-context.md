# Epic 14: MT5 EA + Live Execution Path — Technical Context

**Created:** 2026-05-24 (formalized from `docs/research/epic-14-mt5-ea-outline.md`, 2026-05-06)
**Last updated:** 2026-05-24
**Status:** **Contexted** — 21 stories drafted, not started
**Epic:** 14 of 16+
**Stories:** 21 (14.1 – 14.21) across 4 phases (A MQL5 EA / B Rust bridge / C Python engine / D E2E+runbook)
**Track:** Independent of Epic 15 (RegimeActor) and Epic 16 (data) — the live-execution leg; can run in parallel.
**Source outline:** `docs/research/epic-14-mt5-ea-outline.md` (full story detail, risks, architecture diagram)
**Skill/rules:** `mql5-zmq-bridge` + `mql5-patterns` skills; `.claude/rules/mql5/*`; reviewer `mql5-reviewer`.

---

## Overview

### Problem Statement

Sandboxed shipped Epics 8–13 (strategies, rule engine, backtest harness, scale-out tactics) and the
live orchestrator (Epic 10.5: per-account Nautilus `TradingNode`, `ZmqExecutionClient`,
`RedisDataClient`). But the **live execution path does not work end-to-end** — the MetaTrader 5 leg is
missing:

- ✅ `trading-engine` (Python/Nautilus) submits orders over ZMQ.
- ✅ `mt5-bridge` (Rust) receives `Order` from ZMQ and queues for delivery.
- ❌ **MT5 EA (MQL5): not written** — there is no consumer inside MetaTrader 5 to pick up orders, execute
  them, and report results.
- ❌ `ZmqExecutionClient._modify_order` / `_cancel_order` / `_cancel_all_orders` are `NotImplementedError`
  stubs (`zmq_execution_client.py:234,239,244,249` — deferred from Epic 10).
- ❌ Reconciliation reports (`generate_*_reports`, `zmq_execution_client.py:184-222`) return `[]` with a
  phantom-flat WARNING — a warm restart cannot see real MT5 positions.

Until Epic 14 ships, Sandboxed **cannot trade live** on an FTMO MT5 account.

### Solution

Complete the live execution path in four phases:

- **Phase A (MQL5):** write the MT5 Expert Advisor — ZMQ client, heartbeat, JSON parse + dispatch, HMAC
  verify, market OrderSend (BUY/SELL + SL/TP), and periodic position/order snapshot broadcast.
- **Phase B (Rust):** extend the bridge protocol + handlers for modify / cancel / close / snapshot.
- **Phase C (Python):** implement the engine-side modify/cancel and reconciliation (replace the stubs),
  routed through `ValidatedZmqAdapter` (rule check + audit) per FTMO discipline.
- **Phase D:** E2E test on an MT5 demo account, operator deployment runbook, CURVE auth for non-loopback,
  and sprint close-out.

When Epic 14 is done: submit / modify / cancel / close work end-to-end MT5 ↔ engine, and a warm restart
reconciles against real MT5 positions without duplicate orders.

### Scope

**In scope:** MT5 EA (scaffold → market order → modify SL/TP → cancel → close → result reporting →
snapshot); bridge protocol extension (`ModifyOrder`, `CancelOrder`, `ClosePosition`,
`ModifyOrderResult`, `CancelOrderResult`, `PositionSnapshot`) + handlers; engine modify/cancel impl +
reconciliation; HMAC validation engine→EA; CURVE auth when non-loopback; operator runbook; E2E demo test.

**Out of scope (defer):** multi-account multiplexing (1 EA → many accounts); MT5 history sync (load past
broker trades); production deploy/migration plan; Epic 13 tactics integration (independent at
implementation, only coincides at deploy time).

---

## Architectural Decisions

> Full detail + sequence diagram in `docs/research/epic-14-mt5-ea-outline.md` §3–§5. Summary:

1. **MQL5 EA via vendored `dingmaotu/mql-zmq`** (Apache-2.0) + `libzmq.dll`/`libsodium.dll` (LGPLv3+SE,
   pinned by SHA-256 in the runbook) + `vivazzi/JAson` (MIT). EA lives under `services/mt5-bridge/mql5-ea/`.
2. **JSON wire contract mirrors `services/mt5-bridge/src/protocol.rs`** — `MessageType` enum, snake_case
   fields. A field-name mismatch silently breaks decoding on the Rust side.
3. **HMAC-SHA256 (RFC 2104) on every engine→EA command** (`CryptEncode` is plain SHA-256, not HMAC →
   hand-rolled). The **canonical-serialization field order must match the Python signer** — this is an
   open question (needs an ADR + a Python golden-vector test) and **blocks deploy** until resolved.
4. **FTMO audit discipline:** every modify/cancel/close routes through `ValidatedZmqAdapter` (rule check
   + `audit_writer` before mutation), per `common/sandboxed-domain.md`.
5. **CURVE auth** mandatory once the bridge ZMQ socket binds beyond `127.0.0.1` (`zmq_curve_keypair`,
   server key in config, not embedded).
6. **Crash safety:** heartbeat-timeout detection (bridge) + engine pause on N missed heartbeats +
   position-snapshot reconciliation at boot → no orphan/phantom-flat positions.
7. **Correlation ID per modify/cancel command** + EA queue serialization to avoid double-modify races.

---

## Story Breakdown

Commit convention: `Implement spec 14 story 14.x` (per `sandboxed-domain.md`).

| # | Story | Size | Phase | Deps | Status |
|---|---|---|---|---|---|
| 14.1 | MT5 EA project scaffold (MQL5 file, libzmq Win64 binding, config, build setup) | S | A MQL5 | — | backlog |
| 14.2 | EA heartbeat client (periodic publish, match bridge `Heartbeat`) | M | A | 14.1 | backlog |
| 14.3 | EA JSON message parser + dispatch (`MessageType` discriminator; `Error` on malformed) | S | A | 14.2 | backlog |
| 14.4 | EA HMAC signature verify (RFC 2104; reject unsigned; matches Python golden vector) | M | A | 14.3 | backlog |
| 14.5 | EA OrderSend market BUY/SELL (`TRADE_ACTION_DEAL` + SL/TP; publish `OrderResult`) | M | A | 14.4 | backlog |
| 14.6 | EA position/order snapshot broadcast (periodic `PositionSnapshot`) | M | A | 14.5 | backlog |
| 14.7 | Bridge protocol enum + structs (modify/cancel/close/results/snapshot) + proptest roundtrip | M | B Rust | — | backlog |
| 14.8 | `modify_handler.rs` (queue for EA, correlation-ID pending acks, timeout) | M | B | 14.7 | backlog |
| 14.9 | `cancel_handler.rs` + `close_handler.rs` | M | B | 14.7 | backlog |
| 14.10 | `snapshot_handler.rs` (receive `PositionSnapshot`, expose REQ/REP for engine query) | M | B | 14.7 | backlog |
| 14.11 | `zmq_server.rs` routing extension (route new types; integration tests) | S | B | 14.7-14.10 | backlog |
| 14.12 | `zmq_models.py` Pydantic models (modify/cancel/close req+result; schema = Rust serde) | S | C Python | 14.7 | backlog |
| 14.13 | `zmq_adapter.py` send/wait for modify/cancel/close (mirror `send_order_and_wait`) | M | C | 14.12 | backlog |
| 14.14 | `validated_adapter.py` rule + audit for modify/cancel/close (3 new entry points) | M | C | 14.13 | backlog |
| 14.15 | `order_translator.py` dispatch_modify/cancel/close (Nautilus cmd → bridge; emit events) | M | C | 14.14 | backlog |
| 14.16 | `zmq_execution_client.py` implement modify/cancel (replace `NotImplementedError` 234/239/244/249) | M | C | 14.15 | backlog |
| 14.17 | `zmq_execution_client.py` reconciliation reports (replace `[]` stubs via snapshot; kill phantom-flat) | M | C | 14.10, 14.16 | backlog |
| 14.18 | E2E integration test on MT5 demo (submit→fill→modify SL→close; latency/slippage) | XL | D | 14.6, 14.11, 14.17 | backlog |
| 14.19 | Operator runbook `docs/runbooks/mt5-ea-deployment.md` (install, attach, DLL, FTMO integration) | M | D | 14.18 | backlog |
| 14.20 | CURVE auth for non-loopback bind (keypairs, config, enable) | M | D | 14.11 | backlog |
| 14.21 | Sprint artifacts + retrospective; update `docs/architecture.md` with live-path detail | S | D | 14.20 | backlog |

**Total:** ~21 stories. Estimate **3–5 weeks** depending on MQL5 expertise, libzmq Win64 build path, and
MT5 demo test infrastructure (Windows + broker demo account).

---

## Risks & Open Questions

**Top risks** (full table in outline §5): MQL5 expertise gap (team is Python/Rust) → 14.1 onboarding +
reuse `dingmaotu/mql-zmq`; EA crash → orphan positions → heartbeat-timeout + snapshot reconciliation;
**phantom-flat reconciliation gap (CRITICAL, already a code TODO)** → closed by 14.17; HMAC canonical
field-order mismatch → golden-vector test + ADR; live vs backtest slippage → document in validation report.

**Open questions (must resolve before/early in the epic, outline §8):**
1. **Who owns MQL5 development** (expertise vs library port)? — drives 14.1–14.6 estimate.
2. **MT5 demo account** for test — FTMO challenge demo (rules active, complicates test) vs broker demo (ICMarkets/OANDA MT5)?
3. **ZMQ DLL distribution + libzmq LGPLv3+SE licensing** — ship with EA vs user-installs?
4. **MT5 build toolchain** — MetaEditor on Windows; can it build under Wine on Linux?
5. **Multi-account** — design for multi-account from the start, or single-account first + refactor?
6. **HMAC canonical field order** — needs an ADR + Python golden vector (`mql5-zmq-bridge` skill §6); **blocks deploy.**
7. **Socket topology** — EA inbound is `DEALER` vs `SUB`? Confirm against `mt5-bridge/zmq_server.rs`.

---

## Dependencies

| Epic | Relationship |
|---|---|
| Epics 8–13 (shipped) | Foundation — not blocking |
| Epic 15 (RegimeActor) | Independent track; both feed eventual live trading |
| Epic 16 (data) | Independent |
| Future meta-label epic | Independent |

Epic 14 can run **in parallel** with Epic 15/16 (cross-language vs Python-only). It is the prerequisite
for any real live-capital trading on FTMO MT5.

**Per-story detail, sequence diagram, success criteria:** `docs/research/epic-14-mt5-ea-outline.md`.
