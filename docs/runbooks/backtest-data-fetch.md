# Runbook — Backtest data fetch via tv-api

**Audience:** Operator running Epic 12 validation campaign.

**Goal:** populate `data/historical/<symbol>/<tf>/<window>.parquet` shards for the trading-engine backtest dataset pipeline using the TradingView API ported into `services/tv-api/`.

The CLI auto-routes between two API surfaces based on the timeframe:

- **Intraday timeframes** (`1`, `3`, `5`, `15`, `30`, `60`, `120`, `240`) — free-tier FakeReplay path. No premium subscription required (story 12.7.0a–d).
- **Daily / weekly / monthly** (`D`/`1D`, `W`/`1W`, `M`/`1M`) — premium ReplayMode (story 12.7.0e). Requires a TradingView account with replay entitlement; the CLI fetches `SESSION_ID` and `SESSION_SIGN` cookies from environment exactly like the intraday path.

This runbook covers the four-shard XAUUSD M5+M15 × in_sample+oos_reserve campaign that Epic 12 needs. The same procedure scales to other timeframes and symbols by swapping the flags — the auto-route picks FakeReplay or ReplayMode without operator input.

> **Anchor history cap (empirical, 2026-05-11 on `oanhcao_dev5` premium account):**
> The server applies a hard cap of **≈ 5500 bars per `-to` anchor**, regardless of `-from`, `-batch-size`, `-max-batches`, or subscription tier. The bar count is constant; the calendar coverage depends on timeframe:
>
> | Timeframe | Bars/anchor | Calendar coverage back from `-to` |
> |---|---|---|
> | M1 | ~5621 | ~4 trading days |
> | M5 premium ReplayMode | ~5269 | ~25 days |
> | M5 FakeReplay (free tier or no flag) | ~3888 | ~18 days |
> | M15 (interpolated) | ~5500 | ~75 days |
> | 1D / 1W / 1M | well under cap | a single call covers years |
>
> For multi-month / multi-year intraday windows you MUST run a series of calls with stepped `-to` anchors and merge via `go_manifest_loader`. The `-replay-mode` flag forces premium ReplayMode for intraday timeframes (wider per-anchor window). M1 additionally needs `-response-timeout-ms ≥ 5000` because the initial replay batch is slow to materialise (default 2000 ms times out).

---

## Prerequisites

- Go toolchain installed (`go.mod` is pinned to 1.24.9).
- TradingView account credentials: `SESSION_ID` + `SESSION_SIGN` env vars (or `.env` file). The same credentials power both modes; ReplayMode additionally requires the account to have premium replay entitlement.
- Network access to `wss://data.tradingview.com/socket.io/websocket?type=chart`.
- ~10–20 GB free disk for full XAUUSD M5+M15 2024-01 → 2026-04 (≈300K Parquet rows total, Snappy-compressed << 100 MB).

## Build the CLI

```bash
cd services/tv-api
go build -o bin/tv-cli ./cmd/tv-cli
./bin/tv-cli -help | head -50
```

## Run the four-shard XAUUSD campaign

Because each call caps at ~25 days, a 2-year M5 in-sample shard requires ~30 stepped invocations. Drive the loop from a shell script that walks `-to` backward in 20-day increments (5-day safety overlap absorbs weekend gaps and partial batches), writing each chunk to a numbered file. Then merge with `go_manifest_loader`.

```bash
# 1) M5 in-sample — chunked walk, ~30 calls covering 2024-01-01 → 2026-01-01
mkdir -p chunks/XAUUSD/M5/in_sample
to=2026-01-01T00:00:00Z
i=0
while :; do
  from=$(date -u -d "$to - 20 days" +%Y-%m-%dT%H:%M:%SZ)
  ./bin/tv-cli -command backtest-fetch -replay-mode \
    -symbol OANDA:XAUUSD -timeframe 5 \
    -from "$from" -to "$to" \
    -spec-name xauusd-validation -dataset-version v1 \
    -window-name in_sample -window-kind in_sample \
    -out chunks/XAUUSD/M5/in_sample/$(printf '%03d' $i).parquet || break
  [[ "$from" < "2024-01-01T00:00:00Z" ]] && break
  to=$from
  i=$((i+1))
done
```

