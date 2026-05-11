#!/usr/bin/env bash
# Generalized chunked walk-back fetch for any (symbol, timeframe, window).
#
# Server caps each anchor at ~5500 bars regardless of subscription, so the
# campaign window is split into adjacent chunks each requesting one
# --step-days slice. Per-anchor bar count: ~4000 (M5 @ 20d), ~5400
# (M15 @ 80d), ~4000 (D @ many years) — tune --step-days for your timeframe.
#
# Idempotent: skips chunks whose .manifest.json already exists.
# Retry-tolerant: 3 attempts per chunk with 10/30/60s backoff for transient
# network errors (e.g. TLS handshake timeout on geo-redirect hosts).
#
# Output layout (paths derived automatically):
#   data/historical/<bare-symbol>/<tf-label>/<window-name>/chunks/NNN.parquet
#   data/historical/<bare-symbol>/<tf-label>/<window-name>/fetch.log
#
# Usage:
#   ./chunked-fetch.sh \
#     --symbol OANDA:XAUUSD --bare-symbol XAUUSD \
#     --timeframe 5 --tf-label M5 \
#     --window-name in_sample --window-kind in_sample \
#     --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
#     --step-days 20
set -euo pipefail

REPO_ROOT=/home/hopdev/Dev/Sandboxed
TV_API_DIR="$REPO_ROOT/services/tv-api"

MAX_ATTEMPTS=3
BACKOFF_SECONDS=(10 30 60)

# --- arg parsing ------------------------------------------------------
SYMBOL=""
BARE_SYMBOL=""
TIMEFRAME=""
TF_LABEL=""
WINDOW_NAME=""
WINDOW_KIND=""
CAMPAIGN_FROM=""
CAMPAIGN_TO=""
STEP_DAYS=""
SPEC_NAME="xauusd-validation"
DATASET_VERSION="v1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --symbol)          SYMBOL="$2";          shift 2 ;;
    --bare-symbol)     BARE_SYMBOL="$2";     shift 2 ;;
    --timeframe)       TIMEFRAME="$2";       shift 2 ;;
    --tf-label)        TF_LABEL="$2";        shift 2 ;;
    --window-name)     WINDOW_NAME="$2";     shift 2 ;;
    --window-kind)     WINDOW_KIND="$2";     shift 2 ;;
    --from)            CAMPAIGN_FROM="$2";   shift 2 ;;
    --to)              CAMPAIGN_TO="$2";     shift 2 ;;
    --step-days)       STEP_DAYS="$2";       shift 2 ;;
    --spec-name)       SPEC_NAME="$2";       shift 2 ;;
    --dataset-version) DATASET_VERSION="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

for var in SYMBOL BARE_SYMBOL TIMEFRAME TF_LABEL WINDOW_NAME WINDOW_KIND \
           CAMPAIGN_FROM CAMPAIGN_TO STEP_DAYS; do
  if [[ -z "${!var}" ]]; then
    echo "Missing required --$(echo "$var" | tr '[:upper:]' '[:lower:]' | tr _ -)" >&2
    exit 2
  fi
done

OUT_DIR="$REPO_ROOT/data/historical/$BARE_SYMBOL/$TF_LABEL/$WINDOW_NAME/chunks"
LOG_FILE="$REPO_ROOT/data/historical/$BARE_SYMBOL/$TF_LABEL/$WINDOW_NAME/fetch.log"

mkdir -p "$OUT_DIR"
printf '\n===== campaign start %s sym=%s tf=%s win=%s [%s → %s] step=%sd =====\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$BARE_SYMBOL" "$TF_LABEL" "$WINDOW_NAME" "$CAMPAIGN_FROM" "$CAMPAIGN_TO" "$STEP_DAYS" \
  >>"$LOG_FILE"

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
          -symbol "$SYMBOL" -timeframe "$TIMEFRAME" \
          -from "$from" -to "$to" \
          -spec-name "$SPEC_NAME" -dataset-version "$DATASET_VERSION" \
          -window-name "${WINDOW_NAME}_chunk_$(printf '%03d' "$i")" \
          -window-kind "$WINDOW_KIND" \
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
      echo "FAILED at iter $i after $MAX_ATTEMPTS attempts (re-run to resume)" | tee -a "$LOG_FILE"
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

printf '[%s] done iters=%d skipped=%d total_chunk_bars=%d\n' \
  "$(date -u +%H:%M:%S)" "$((i + 1))" "$skipped" "$total_bars" | tee -a "$LOG_FILE"
