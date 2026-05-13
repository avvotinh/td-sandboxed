// Package store — Parquet writer for backtest historical bars.
//
// Story 12.7.0b: produces a single-file Snappy-compressed Parquet shard
// per (symbol, timeframe, window) tuple, paired with a JSON sidecar
// manifest (see manifest.go) that mirrors the Python DatasetEntry schema.
// The writer is deliberately small: stream rows in row groups, atomic
// rename on close, drop the temp file on abort. Cross-language artefact
// is the only contract — trading-engine reads what tv-api wrote.
package store

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/parquet-go/parquet-go"
	"github.com/parquet-go/parquet-go/compress"
	"github.com/parquet-go/parquet-go/compress/snappy"
)

// BarRow is the on-disk row schema for a single OHLCV candle. Column
// names and types must match what `pandas.read_parquet` (via pyarrow) is
// happy to round-trip; the trading-engine adapter converts Time
// (Unix-millisecond int64) to a tz-aware datetime.
type BarRow struct {
	Time   int64   `parquet:"time"` // Unix milliseconds, UTC
	Open   float64 `parquet:"open"`
	High   float64 `parquet:"high"`
	Low    float64 `parquet:"low"`
	Close  float64 `parquet:"close"`
	Volume float64 `parquet:"volume"`
}

// ParquetOption configures a ParquetWriter at construction time.
type ParquetOption func(*parquetConfig)

type parquetConfig struct {
	rowGroupSize int
	compression  compress.Codec
}

func defaultParquetConfig() parquetConfig {
	return parquetConfig{
		rowGroupSize: 8192,
		compression:  &snappy.Codec{},
	}
}

// WithRowGroupSize sets the maximum rows per row group. 8192 is a sane
// default for sub-100K-bar fetches; larger groups reduce overhead but
// increase memory while writing.
func WithRowGroupSize(n int) ParquetOption {
	return func(c *parquetConfig) {
		if n > 0 {
			c.rowGroupSize = n
		}
	}
}

// WithCompression overrides the default Snappy codec. Snappy is the right
// choice for backtest data because it round-trips through pyarrow without
// extra dependencies and the compute cost is negligible.
func WithCompression(codec compress.Codec) ParquetOption {
	return func(c *parquetConfig) {
		if codec != nil {
			c.compression = codec
		}
	}
}

// ParquetWriter streams BarRow records to disk and atomically renames the
// temp file to the final path on Close. A failed Close (or explicit Abort
// before Close) deletes the temp file so partial Parquet shards never
// leak — the manifest fingerprint depends on the full row set so a
// half-written file is always wrong, never recoverable.
type ParquetWriter struct {
	finalPath string
	tmpPath   string
	file      *os.File
	gw        *parquet.GenericWriter[BarRow]
	closed    bool
	aborted   bool
}

// NewParquetWriter opens <path>.tmp for writing and prepares the row
// group writer. The destination directory is created if absent.
func NewParquetWriter(path string, opts ...ParquetOption) (*ParquetWriter, error) {
	if path == "" {
		return nil, fmt.Errorf("NewParquetWriter: path is required")
	}

	cfg := defaultParquetConfig()
	for _, opt := range opts {
		opt(&cfg)
	}

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("NewParquetWriter: mkdir %q: %w", filepath.Dir(path), err)
	}

	tmpPath := path + ".tmp"
	f, err := os.Create(tmpPath)
	if err != nil {
		return nil, fmt.Errorf("NewParquetWriter: create %q: %w", tmpPath, err)
	}

	gw := parquet.NewGenericWriter[BarRow](f,
		parquet.Compression(cfg.compression),
		parquet.MaxRowsPerRowGroup(int64(cfg.rowGroupSize)),
	)

	return &ParquetWriter{
		finalPath: path,
		tmpPath:   tmpPath,
		file:      f,
		gw:        gw,
	}, nil
}

// WriteBars appends a slice of rows to the current row group. May be
// called repeatedly; the writer flushes implicitly when row group size
// is reached.
func (w *ParquetWriter) WriteBars(rows []BarRow) error {
	if w.closed {
		return fmt.Errorf("WriteBars: writer is closed")
	}
	if w.aborted {
		return fmt.Errorf("WriteBars: writer is aborted")
	}
	if len(rows) == 0 {
		return nil
	}
	if _, err := w.gw.Write(rows); err != nil {
		return fmt.Errorf("WriteBars: parquet write %d rows: %w", len(rows), err)
	}
	return nil
}

// Close flushes the writer, fsyncs the temp file, closes the file
// handle, and atomically renames .tmp → final path. Idempotent: a second
// Close after success is a no-op.
func (w *ParquetWriter) Close() error {
	if w.closed {
		return nil
	}
	if w.aborted {
		return fmt.Errorf("Close: writer was aborted")
	}

	if err := w.gw.Close(); err != nil {
		w.file.Close()
		_ = os.Remove(w.tmpPath)
		return fmt.Errorf("Close: parquet writer close: %w", err)
	}

	if err := w.file.Sync(); err != nil {
		w.file.Close()
		_ = os.Remove(w.tmpPath)
		return fmt.Errorf("Close: fsync %q: %w", w.tmpPath, err)
	}

	if err := w.file.Close(); err != nil {
		_ = os.Remove(w.tmpPath)
		return fmt.Errorf("Close: close %q: %w", w.tmpPath, err)
	}

	if err := os.Rename(w.tmpPath, w.finalPath); err != nil {
		_ = os.Remove(w.tmpPath)
		return fmt.Errorf("Close: rename %q -> %q: %w", w.tmpPath, w.finalPath, err)
	}

	w.closed = true
	return nil
}

// Abort discards the temp file without renaming it. Safe to defer — a
// no-op when Close has already succeeded.
func (w *ParquetWriter) Abort() error {
	if w.closed || w.aborted {
		return nil
	}
	w.aborted = true
	_ = w.gw.Close()
	_ = w.file.Close()
	if err := os.Remove(w.tmpPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("Abort: remove %q: %w", w.tmpPath, err)
	}
	return nil
}