Repeat with `to=2026-04-30T23:59:59Z`, walking back to `2026-01-01T00:00:00Z` for the OOS reserve shard (~6 calls); swap `-timeframe 5` for `15` to run the M15 pair. The campaign produces four directories of chunked Parquet files plus their `.manifest.json` sidecars.

Merge each shard's chunks via `go_manifest_loader --sidecar chunks/.../*.parquet.manifest.json …` — see [Merge sidecars into the canonical manifest](#merge-sidecars-into-the-canonical-manifest). The tool concatenates manifest entries; row-level deduplication of the 5-day overlap is not done here, so the consumer must dedupe by `(timeframe, ts)` before backtest replay. Verify the merged shard has no duplicate timestamps with `pandas.duplicated()` against the union of all chunk Parquets before treating it as the canonical dataset.

## ReplayMode example (premium account, daily / weekly / monthly)

The CLI auto-detects daily / weekly / monthly timeframes (`D`, `1D`, `W`, `1W`, `M`, `1M`) and routes through premium ReplayMode. Same flag surface, same output shape — only the underlying API call changes.

```bash
# Daily XAUUSD, 5 years of in-sample data
./bin/tv-cli -command backtest-fetch \
  -symbol OANDA:XAUUSD -timeframe 1D \
  -from 2021-01-01T00:00:00Z -to 2026-01-01T00:00:00Z \
  -spec-name xauusd-daily -dataset-version v1 \
  -window-name in_sample -window-kind in_sample \
  -out ../../data/historical/XAUUSD/D1/in_sample.parquet
```

If the account lacks replay entitlement the server silently returns no bars; the CLI surfaces this as `zero bars in […] — likely symbol-feed mismatch or premium-account entitlement missing` rather than hanging.

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
- **Timeframe split:** intraday timeframes (`1, 3, 5, 15, 30, 60, 120, 240`) work on any account. Daily / weekly / monthly require a premium TradingView account with replay entitlement — the CLI auto-routes but a free account silently yields zero bars.
- **Anchor history cap (server-side):** ~25 days back from `-to` on premium ReplayMode, ~18 days on FakeReplay. Multi-month windows require chunked walks (see [Run the four-shard XAUUSD campaign](#run-the-four-shard-xauusd-campaign)). Empirically reproduced 2026-05-11 on `oanhcao_dev5` across both `to=2026-05-01` and `to=2024-06-01` anchors — the cap travels with the anchor, not with the calendar.
- **`--replay-mode` override:** forces premium ReplayMode for intraday timeframes (default auto-route only enables ReplayMode for D/W/M). On premium accounts ReplayMode returns ~7 days more intraday history per anchor than FakeReplay — measurable as 5269 vs 3888 M5 bars in the empirical smoke. Without a premium subscription, `--replay-mode` produces zero bars for any timeframe.
- **`--response-timeout-ms` override:** raises the per-batch response wait. Default 2000 ms suffices for M5 and coarser timeframes. M1 in replay mode requires ≥5000 ms (empirically the initial batch lands in ~6–8 s as the server materialises high-density bars at a historical anchor). Without bumping, M1 fails with `fetch_until: no initial batch within 2s`.
- **Symbol mapping:** Manifest writes the bare ticker (`XAUUSD`), not the exchange-prefixed form (`OANDA:XAUUSD`). This matches `configs/datasets/*.yaml` shorthand.

## Story references

- 12.7.0a — FakeReplay protocol port (`pkg/tradingview` + `internal/session`).
- 12.7.0b — Parquet writer + JSON manifest (`internal/store`).
- 12.7.0c — `tv-cli backtest-fetch` command (`cmd/tv-cli`).
- 12.7.0d — Python merge tool + this runbook.
- 12.7.0e — premium ReplayMode port (`internal/session/replay.go` + `pkg/tradingview/replay.go` + CLI auto-route). Daily/weekly/monthly bars unblocked.
