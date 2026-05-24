# Epic 16: Historical Data Acquisition Campaign — Technical Context

**Created:** 2026-05-24
**Last updated:** 2026-05-24
**Status:** **Contexted** — 8 stories drafted, not started
**Epic:** 16 of 16+
**Stories:** 8 (16.1 – 16.8) across 3 phases (D0 prereq / D1 fetch / D2 quality)
**Execution order:** **Prerequisite — run before Epic 15 implementation** (despite the higher
number; numbering is append-only). Serves two downstream consumers: Epic 15 backtest validation
and the future meta-labeling / signal-quality epic.
**Source pipeline:** Epic 12.7.0 (`tv-cli backtest-fetch`, `go_manifest_loader`, `DatasetPipeline`)
**Runbook:** `docs/runbooks/backtest-data-fetch.md`

---

## Overview

### Problem Statement

Before implementing Epic 15 (and the future ML epic) we need historical bar data on this machine.
Current state (2026-05-24, Windows workspace):

- The fetch pipeline is mature (Epic 12.7.0) but **no historical data exists locally** — `data/`
  is gitignored and empty; no parquet shards, no manifests. The workspace moved Linux→Windows.
- `tv-cli` is **not built** (`services/tv-api/bin/` empty); no `SESSION_ID`/`SESSION_SIGN` in env.
- Only one dataset spec exists (`configs/datasets/xauusd-validation.yaml`, XAUUSD M5+M15 2y).

Two consumers have **different** data needs:

| | Backtest (Epic 15 + validation) | ML training (meta-label, future) |
|---|---|---|
| Volume | 2y in-sample + OOS sufficient | More — XAUUSD ~200-500 trades/yr → 2y ≈ 400-1000 samples (borderline per meta-label research); needs deeper history + multiple pooled symbols |
| Symbols | 1-2 enough to validate | Multiple, pooled, to clear the sample floor |
| Properties | Spread modeled via `ftmo.yaml` OK | Point-in-time, no look-ahead (purged CV); spread-as-feature **unavailable** from TradingView (dropped, Epic 15 design R5) |

### Solution

A **script-driven fetch campaign** populating Parquet shards for **4 symbols × 4 timeframes**,
targeting **5 years** of history (accepting the per-timeframe server floor), consumed through the
existing `DatasetPipeline`. Scope (decided 2026-05-24):

- **Symbols:** XAUUSD, EURUSD, GBPUSD, **USDJPY**.
- **Timeframes:** M5, M15, H1, H4.
- **Depth:** target 5y `in_sample` + 4mo `oos_reserve`; **M5 will floor shallowest** (see Decision 2).
- **Account:** premium TradingView with ReplayMode entitlement (wider intraday window + daily-capable).

Campaign size: 4 × 4 × 2 windows ≈ **32 shards, ~400+ stepped-anchor fetch calls** (rate-limited,
1/IP, silent throttle) → **must be script-driven**, not the manual per-shard loop the current
runbook documents.

### Scope (Epic 16)

**In Scope:**

- USDJPY custom instrument builder (JPY precision/pip/fee) — code prerequisite for valid USDJPY backtests.
- Dataset specs `configs/datasets/{xauusd,eurusd,gbpusd,usdjpy}-5y.yaml` (M5/M15/H1/H4 × in_sample + oos_reserve).
- A fetch-campaign **driver script** automating the stepped-anchor walk across the symbol×tf matrix + merge + dedupe + verify.
- Build `tv-cli`, wire credentials, premium smoke, run the campaign, materialize via `DatasetPipeline`.
- Per-shard quality gate + a data-quality report (dedup, gaps, fingerprint, actual-depth-achieved).

**Out of Scope (defer):**

