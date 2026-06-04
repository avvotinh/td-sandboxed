# Story 15.4 — Actor-before-Strategy `on_bar` Ordering Spike (risk R1)

**Date:** 2026-05-24
**Epic:** 15 (Regime Backtest-Live Parity)
**Branch:** `feat/regime-actor-backtest-parity`
**Status:** ✅ Resolved — **same-bar contract adopted**
**Gates:** Story 15.7 (`BaseStrategy._regime_admits` entry-only gate)
**Test:** `tests/integration/regime/test_actor_strategy_ordering.py` (3 tests, real `BacktestEngine`)

---

## Question

The RegimeActor design (`docs/design/regime-actor-design.md` §3.4, risk R1) needs the
`RegimeActor` to publish the confirmed regime into the shared `RegimeStateStore`
**before** the strategy reads it for the **same** bar. Otherwise the strategy gates on a
stale regime.

> Does NautilusTrader dispatch `Actor.on_bar` ahead of `Strategy.on_bar` for the same
> `BarType` within the same bar?

Design §3.4 flagged this as relying on add-order + subscription order and required it be
*proven by a focused integration test*, not assumed. The two possible contracts:

- **Same-bar** — actor always runs first → strategy reads the *current* bar's regime.
- **One-bar-lag fallback** — if not guaranteed, the strategy reads the regime confirmed as
  of the *previous* bar. Acceptable because the hysteresis filter already imposes multi-bar
  confirmation latency, but it changes the 15.7 read semantics.

## Method

A focused integration test runs the **real** `BacktestEngine` (no mocks) with:

- a minimal probe `Actor` subscribed to one `BarType`, and
- a minimal probe `Strategy` subscribed to the same `BarType`,

both appending `(role, bar.ts_init)` to a shared dispatch log on every `on_bar`. The test
runs twice — once attaching the actor first (`add_actor` → `add_strategy`, the order story
15.8 uses) and once attaching the strategy first — to determine whether the dispatch order
depends on registration order.

- Instrument/bars: `TestInstrumentProvider.default_fx_ccy("EUR/USD")`, 50 synthetic
  trending 1-min bars via `src.backtesting.synthetic_bars.generate_bars`.
- Harness: `BacktestRunner` (the production façade), so the result reflects the real
  composition path, not a hand-rolled engine.

## Result

**Actor `on_bar` precedes Strategy `on_bar` for every bar — and does so regardless of
add-order.** The dispatch log interleaved strictly as
`actor@t0, strategy@t0, actor@t1, strategy@t1, …` for all 50 bars in **both** attach
orders. Adding the strategy *before* the actor did **not** flip the order.

```
attach_actor_first=True : first6=[actor, strategy, actor, strategy, actor, strategy]  → ACTOR FIRST
attach_actor_first=False: first6=[actor, strategy, actor, strategy, actor, strategy]  → ACTOR FIRST
```

Environment: `nautilus_trader 1.221.0`, Python 3.13.7, Windows 11. The guarantee is
structural — Nautilus routes data to actors before strategies for the same bar — so it does
**not** depend on the order in which we register components.

This is a **stronger** guarantee than design §3.4 assumed (it expected the order to depend
on add-order/subscription order).

## Decision (gates 15.7)

1. **Adopt the same-bar contract.** `BaseStrategy._regime_admits` in story 15.7 reads the
   `RegimeStateStore` snapshot published by the actor **on the current bar**. No one-bar-lag
   handling, no warmup off-by-one accounting beyond what the hysteresis filter already does.
2. **Keep `add_actor` before `add_strategy` in 15.8 / 15.10 anyway.** It is correct, matches
   the design's stated add-order (regime → strategy → compliance), and is the most defensive
   composition even though the spike shows correctness does not depend on it. Codifying the
   order keeps intent legible and protects against a future Nautilus change.
3. **Retain the one-bar-lag fallback in the design as the documented contingency.** If a
   future Nautilus upgrade flips the dispatch order, the parametrized ordering tests fail
   loudly and the fallback is re-evaluated before shipping. The tests are the tripwire.

## Regression guard

`test_actor_strategy_ordering.py` ships with the epic and runs in CI:

- `test_actor_on_bar_precedes_strategy_same_bar` — strict-interleave assertion in the
  add-actor-first configuration (the 15.8 production order).
- `test_actor_precedes_strategy_regardless_of_add_order[True|False]` — per-timestamp
  actor-before-strategy assertion in **both** add-orders (locks in the stronger guarantee).

A Nautilus version that makes dispatch order add-order-sensitive or strategy-first will fail
these tests, which is the signal to revisit the same-bar decision.

## Follow-ups / notes

- The probe classes store their shared log under `self._dispatch_log`, **not** `self._log`:
  `_log` collides with the Cython `Component` logger cdef attribute (read-only) and raises
  `AttributeError` on assignment. Worth remembering for 15.5 `RegimeActor` constructor state.
- Spike confirms the meta-labeling prerequisite indirectly: an actor's `on_bar` runs natively
  inside the backtest engine ahead of the strategy, so computing `RegimeFeatures` there has no
  lookahead and the strategy can consume them same-bar.
