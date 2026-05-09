---
paths:
  - "**/*.mq5"
  - "**/*.mqh"
---
# MQL5 Testing

> This file extends [common/testing.md](../common/testing.md) with MQL5-specific content.

## Strategy Tester limitations (read first)

The MT5 Strategy Tester has hard limits that shape how a ZMQ-dependent EA must be tested:

- **DLL imports are BLOCKED on remote optimization agents.** Only local single-agent runs allow DLL — and the DLL files must be present in `[MT5_data]/tester/MQL5/Libraries/` (separate from the live `MQL5/Libraries/`).
- **Networking from the tester is unreliable.** Even with DLL enabled, ZMQ connections inside Strategy Tester are flaky; the bridge cannot drive ticks back into the tester.
- **Time virtualization** breaks heartbeat / timeout logic — the tester accelerates time, so a 5s heartbeat in real-world code expires every tick.

Conclusion: **the ZMQ EA cannot be fully exercised via Strategy Tester.** Use a 3-tier approach.

## 3-tier Test Plan

### Tier 1 — Unit logic, no ZMQ (MQL5 scripts)

Pure-function tests run as `.mq5` script files (not EAs) on a chart. Outputs go to `Print` / Journal.

What to cover:
- Volume normalization across edge cases (below `VOLUME_MIN`, above `VOLUME_MAX`, between steps).
- SL/TP validation with synthetic `STOPS_LEVEL` / `FREEZE_LEVEL`.
- HMAC verify with known test vectors from `services/trading-engine/` (golden vectors must match).
- JSON parse with malformed inputs (truncated, wrong types, missing required fields).
- Magic-number derivation determinism per `account_id`.

```mql5
// File: mql5-ea/Scripts/Tests/test_normalize_volume.mq5
#property script_show_inputs

void OnStart() {
    Assert("step=0.01 floor", NormalizeVolume("EURUSD", 0.123) == 0.12);
    Assert("below min clamps", NormalizeVolume("EURUSD", 0.001) == SymbolInfoDouble("EURUSD", SYMBOL_VOLUME_MIN));
    PrintFormat("PASSED: volume normalization");
}

void Assert(string name, bool ok) {
    if(!ok) { PrintFormat("FAIL: %s", name); ExpertRemove(); }
}
```

Coverage target: 80% of pure logic per `common/testing.md`.

### Tier 2 — Integration with local bridge (DLL enabled)

Setup:
1. Start `services/mt5-bridge` locally (Rust) on a known port.
2. Enable "Allow DLL imports" in MT5 → Tools → Options → Expert Advisors.
3. Copy `libzmq.dll` and `libsodium.dll` into BOTH `[MT5_data]/MQL5/Libraries/` AND `[MT5_data]/tester/MQL5/Libraries/`.
4. Attach EA to a demo chart, configure `InpBridgeHost=127.0.0.1`, ports matching local bridge.

What to cover:
- ZMQ handshake completes within 5s.
- Heartbeat round-trip latency P50/P95.
- Submit a mock `Order` JSON via bridge → expect `OrderResult` with `TRADE_RETCODE_DONE` on a demo account.
- HMAC mismatch causes the EA to emit `Error` response (visible in bridge log).
- `OnDeinit` cleans up: socket closed, no zombie context (verify via `lsof`/`netstat` on bridge side).

### Tier 3 — End-to-end on demo broker account

Setup: real MT5 demo (FTMO challenge demo or ICMarkets demo), full Sandboxed stack including Python engine.

What to cover:
- Full lifecycle: `submit → fill → modify SL → close`. Latency P50/P95.
- Warm restart: kill EA mid-position, restart, verify `PositionSnapshot` reconciles correctly with engine.
- Slippage + spread comparison vs backtest baseline (Epic 12 dataset fingerprint).
- `CanTrade()` guards: disable AutoTrading button mid-session and verify EA rejects new commands.
- Magic-number isolation: run two EA instances on the same chart with different `InpAccountId` and confirm position attribution.

This tier is operator-driven and gated by the runbook in story 14.19.

## Mock bridge (recommended for Tier 1.5)

A tiny Python ZMQ stub that speaks the bridge protocol can be used to drive the EA without a full Rust bridge running. Keep one in `services/mt5-bridge/test-fixtures/mock_bridge.py`. Use it for:
- Replay-style: replay recorded JSON commands into the EA.
- Fault injection: malformed JSON, HMAC mismatch, dropped heartbeat.

## Expert log conventions (assertion target)

Tier 2 / Tier 3 tests assert against the MT5 Experts log:

```
Windows: %APPDATA%\MetaQuotes\Terminal\<hash>\MQL5\Logs\YYYYMMDD.log
or:      [MT5 data folder]\Logs\YYYYMMDD.log
```

Format: `YYYY.MM.DD HH:MM:SS.mmm  EA_name (Symbol,TF)  Message`

Use `PrintFormat()` with structured prefixes (`INFO:`, `WARN:`, `ERROR:`) so test scripts can grep deterministically.

## What CANNOT be tested in MQL5

- True race conditions (single-threaded event loop).
- Cross-EA coordination (each EA is isolated; multi-account semantics belong in Python engine).
- DLL hot-reload (must restart MT5).

For each of these, the canonical test lives upstream in Python (engine) or Rust (bridge).

## Coverage tooling

MQL5 has no native coverage tool. Track manually:
- Maintain a `tests/coverage.md` checklist mapping test file → covered helpers.
- Sprint review: coverage > 80% of public helpers in `Include/Sandboxed/*.mqh`.

## Reference

- `docs/research/mql5-ea-patterns.md` §14 — Strategy Tester / DLL constraints with citations.
- `services/mt5-bridge/test-fixtures/` — mock bridge location once created.
- `common/testing.md` — TDD baseline.
