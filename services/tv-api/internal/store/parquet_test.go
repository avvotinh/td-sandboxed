package store

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/parquet-go/parquet-go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// makeBars produces n synthetic ascending-time OHLCV rows for tests.
func makeBars(n int) []BarRow {
	out := make([]BarRow, n)
	const startMs int64 = 1_700_000_000_000
	const stepMs int64 = 5 * 60_000 // M5 cadence
	for i := 0; i < n; i++ {
		t := startMs + int64(i)*stepMs
		out[i] = BarRow{
			Time:   t,
			Open:   100.0 + float64(i),
			High:   100.5 + float64(i),
			Low:    99.5 + float64(i),
			Close:  100.2 + float64(i),
			Volume: 10.0,
		}
	}
	return out
}

func readParquetBars(t *testing.T, path string) []BarRow {
	t.Helper()
	f, err := os.Open(path)
	require.NoError(t, err)
	defer f.Close()
	stat, err := f.Stat()
	require.NoError(t, err)
	pf, err := parquet.OpenFile(f, stat.Size())
	require.NoError(t, err)

	rows := make([]BarRow, 0)
	reader := parquet.NewGenericReader[BarRow](pf)
	defer reader.Close()
	buf := make([]BarRow, 1024)
	for {
		n, err := reader.Read(buf)
		if n > 0 {
			rows = append(rows, buf[:n]...)
		}
		if err != nil {
			break
		}
	}
	return rows
}

// TestParquetWriter_RoundTrip writes 1000 rows, atomic-renames on close,
// then reads them back and asserts exact equality + .tmp absence.
func TestParquetWriter_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bars.parquet")

	w, err := NewParquetWriter(path)
	require.NoError(t, err)

	rows := makeBars(1000)
	require.NoError(t, w.WriteBars(rows))
	require.NoError(t, w.Close())

	// .tmp must be gone, final must exist.
	_, err = os.Stat(path + ".tmp")
	assert.True(t, os.IsNotExist(err), "tmp file should be removed after Close")
	_, err = os.Stat(path)
	require.NoError(t, err, "final file must exist")

	got := readParquetBars(t, path)
	require.Len(t, got, len(rows))
	for i := range rows {
		assert.Equal(t, rows[i], got[i], "row %d", i)
	}
}

// TestParquetWriter_AbortDropsTemp confirms that Abort removes the tmp
// file and leaves no trace at the final path.
func TestParquetWriter_AbortDropsTemp(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bars.parquet")

	w, err := NewParquetWriter(path)
	require.NoError(t, err)
	require.NoError(t, w.WriteBars(makeBars(10)))
	require.NoError(t, w.Abort())

	_, err = os.Stat(path + ".tmp")
	assert.True(t, os.IsNotExist(err), "tmp file should be removed after Abort")
	_, err = os.Stat(path)
	assert.True(t, os.IsNotExist(err), "final file must NOT exist after Abort")
}

// TestParquetWriter_TmpExistsBeforeClose asserts the tmp file lives
// during the write phase — important for crash-recovery reasoning
// (operator can grep for stale .tmp files).
func TestParquetWriter_TmpExistsBeforeClose(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bars.parquet")

	w, err := NewParquetWriter(path)
	require.NoError(t, err)
	defer w.Abort()

	require.NoError(t, w.WriteBars(makeBars(10)))

	_, err = os.Stat(path + ".tmp")
	require.NoError(t, err, "tmp file must exist while writer is open")
}

// TestParquetWriter_RejectsAfterClose ensures double-close is no-op and
// writes after close fail loudly.
func TestParquetWriter_RejectsAfterClose(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bars.parquet")

	w, err := NewParquetWriter(path)
	require.NoError(t, err)
	require.NoError(t, w.WriteBars(makeBars(5)))
	require.NoError(t, w.Close())

	// Idempotent close
	assert.NoError(t, w.Close())

	// Write after close errors
	err = w.WriteBars(makeBars(1))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "closed")
}

// TestParquetWriter_EmptyPathRejected covers input validation.
func TestParquetWriter_EmptyPathRejected(t *testing.T) {
	_, err := NewParquetWriter("")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "path is required")
}

// TestParquetWriter_CompressionShrinksFile asserts Snappy actually
// compresses (a sanity check that the codec wires through).
func TestParquetWriter_CompressionShrinksFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bars.parquet")

	w, err := NewParquetWriter(path)
	require.NoError(t, err)
	require.NoError(t, w.WriteBars(makeBars(10000)))
	require.NoError(t, w.Close())

	stat, err := os.Stat(path)
	require.NoError(t, err)
	// 10K rows × 6 fields × 8 bytes = 480 KB raw; compressed should be
	// substantially smaller than that. Generous bound to avoid flakes.
	assert.Less(t, stat.Size(), int64(400_000), "snappy-compressed parquet should shrink monotonic OHLCV data")
}
