package store

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestComputeFingerprint_GoldenValueMatchesPythonFormula is the
// cross-language reproducibility guard: the SHA256 must equal what
// Python's `hashlib.sha256(f"{min_ns}|{max_ns}|{count}".encode())
// .hexdigest()[:16]` produces. If this test breaks, the manifest schema
// has drifted and trading-engine load will fail.
func TestComputeFingerprint_GoldenValueMatchesPythonFormula(t *testing.T) {
	rows := []BarRow{
		{Time: 1_700_000_000_000}, // ms
		{Time: 1_700_000_300_000},
		{Time: 1_700_000_600_000},
	}
	fp := ComputeFingerprint(rows)

	const msToNs int64 = 1_000_000
	wantMin := int64(1_700_000_000_000) * msToNs
	wantMax := int64(1_700_000_600_000) * msToNs
	wantCount := 3

	expectedPayload := fmt.Sprintf("%d|%d|%d", wantMin, wantMax, wantCount)
	expectedHash := sha256.Sum256([]byte(expectedPayload))
	wantSha := hex.EncodeToString(expectedHash[:])[:16]

	assert.Equal(t, wantMin, fp.MinTs, "min_ts must be ns")
	assert.Equal(t, wantMax, fp.MaxTs, "max_ts must be ns")
	assert.Equal(t, wantCount, fp.RowCount)
	assert.Equal(t, wantSha, fp.Sha256Short, "sha256 must match Python formula exactly")
}

// TestComputeFingerprint_EmptyInputReturnsZero documents that an empty
// row slice yields a zero-valued fingerprint rather than panicking on
// rows[len-1].
func TestComputeFingerprint_EmptyInputReturnsZero(t *testing.T) {
	fp := ComputeFingerprint(nil)
	assert.Zero(t, fp.MinTs)
	assert.Zero(t, fp.MaxTs)
	assert.Zero(t, fp.RowCount)
	assert.Empty(t, fp.Sha256Short)
}

// TestDetectGaps covers the most common shapes the operator will hit.
func TestDetectGaps(t *testing.T) {
	const (
		tf  = "5"
		win = "in_sample"
	)

	// Helper to build M5 bars with explicit timestamps in millis.
	mk := func(timesMs ...int64) []BarRow {
		out := make([]BarRow, len(timesMs))
		for i, t := range timesMs {
			out[i] = BarRow{Time: t}
		}
		return out
	}

	cases := []struct {
		name        string
		rows        []BarRow
		maxGapHours float64
		wantCount   int
	}{
		{name: "empty", rows: nil, maxGapHours: 48, wantCount: 0},
		{name: "single", rows: mk(1_700_000_000_000), maxGapHours: 48, wantCount: 0},
		{name: "no_gap_contiguous_M5", rows: mk(
			1_700_000_000_000,
			1_700_000_000_000+5*60_000,
			1_700_000_000_000+10*60_000,
		), maxGapHours: 48, wantCount: 0},
		{name: "weekend_gap_below_threshold", rows: mk(
			1_700_000_000_000,
			1_700_000_000_000+47*3_600_000, // 47 h gap
		), maxGapHours: 48, wantCount: 0},
		{name: "weekend_gap_above_threshold", rows: mk(
			1_700_000_000_000,
			1_700_000_000_000+50*3_600_000, // 50 h gap
		), maxGapHours: 48, wantCount: 1},
		{name: "two_gaps", rows: mk(
			1_700_000_000_000,
			1_700_000_000_000+50*3_600_000,
			1_700_000_000_000+50*3_600_000+5*60_000, // tight pair
			1_700_000_000_000+150*3_600_000,         // another big gap
		), maxGapHours: 48, wantCount: 2},
		{name: "max_gap_zero_disables", rows: mk(
			1_700_000_000_000,
			1_700_000_000_000+50*3_600_000,
		), maxGapHours: 0, wantCount: 0},
		{name: "unknown_timeframe_skips", rows: mk(
			1_700_000_000_000,
			1_700_000_000_000+50*3_600_000,
		), maxGapHours: 48, wantCount: 0}, // tested below with bad tf
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			actualTf := tf
			if tc.name == "unknown_timeframe_skips" {
				actualTf = "WEIRD"
			}
			gaps := DetectGaps(tc.rows, actualTf, win, tc.maxGapHours)
			require.Len(t, gaps, tc.wantCount)
			for _, g := range gaps {
				assert.Equal(t, actualTf, g.Timeframe)
				assert.Equal(t, win, g.WindowName)
				assert.Greater(t, g.DurationHours, tc.maxGapHours)
			}
		})
	}
}

