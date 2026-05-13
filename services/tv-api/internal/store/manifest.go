// Package store — JSON manifest emitted alongside the Parquet shard.
//
// Story 12.7.0b: schema mirrors Python
// services/trading-engine/src/backtesting/dataset/manifest.py exactly so a
// Go-written sidecar round-trips through DatasetManifest.load_json
// without bespoke adapter logic. Field names, ordering, and especially
// the fingerprint formula (sha256("min_ts|max_ts|row_count")[:16] over
// nanosecond timestamps) MUST match — any drift breaks the cross-language
// reproducibility guarantee.
package store

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"
)

// ManifestSchemaVersion mirrors the Python `_MANIFEST_SCHEMA_VERSION`
// constant in manifest.py:25. Bump together when the schema changes.
const ManifestSchemaVersion = "1"

// Fingerprint is the 4-tuple Python's ContentHashFingerprint dataclass
// dumps via to_dict(). min_ts and max_ts are nanoseconds; sha256_short
// is the 16-character truncation of sha256("min|max|count").
type Fingerprint struct {
	MinTs       int64  `json:"min_ts"`
	MaxTs       int64  `json:"max_ts"`
	RowCount    int    `json:"row_count"`
	Sha256Short string `json:"sha256_short"`
}

// BarGap mirrors Python BarGap.to_dict — duration_hours is computed at
// emit time from the (after − before) span.
type BarGap struct {
	Timeframe     string  `json:"timeframe"`
	WindowName    string  `json:"window_name"`
	Before        string  `json:"before"`
	After         string  `json:"after"`
	DurationHours float64 `json:"duration_hours"`
}

// DatasetEntry mirrors Python DatasetEntry.to_dict.
type DatasetEntry struct {
	Timeframe   string      `json:"timeframe"`
	WindowName  string      `json:"window_name"`
	WindowKind  string      `json:"window_kind"`
	Start       string      `json:"start"`
	End         string      `json:"end"`
	ParquetPath string      `json:"parquet_path"`
	Fingerprint Fingerprint `json:"fingerprint"`
	RowCount    int         `json:"row_count"`
	Gaps        []BarGap    `json:"gaps"`
}

// DatasetManifest mirrors Python DatasetManifest.to_dict.
type DatasetManifest struct {
	SchemaVersion  string         `json:"schema_version"`
	SpecName       string         `json:"spec_name"`
	DatasetVersion string         `json:"dataset_version"`
	Symbol         string         `json:"symbol"`
	GeneratedAt    string         `json:"generated_at"`
	MaxGapHours    float64        `json:"max_gap_hours"`
	Entries        []DatasetEntry `json:"entries"`
}

// ComputeFingerprint reproduces the Python data_cache.py:54-57 formula
// over a sorted-ascending slice of bars. Times in the BarRow are
// Unix-millisecond ints, but the fingerprint payload uses nanoseconds to
// match Python's tz-aware DataFrame index → ms × 1_000_000.
//
// The caller is responsible for pre-sorting; sorting here would either
// mutate the caller's slice or force an allocation.
func ComputeFingerprint(rows []BarRow) Fingerprint {
	if len(rows) == 0 {
		return Fingerprint{}
	}
	const msToNs int64 = 1_000_000
	minNs := rows[0].Time * msToNs
	maxNs := rows[len(rows)-1].Time * msToNs
	count := len(rows)
	payload := fmt.Sprintf("%d|%d|%d", minNs, maxNs, count)
	sum := sha256.Sum256([]byte(payload))
	return Fingerprint{
		MinTs:       minNs,
		MaxTs:       maxNs,
		RowCount:    count,
		Sha256Short: hex.EncodeToString(sum[:])[:16],
	}
}

// timeframeMillis maps a TradingView intraday timeframe string to the
// expected bar interval in milliseconds. Used by DetectGaps to compute
// the "expected next bar timestamp" floor.
func timeframeMillis(tf string) (int64, error) {
	switch tf {
	case "1":
		return 60_000, nil
	case "3":
		return 3 * 60_000, nil
	case "5":
		return 5 * 60_000, nil
	case "15":
		return 15 * 60_000, nil
	case "30":
		return 30 * 60_000, nil
	case "60":
		return 60 * 60_000, nil
	case "120":
		return 120 * 60_000, nil
	case "240":
		return 240 * 60_000, nil
	case "D", "1D":
		return 24 * 60 * 60_000, nil
	default:
		return 0, fmt.Errorf("timeframeMillis: unsupported timeframe %q", tf)
	}
}