- Tick / order-book / spread capture (spread stays modeled via `ftmo.yaml`; ML spread-feature unavailable).
- Options, fundamental, news/sentiment data.
- Real-time streaming ingestion (that is `tv-api` live, not this campaign).
- Symbols beyond the 4 chosen; AUDUSD/USDCAD not fetched this round.
- TimescaleDB `candles` load is **optional/deferred** (16.8) — backtest consumes Parquet; only load DB if a non-backtest consumer needs it.
- ML feature/label generation — that is the meta-label epic (Epic 15's `feature_recorder` produces the regime-feature stream, not this raw campaign).

---

## Architectural Decisions

### 1. Script-driven campaign, not the manual per-shard loop
32 shards × ~30 stepped calls each = ~400+ calls. The runbook's hand-driven `while` loop per shard
is impractical at this scale. A driver (`scripts/fetch_campaign.py`) walks the symbol×tf matrix,
steps `-to` anchors backward, writes numbered chunks, then invokes merge + dedupe + verify per shard.

### 2. Target 5y, accept the per-timeframe server floor (M5 shallowest)
TradingView caps ~5500 bars/anchor and has a finite intraday history floor (runbook only validated
~2y M5). Realistic depth, finest→coarsest: **M5 ~2-3y likely (may not reach 5y)**, M15 deeper, H1/H4
reach 5y comfortably. The campaign records *actual* depth achieved per (symbol, tf); 5y is a target,
not a guarantee. Acceptance is "deepest the server returns," not "exactly 5y."

### 3. USDJPY needs a custom JPY instrument builder
`runner_facade._build_instrument` only special-cases XAUUSD + `{EURUSD,GBPUSD,AUDUSD}`. USDJPY falls
to `default_fx_ccy` → non-zero 2bps instrument fees ("eats the account") + wrong precision (JPY pairs
are `price_precision=3, pip=0.01`, not 5/0.0001). A `_build_jpy_pair_instrument` (precision=3,
pip_increment=0.001, size like FX, `maker_fee=taker_fee=0`) is required before USDJPY backtests are
valid. **Escape hatch:** swapping USDJPY → AUDUSD (builder already exists) eliminates story 16.1.

### 4. Parquet-first; TimescaleDB load optional
Backtest consumes Parquet via `DatasetPipeline`/`CachedBarLoader`; `TimescaleDataSpec` is not wired
(`runner_facade` raises `NotImplementedError`). DB load (16.8) is deferred unless a non-backtest
consumer needs it.

### 5. Premium ReplayMode
Wider per-anchor intraday window (~25d M5 vs ~18d FakeReplay) → fewer calls, and daily/weekly capable
if needed later. Requires `SESSION_ID`/`SESSION_SIGN` from a premium account (operator-supplied).

### 6. Window convention + version pinning
Each symbol spec: `in_sample` (deep, 5y target) + `oos_reserve` (most-recent ~4mo, held out).
`dataset_version` pinned; bumping it invalidates downstream comparison reports (same discipline as
`xauusd-validation.yaml`).

---

## Story Breakdown

| # | Story | Effort | Phase | Notes / AC | Status |
|---|---|---|---|---|---|
| 16.1 | USDJPY instrument builder (`_build_jpy_pair_instrument`: precision=3, pip=0.001, fee=0) + tests | S | D0 Prereq | Decision 3; no credentials needed. Escape hatch: AUDUSD instead → drop this story | backlog |
| 16.2 | Dataset specs `configs/datasets/{xauusd,eurusd,gbpusd,usdjpy}-5y.yaml` (M5/M15/H1/H4 × in_sample+oos) | S | D0 Prereq | extend `xauusd-validation.yaml`; tz-aware windows; no credentials | backlog |
| 16.3 | Fetch-campaign driver `scripts/fetch_campaign.py` (matrix walk + stepped anchors + merge + dedupe + verify) | M | D0 Prereq | Decision 1; idempotent re-run; no credentials to write/test the dry-run path | backlog |
| 16.4 | Build `tv-cli` + wire credentials + premium smoke (1 shard XAUUSD H4) confirms replay entitlement | S | D1 Fetch | needs `SESSION_ID`/`SESSION_SIGN`; surfaces zero-bars-if-not-premium early | backlog |
| 16.5 | Run campaign per symbol, coarse→fine (H4→H1→M15→M5); record actual depth/tf vs 5y target | L | D1 Fetch | Decision 2; mostly machine time (rate-limited, hours); driver-orchestrated | backlog |
| 16.6 | Merge (`go_manifest_loader`) + materialize via `DatasetPipeline`; canonical manifest per symbol | M | D1 Fetch | dedupe 5-day overlap by `(tf,ts)` before treating canonical | backlog |
| 16.7 | Quality gate + data-quality report (dedup, gaps<threshold, fingerprint match, actual depth) → sprint-artifacts | M | D2 Quality | gate consumed by Epic 15 / ML epic | backlog |
| 16.8 | (optional) TimescaleDB `candles` load for non-backtest consumers | S | D2 Quality | Decision 4 — deferred unless needed | backlog |

**Total effort:** D0 ~1.5d (builder + specs + driver), D1 ~1d operator + significant fetch wall-clock
(rate-limited, possibly 1-2 days background), D2 ~0.5-1d. D0 is **fully credential-independent** and can
start immediately; D1 blocks on operator-supplied credentials + premium confirmation.

**Open items carried into implementation:**
1. USDJPY builder (16.1) vs swap to AUDUSD — confirm at draft of 16.1/16.2.
2. Actual M5 depth (Decision 2) — discovered during 16.5; 5y is a target, server floor is the real bound.
3. Operator must supply `SESSION_ID`/`SESSION_SIGN` (premium) before 16.4.