// TestWriteManifest_RoundTripJSON confirms that the manifest can be
// written, then read back, and the deserialised structure equals the
// original. Validates JSON tag wiring end-to-end.
func TestWriteManifest_RoundTripJSON(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "shard.parquet.manifest.json")

	now := time.Date(2026, 5, 3, 12, 0, 0, 0, time.UTC)
	m := DatasetManifest{
		SchemaVersion:  ManifestSchemaVersion,
		SpecName:       "xauusd-validation",
		DatasetVersion: "v1",
		Symbol:         "XAUUSD",
		GeneratedAt:    FormatRFC3339UTC(now),
		MaxGapHours:    48.0,
		Entries: []DatasetEntry{
			{
				Timeframe:   "5",
				WindowName:  "in_sample",
				WindowKind:  "in_sample",
				Start:       FormatRFC3339UTC(time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)),
				End:         FormatRFC3339UTC(time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)),
				ParquetPath: "data/historical/XAUUSD/M5/in_sample.parquet",
				Fingerprint: ComputeFingerprint([]BarRow{
					{Time: 1_700_000_000_000},
					{Time: 1_700_000_300_000},
				}),
				RowCount: 2,
				Gaps:     []BarGap{},
			},
		},
	}

	require.NoError(t, WriteManifest(path, m))

	raw, err := os.ReadFile(path)
	require.NoError(t, err)

	var got DatasetManifest
	require.NoError(t, json.Unmarshal(raw, &got))
	assert.Equal(t, m, got)
}

// TestWriteManifest_KeysAreSortedAndIndented mirrors Python's
// json.dumps(..., indent=2, sort_keys=True). Byte-identical output is
// the contract — operator diffs on regenerated manifests should be
// limited to genuinely changed fields, not key reordering.
func TestWriteManifest_KeysAreSortedAndIndented(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "ordered.json")

	m := DatasetManifest{
		SchemaVersion:  "1",
		SpecName:       "alpha",
		DatasetVersion: "v1",
		Symbol:         "X",
		// Use the prod helper so the test stays in sync with the
		// fractional-second formatting rules — hand-typed strings hide
		// drift between FormatRFC3339UTC and the JSON contract.
		GeneratedAt: FormatRFC3339UTC(time.Date(2026, 5, 3, 0, 0, 0, 0, time.UTC)),
		MaxGapHours: 1.0,
		Entries:     []DatasetEntry{},
	}
	require.NoError(t, WriteManifest(path, m))

	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	body := string(raw)

	// Top-level keys appear in lexicographic order.
	posDataset := stringIndex(body, "\"dataset_version\":")
	posEntries := stringIndex(body, "\"entries\":")
	posGenerated := stringIndex(body, "\"generated_at\":")
	posMax := stringIndex(body, "\"max_gap_hours\":")
	posSchema := stringIndex(body, "\"schema_version\":")
	posSpec := stringIndex(body, "\"spec_name\":")
	posSymbol := stringIndex(body, "\"symbol\":")
	require.Less(t, posDataset, posEntries)
	require.Less(t, posEntries, posGenerated)
	require.Less(t, posGenerated, posMax)
	require.Less(t, posMax, posSchema)
	require.Less(t, posSchema, posSpec)
	require.Less(t, posSpec, posSymbol)

	assert.Contains(t, body, "  \"")
}

func stringIndex(haystack, needle string) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return i
		}
	}
	return -1
}

// TestFormatRFC3339UTC matches Python _isoformat byte-for-byte:
//
//   - integer second  → no fractional component (matches Python)
//   - sub-second      → exactly 6 microsecond digits (matches Python)
//   - +00:00 offset   → required (Python ≤ 3.10 stumbles on Z)
func TestFormatRFC3339UTC(t *testing.T) {
	cases := []struct {
		name string
		ts   time.Time
		want string
	}{
		{
			name: "exact_second",
			ts:   time.Date(2026, 5, 3, 12, 34, 56, 0, time.UTC),
			want: "2026-05-03T12:34:56+00:00",
		},
		{
			name: "microsecond_precision",
			ts:   time.Date(2026, 5, 3, 12, 34, 56, 123456*1000, time.UTC),
			want: "2026-05-03T12:34:56.123456+00:00",
		},
		{
			name: "nanos_truncate_to_micros",
			ts:   time.Date(2026, 5, 3, 12, 34, 56, 123456789, time.UTC),
			want: "2026-05-03T12:34:56.123456+00:00",
		},
	}
	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			assert.Equal(t, tc.want, FormatRFC3339UTC(tc.ts))
		})
	}
}