// DetectGaps walks a sorted-ascending slice of bars and emits a BarGap
// for every consecutive pair where (after − before) exceeds
// maxGapHours. The duration_hours field reports the actual gap length
// (after − before in hours), matching Python's BarGap.duration_hours
// property which includes the expected bar interval.
//
// maxGapHours == 0 disables detection (returns empty slice).
func DetectGaps(rows []BarRow, timeframe, windowName string, maxGapHours float64) []BarGap {
	if maxGapHours <= 0 || len(rows) < 2 {
		return []BarGap{}
	}
	if _, err := timeframeMillis(timeframe); err != nil {
		// Unknown timeframe — skip gap detection rather than guess.
		return []BarGap{}
	}

	gaps := make([]BarGap, 0)
	maxGapMillis := int64(maxGapHours * 3_600_000)

	for i := 1; i < len(rows); i++ {
		delta := rows[i].Time - rows[i-1].Time
		if delta <= maxGapMillis {
			continue
		}
		before := time.UnixMilli(rows[i-1].Time).UTC()
		after := time.UnixMilli(rows[i].Time).UTC()
		gaps = append(gaps, BarGap{
			Timeframe:     timeframe,
			WindowName:    windowName,
			Before:        before.Format(time.RFC3339Nano),
			After:         after.Format(time.RFC3339Nano),
			DurationHours: float64(delta) / 3_600_000.0,
		})
	}
	return gaps
}

// FormatRFC3339UTC formats a timestamp byte-identically to Python's
// `datetime.astimezone(UTC).isoformat()` (Python manifest.py:28-29):
//
//   - exact second  → "2026-05-03T12:34:56+00:00"            (no fractional)
//   - sub-second    → "2026-05-03T12:34:56.123456+00:00"     (always 6 digits)
//
// Python's datetime is microsecond-precision; truncating below that
// preserves exact equality on round-trip. The +00:00 offset is mandatory
// (Z parses differently on Python ≤ 3.10 even though we target ≥ 3.11).
func FormatRFC3339UTC(t time.Time) string {
	t = t.UTC().Truncate(time.Microsecond)
	if t.Nanosecond() == 0 {
		return t.Format("2006-01-02T15:04:05-07:00")
	}
	return t.Format("2006-01-02T15:04:05.000000-07:00")
}

// WriteManifest serialises the manifest to JSON with sorted map keys and
// 2-space indent — byte-identical to Python's
// json.dumps(..., indent=2, sort_keys=True). The destination directory
// is created if absent. Manifest path is conventionally
// `<parquet_path>.manifest.json`; that placement keeps shard + sidecar
// adjacent in the filesystem.
func WriteManifest(path string, m DatasetManifest) error {
	if path == "" {
		return fmt.Errorf("WriteManifest: path is required")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("WriteManifest: mkdir %q: %w", filepath.Dir(path), err)
	}

	doc, err := canonicalJSON(m)
	if err != nil {
		return fmt.Errorf("WriteManifest: encode: %w", err)
	}

	if err := os.WriteFile(path, doc, 0o644); err != nil {
		return fmt.Errorf("WriteManifest: write %q: %w", path, err)
	}
	return nil
}

// canonicalJSON produces JSON byte-identical to Python's
// json.dumps(payload, indent=2, sort_keys=True). Go's json package does
// not sort map keys at struct level, so we round-trip through
// map[string]any and re-emit with sorted keys.
func canonicalJSON(v any) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var generic any
	if err := json.Unmarshal(raw, &generic); err != nil {
		return nil, err
	}
	return marshalSorted(generic, "  ", "")
}

// marshalSorted is a small canonical JSON encoder that sorts object keys
// and uses indent + prefix similar to Python's json.dumps. It does not
// re-implement number formatting — it relies on json.Marshal for scalar
// encoding.
func marshalSorted(v any, indent, prefix string) ([]byte, error) {
	switch val := v.(type) {
	case map[string]any:
		keys := make([]string, 0, len(val))
		for k := range val {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		nested := prefix + indent
		out := []byte("{")
		for i, k := range keys {
			if i > 0 {
				out = append(out, ',')
			}
			out = append(out, '\n')
			out = append(out, nested...)
			kRaw, _ := json.Marshal(k)
			out = append(out, kRaw...)
			out = append(out, ':', ' ')
			child, err := marshalSorted(val[k], indent, nested)
			if err != nil {
				return nil, err
			}
			out = append(out, child...)
		}
		if len(keys) > 0 {
			out = append(out, '\n')
			out = append(out, prefix...)
		}
		out = append(out, '}')
		return out, nil
	case []any:
		nested := prefix + indent
		out := []byte("[")
		for i, item := range val {
			if i > 0 {
				out = append(out, ',')
			}
			out = append(out, '\n')
			out = append(out, nested...)
			child, err := marshalSorted(item, indent, nested)
			if err != nil {
				return nil, err
			}
			out = append(out, child...)
		}
		if len(val) > 0 {
			out = append(out, '\n')
			out = append(out, prefix...)
		}
		out = append(out, ']')
		return out, nil
	default:
		return json.Marshal(v)
	}
}
