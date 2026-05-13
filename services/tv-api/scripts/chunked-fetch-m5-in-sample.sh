#!/usr/bin/env bash
# Chunked walk-back campaign for XAUUSD M5 in_sample window 2024-01-01 → 2026-01-01.
# Server caps each anchor at ~5269 bars (~25 days) on premium ReplayMode, so we
# step -to backward in 20-day increments — each chunk requests its own 20-day
# window adjacent to the previous one (next iter's -to = previous iter's -from),
# writing numbered chunks. Merge sidecars + consolidate via
# trading-engine/scripts/stitch_chunks_to_window.py, which dedupes the handful
# of boundary-bar collisions and emits a single canonical Parquet + manifest.
#
# Idempotent: re-running skips any chunk whose .manifest.json already exists,
# so a transient failure can be resumed by simply running the script again.
set -euo pipefail

# All paths absolute so script works regardless of cwd.
TV_API_DIR=/home/hopdev/Dev/Sandboxed/services/tv-api
OUT_DIR=/home/hopdev/Dev/Sandboxed/data/historical/XAUUSD/M5/in_sample/chunks
LOG_FILE=/home/hopdev/Dev/Sandboxed/data/historical/XAUUSD/M5/in_sample/fetch.log

CAMPAIGN_TO=2026-01-01T00:00:00Z
CAMPAIGN_FROM=2024-01-01T00:00:00Z
STEP_DAYS=20

# Retry policy for transient network errors (e.g. TLS handshake timeout on
# vn.tradingview.com geo-redirect). Backoff in seconds.
MAX_ATTEMPTS=3
BACKOFF_SECONDS=(10 30 60)

mkdir -p "$OUT_DIR"
# Append to log on resume; banner makes resume boundary obvious.
printf '\n===== campaign start %s =====\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG_FILE"

cd "$TV_API_DIR"

to=$CAMPAIGN_TO
i=0
total_bars=0
skipped=0
while :; do
  from=$(date -u -d "$to - ${STEP_DAYS} days" +%Y-%m-%dT%H:%M:%SZ)
  if [[ "$from" < "$CAMPAIGN_FROM" ]]; then
    from=$CAMPAIGN_FROM
  fi

  chunk_file="${OUT_DIR}/$(printf '%03d' "$i").parquet"
  manifest_file="${chunk_file}.manifest.json"

  if [[ -f "$manifest_file" ]]; then
    bars=$(python3 -c "import json; m=json.load(open('${manifest_file}')); print(m['entries'][0]['row_count'])")
    total_bars=$((total_bars + bars))
    skipped=$((skipped + 1))
    printf '[%s] iter=%03d SKIP (manifest exists) bars=%s cumulative=%s\n' \
      "$(date -u +%H:%M:%S)" "$i" "$bars" "$total_bars" | tee -a "$LOG_FILE"
  else
    printf '[%s] iter=%03d anchor=%s from=%s\n' "$(date -u +%H:%M:%S)" "$i" "$to" "$from" | tee -a "$LOG_FILE"

    attempt=1
    success=0
    while (( attempt <= MAX_ATTEMPTS )); do
      if ./bin/tv-cli -command backtest-fetch -replay-mode \
          -symbol OANDA:XAUUSD -timeframe 5 \
          -from "$from" -to "$to" \
          -spec-name xauusd-validation -dataset-version v1 \
          -window-name "in_sample_chunk_$(printf '%03d' "$i")" -window-kind in_sample \
          -out "$chunk_file" >>"$LOG_FILE" 2>&1; then
        success=1
        break
      fi
      if (( attempt < MAX_ATTEMPTS )); then
        sleep_for=${BACKOFF_SECONDS[$((attempt - 1))]}
        printf '  ! attempt %d/%d failed — sleeping %ss before retry\n' \
          "$attempt" "$MAX_ATTEMPTS" "$sleep_for" | tee -a "$LOG_FILE"
        sleep "$sleep_for"
      fi
      attempt=$((attempt + 1))
    done

    if (( success != 1 )); then
      echo "FAILED at iter $i after $MAX_ATTEMPTS attempts (re-run script to resume)" | tee -a "$LOG_FILE"
      exit 1
    fi

    bars=$(python3 -c "import json; m=json.load(open('${manifest_file}')); print(m['entries'][0]['row_count'])")
    total_bars=$((total_bars + bars))
    printf '  → bars=%s cumulative=%s\n' "$bars" "$total_bars" | tee -a "$LOG_FILE"
  fi

  [[ "$from" == "$CAMPAIGN_FROM" ]] && break
  to=$from
  i=$((i + 1))
done

printf '[%s] done iters=%d skipped=%d total_chunk_bars=%d (overlaps included)\n' \
  "$(date -u +%H:%M:%S)" "$((i + 1))" "$skipped" "$total_bars" | tee -a "$LOG_FILE"
