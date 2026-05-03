# Runbook — Backtest data fetch via tv-api

**Audience:** Operator running Epic 12 validation campaign.

**Goal:** populate `data/historical/<symbol>/<tf>/<window>.parquet` shards for the trading-engine backtest dataset pipeline using the TradingView free-tier FakeReplay API ported into `services/tv-api/`.

This runbook covers the four-shard XAUUSD M5+M15 × in_sample+oos_reserve campaign that Epic 12 needs. The same procedure scales to other intraday timeframes and symbols by swapping the flags.

---

## Prerequisites

- Go toolchain installed (`go.mod` is pinned to 1.24.9).
- TradingView free account (no auth needed for FakeReplay; premium ReplayMode is deferred to story 12.7.0e).
- Network access to `wss://data.tradingview.com/socket.io/websocket?type=chart`.
- ~10–20 GB free disk for full XAUUSD M5+M15 2024-01 → 2026-04 (≈300K Parquet rows total, Snappy-compressed << 100 MB).

## Build the CLI

```bash
cd services/tv-api
go build -o bin/tv-cli ./cmd/tv-cli
./bin/tv-cli -help | head -50
```

## Run the four-shard XAUUSD campaign

```bash
# 1) M5 in-sample (2 years)
./bin/tv-cli -command backtest-fetch \
  -symbol OANDA:XAUUSD -timeframe 5 \
  -from 2024-01-01T00:00:00Z -to 2026-01-01T00:00:00Z \
  -spec-name xauusd-validation -dataset-version v1 \
  -window-name in_sample -window-kind in_sample \
  -out ../../data/historical/XAUUSD/M5/in_sample.parquet

# 2) M5 OOS reserve (4 months)
./bin/tv-cli -command backtest-fetch \
  -symbol OANDA:XAUUSD -timeframe 5 \
  -from 2026-01-01T00:00:00Z -to 2026-04-30T23:59:59Z \
  -spec-name xauusd-validation -dataset-version v1 \
  -window-name oos_reserve -window-kind oos_reserve \
  -out ../../data/historical/XAUUSD/M5/oos_reserve.parquet

# 3) M15 in-sample
./bin/tv-cli -command backtest-fetch \
  -symbol OANDA:XAUUSD -timeframe 15 \
  -from 2024-01-01T00:00:00Z -to 2026-01-01T00:00:00Z \
  -spec-name xauusd-validation -dataset-version v1 \
  -window-name in_sample -window-kind in_sample \
  -out ../../data/historical/XAUUSD/M15/in_sample.parquet

# 4) M15 OOS reserve
./bin/tv-cli -command backtest-fetch \
  -symbol OANDA:XAUUSD -timeframe 15 \
  -from 2026-01-01T00:00:00Z -to 2026-04-30T23:59:59Z \
  -spec-name xauusd-validation -dataset-version v1 \
  -window-name oos_reserve -window-kind oos_reserve \
  -out ../../data/historical/XAUUSD/M15/oos_reserve.parquet
```

Each invocation produces a Parquet shard plus a JSON sidecar at `<out>.manifest.json`.

## Merge sidecars into the canonical manifest

```bash
cd services/trading-engine
uv run python -m src.backtesting.dataset.go_manifest_loader \
  --sidecar ../../data/historical/XAUUSD/M5/in_sample.parquet.manifest.json \
  --sidecar ../../data/historical/XAUUSD/M5/oos_reserve.parquet.manifest.json \
  --sidecar ../../data/historical/XAUUSD/M15/in_sample.parquet.manifest.json \
  --sidecar ../../data/historical/XAUUSD/M15/oos_reserve.parquet.manifest.json \
  --out manifests/xauusd-validation-v1.json
```

The merged JSON is the authoritative `DatasetManifest` that `DatasetPipeline.materialize_async` and the Epic 12 validation harness consume.

## Tuning knobs

| Flag | Default | When to change |
|---|---|---|
| `-throttle-ms` | 150 | Increase to 250–500 if you see WebSocket reconnects mid-fetch. The free-tier rate limit is generous but undocumented. |
| `-batch-size` | 1000 | Decrease to 500 for very long ranges (>2 years M5) where the server occasionally returns short batches. Cap is 5000 (CLI rejects above). |
| `-max-batches` | 1000 | Ceiling at ≈ batch-size × max-batches bars. Default = 1M bars, plenty for M5/M15. |
| `-max-gap-hours` | 48 | The threshold for flagging a missing-bars gap in the manifest. Defaults to "longer than a weekend"; tighten to 24 if running on a 24/7 instrument like crypto. |

## Verifying the fetch

```bash
# Inspect the Parquet directly.
uv run python -c "
import pandas as pd
df = pd.read_parquet('../../data/historical/XAUUSD/M5/in_sample.parquet')
print(df.dtypes)
print(df.head())
print('rows:', len(df))
"

# Confirm the manifest loads through the canonical Python path.
uv run python -c "
from src.backtesting.dataset.manifest import DatasetManifest
m = DatasetManifest.load_json('manifests/xauusd-validation-v1.json')
print('symbol:', m.symbol)
print('total rows:', m.total_rows)
print('gaps:', m.gap_count)
for e in m.entries:
    print(f'  {e.timeframe} {e.window_name}: {e.row_count} rows fp={e.fingerprint.sha256()}')
"
```

## Recovery from partial / failed fetches

The Parquet writer is atomic: on any error mid-fetch the temp file `<out>.tmp` is removed and the final path is **not** created. There is no "resume" — re-run the same command. The fingerprint depends on the full row set, so a partial shard would carry a different fingerprint anyway.

If the WebSocket drops mid-fetch, the tv-api session.ChartSession reconnects automatically with reference-aware logic (story 12.7.0a) and bars already buffered in the session de-duplicate by timestamp. You should see the fetch resume and complete normally; if it still fails after 2–3 retries, increase `-throttle-ms` and try again.

If TradingView reports a `series_error` containing "no more bars" or similar terminal phrasing, FetchUntil treats that as "server has no older data" and stops cleanly — the resulting Parquet covers `[max(server-floor, -from), -to]` with whatever bars are available. This is the expected behaviour for symbols with limited history.

## Caveats

- **ToS:** the TradingView API used here is reverse-engineered. There is no SLA, and rate-limit responses are silent. Use modest concurrency (one fetch at a time per IP).
- **Data provenance:** OANDA:XAUUSD on TradingView reflects OANDA retail spreads; FTMO MT5 spreads differ. Per Decision §1 in `docs/epic-12-context.md`, spread for the backtest comes from `configs/firms/ftmo.yaml` via `SpreadAwareFeeModel`, not from the bars file — so this provenance gap does not block the validation campaign.
- **Intraday-only:** FakeReplay free-tier supports timeframes `1, 3, 5, 15, 30, 60, 120, 240`. Daily/weekly/monthly require premium ReplayMode (story 12.7.0e, deferred).
- **Symbol mapping:** Manifest writes the bare ticker (`XAUUSD`), not the exchange-prefixed form (`OANDA:XAUUSD`). This matches `configs/datasets/*.yaml` shorthand.

## Story references

- 12.7.0a — FakeReplay protocol port (`pkg/tradingview` + `internal/session`).
- 12.7.0b — Parquet writer + JSON manifest (`internal/store`).
- 12.7.0c — `tv-cli backtest-fetch` command (`cmd/tv-cli`).
- 12.7.0d — Python merge tool + this runbook.
- 12.7.0e — premium ReplayMode (deferred until premium account is available).
