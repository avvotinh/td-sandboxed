# Epic 16 — Historical Data Quality-Gate Report

**Date:** 2026-05-24
**Story:** 16.7 (quality gate) — closes Epic 16 D2 with 16.6 (per-symbol merge).
**Source:** OANDA via TradingView premium ReplayMode (`tv-cli backtest-fetch`); driver
`scripts/fetch_campaign.py`; canonical stitch `stitch_chunks_to_window.py`.
**Data location:** `data/historical/<SYMBOL>/<TF>/{in_sample,oos_reserve}.parquet` (+ `.manifest.json`)
and merged per-symbol manifests `services/trading-engine/manifests/<symbol>-5y.json`. **All gitignored**
— regenerate per `docs/runbooks/backtest-data-fetch.md` + `scripts/fetch_campaign.py`.

## Verdict: ✅ PASS — 32/32 shards, ready for backtest/ML

All four quality gates pass on every shard; the merged manifests are consumable by
`baseline_harness` (indexed + looked up all 8 (window, timeframe) keys per symbol; parquet paths
resolve).

## Inventory (32 shards = 4 symbols × 4 timeframes × 2 windows)

Windows: `in_sample` 2021-01-01→2026-01-01 (target 5y), `oos_reserve` 2026-01-01→2026-05-01 (held out).
All in_sample shards floor at **2021-01-03** (≈5y; 2 calendar days short of target — negligible, no
window reconciliation needed). `tf` label correct on all (MT label, not tv minutes — story 16.6 fix).

| Symbol | M5 (in/oos) | M15 (in/oos) | H1 (in/oos) | H4 (in/oos) | gaps in/oos |
|---|---|---|---|---|---|
| XAUUSD | 354 635 / 23 146 | 118 228 / 7 717 | 29 570 / 1 931 | 7 733 / 505 | 10 / 1 |
| EURUSD | 373 054 / 24 516 | 124 489 / 8 173 | 31 125 / 2 044 | 7 782 / 511 | 3 / 0 |
| GBPUSD | 372 900 / 24 514 | 124 485 / 8 173 | 31 125 / 2 044 | 7 782 / 511 | 3 / 0 |
| USDJPY | 373 077 / 24 507 | 124 498 / 8 173 | 31 125 / 2 044 | 7 782 / 511 | 3 / 0 |

Price-range sanity (distinct, correct): XAUUSD 1616–4546 · EURUSD 0.95–1.23 · GBPUSD 1.04–1.42 ·
USDJPY 102.6–161.9. (Confirms no cross-symbol data mix; identical row counts across the 3 FX pairs are
expected — same OANDA calendar.)

## Gates

1. **Completeness** — 32/32 canonical shards present; merged manifests carry all 8 (window, tf) entries per symbol. ✅
2. **Timeframe label** — every manifest entry uses the MT label (`M5/M15/H1/H4`), matching
   `baseline_harness` key + `pipeline.timeframe_to_seconds` (story 16.6). Verified round-trip. ✅
3. **De-duplication** — overlapping stepped-anchor chunks deduped on `time` by `stitch_chunks_to_window.py`
   (overlap drops were ~0–1 per shard; no duplicate timestamps in canonical parquet). ✅
4. **Gaps** — all flagged gaps (≤10/shard) are benign weekend/holiday closures above the 72h threshold
   (tuned in 16.4 from 48h, which had flagged every ~51–52h weekend). No unexpected mid-week gaps. ✅
5. **Depth** — every timeframe reaches ~5y (2021-01-03); M5 on premium ReplayMode beat the pessimistic
   2–3y floor prediction (epic-16 Decision 2). ✅
6. **Consumability** — `baseline_harness._index_manifest` + `_lookup_entry` succeed for all 8 keys per
   symbol against the merged manifest; parquet paths exist. ✅

## Provenance & caveats

- **Source = OANDA** (TradingView); fetch symbol `OANDA:<TICKER>`, manifest stores bare ticker.
- **UTC end-to-end.** Bars are session-anchored to OANDA's 17:00-New-York day (H4 timestamps land at
  22:00 UTC winter / 21:00 UTC summer, DST-shifting). Window boundaries are clean UTC instants.
- **Spread is modeled, not captured** — backtest applies spread via `configs/firms/ftmo.yaml`
  (`SpreadAwareFeeModel`); OANDA retail spreads differ from FTMO MT5. Spread-as-feature unavailable for
  ML (Epic 15 design R5).
- **USDJPY** requires the JPY instrument builder (story 16.1, `_build_jpy_pair_instrument`); without it
  USDJPY backtests fall to `default_fx_ccy` (2 bps fee + wrong precision).
- **Process note:** GBPUSD/USDJPY M5 were re-fetched after a Stage-C race (a script edit during a
  background loop invoking it → `can't open fetch_campaign.py`). Lesson: never edit a script a
  background job is running.

## Regeneration

```bash
# fetch (per symbol/timeframe, premium credentials in services/tv-api/.env)
uv run python scripts/fetch_campaign.py --spec ../../configs/datasets/<symbol>-5y.yaml
# re-stitch existing chunks only (no network)
uv run python scripts/fetch_campaign.py --spec ... --stitch-only --timeframes M5,M15,H1,H4
# merge per-symbol multi-entry manifest (16.6)
uv run python -c "from src.backtesting.dataset.go_manifest_loader import merge_go_manifests; ..."
```

## Out of scope
16.8 (TimescaleDB `candles` load) deferred — backtest consumes Parquet; only load if a non-backtest
consumer needs it.
