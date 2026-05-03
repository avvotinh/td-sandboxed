package main

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/avvotinh/tv-api/internal/store"
	"github.com/avvotinh/tv-api/pkg/tradingview"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// stubSession captures SetMarket/FetchRange calls and returns canned bars.
type stubSession struct {
	setMarketErr  error
	fetchRangeErr error
	periods       []*tradingview.Period

	setMarketArgs *tradingview.ChartSessionOptions
	fetchedFrom   int64
	fetchedTo     int64
	deleted       bool
}

func (s *stubSession) SetMarket(symbol string, options *tradingview.ChartSessionOptions) error {
	s.setMarketArgs = options
	return s.setMarketErr
}

func (s *stubSession) FetchRange(_ context.Context, fromTs, toTs int64, _ ...tradingview.FetchOption) ([]*tradingview.Period, error) {
	s.fetchedFrom = fromTs
	s.fetchedTo = toTs
	return s.periods, s.fetchRangeErr
}

func (s *stubSession) Delete() error {
	s.deleted = true
	return nil
}

// stubWriter records calls to a barWriter for assertion.
type stubWriter struct {
	rows         []store.BarRow
	closed       bool
	aborted      bool
	writeErr     error
	closeErr     error
	abortReturns error
}

func (w *stubWriter) WriteBars(rows []store.BarRow) error {
	if w.writeErr != nil {
		return w.writeErr
	}
	w.rows = append(w.rows, rows...)
	return nil
}

func (w *stubWriter) Close() error {
	if w.closeErr != nil {
		return w.closeErr
	}
	w.closed = true
	return nil
}

func (w *stubWriter) Abort() error {
	w.aborted = true
	return w.abortReturns
}

// TestParseBacktestFetchFlags covers the validation surface — every
// failure path operators are likely to hit.
func TestParseBacktestFetchFlags(t *testing.T) {
	cases := []struct {
		name    string
		setup   func()
		wantErr string
	}{
		{
			name:    "missing_from",
			setup:   func() { *bfFrom = ""; *bfTo = "2026-01-01T00:00:00Z"; *bfOut = "/tmp/x.parquet" },
			wantErr: "-from is required",
		},
		{
			name:    "missing_to",
			setup:   func() { *bfFrom = "2024-01-01T00:00:00Z"; *bfTo = ""; *bfOut = "/tmp/x.parquet" },
			wantErr: "-to is required",
		},
		{
			name:    "missing_out",
			setup:   func() { *bfFrom = "2024-01-01T00:00:00Z"; *bfTo = "2026-01-01T00:00:00Z"; *bfOut = "" },
			wantErr: "-out is required",
		},
		{
			name:    "from_after_to",
			setup:   func() { *bfFrom = "2026-01-01T00:00:00Z"; *bfTo = "2024-01-01T00:00:00Z"; *bfOut = "/tmp/x.parquet" },
			wantErr: "must be strictly before",
		},
		{
			name:    "bad_from_format",
			setup:   func() { *bfFrom = "yesterday"; *bfTo = "2026-01-01T00:00:00Z"; *bfOut = "/tmp/x.parquet" },
			wantErr: "parse -from",
		},
		{
			name: "invalid_window_kind",
			setup: func() {
				*bfFrom = "2024-01-01T00:00:00Z"
				*bfTo = "2026-01-01T00:00:00Z"
				*bfOut = "/tmp/x.parquet"
				*bfWindowKind = "bad"
			},
			wantErr: "window-kind",
		},
		{
			name: "batch_size_too_large",
			setup: func() {
				*bfFrom = "2024-01-01T00:00:00Z"
				*bfTo = "2026-01-01T00:00:00Z"
				*bfOut = "/tmp/x.parquet"
				*bfWindowKind = "in_sample"
				*bfBatchSize = 6000
			},
			wantErr: "batch-size",
		},
		{
			name: "negative_throttle",
			setup: func() {
				*bfFrom = "2024-01-01T00:00:00Z"
				*bfTo = "2026-01-01T00:00:00Z"
				*bfOut = "/tmp/x.parquet"
				*bfWindowKind = "in_sample"
				*bfBatchSize = 1000
				*bfThrottleMs = -10
			},
			wantErr: "throttle-ms",
		},
		{
			name: "zero_max_batches",
			setup: func() {
				*bfFrom = "2024-01-01T00:00:00Z"
				*bfTo = "2026-01-01T00:00:00Z"
				*bfOut = "/tmp/x.parquet"
				*bfWindowKind = "in_sample"
				*bfBatchSize = 1000
				*bfThrottleMs = 150
				*bfMaxBatches = 0
			},
			wantErr: "max-batches",
		},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			resetGlobalFlags()
			tc.setup()
			_, err := parseBacktestFetchFlags()
			require.Error(t, err)
			assert.Contains(t, err.Error(), tc.wantErr)
		})
	}
}

// TestParseBacktestFetchFlags_Happy verifies a fully-populated valid
// flag set parses cleanly with the expected derived fields.
func TestParseBacktestFetchFlags_Happy(t *testing.T) {
	resetGlobalFlags()
	*symbol = "OANDA:XAUUSD"
	*timeframe = "5"
	*bfFrom = "2024-01-01T00:00:00Z"
	*bfTo = "2026-04-30T23:59:59Z"
	*bfOut = "/tmp/xauusd.parquet"
	*bfWindowKind = "in_sample"
	*bfBatchSize = 1500
	*bfThrottleMs = 250

	cfg, err := parseBacktestFetchFlags()
	require.NoError(t, err)
	assert.Equal(t, "OANDA:XAUUSD", cfg.Symbol)
	assert.Equal(t, "5", cfg.Timeframe)
	assert.Equal(t, time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC), cfg.From)
	assert.Equal(t, time.Date(2026, 4, 30, 23, 59, 59, 0, time.UTC), cfg.To)
	assert.Equal(t, "/tmp/xauusd.parquet", cfg.Out)
	assert.Equal(t, "in_sample", cfg.WindowKind)
	assert.Equal(t, 1500, cfg.BatchSize)
	assert.Equal(t, 250*time.Millisecond, cfg.Throttle)
}

// TestConvertPeriodsToBarRows verifies the (s → ms) timestamp scaling +
// ascending sort that ComputeFingerprint relies on.
func TestConvertPeriodsToBarRows(t *testing.T) {
	periods := []*tradingview.Period{
		{Time: 1700000300, Open: 2, High: 3, Low: 1, Close: 2.5, Volume: 100},
		{Time: 1700000000, Open: 1, High: 2, Low: 0.5, Close: 1.5, Volume: 50},
		{Time: 1700000600, Open: 3, High: 4, Low: 2.5, Close: 3.5, Volume: 200},
	}

	rows := convertPeriodsToBarRows(periods)
	require.Len(t, rows, 3)
	assert.Equal(t, int64(1700000000_000), rows[0].Time, "ms scaling + ascending order")
	assert.Equal(t, int64(1700000300_000), rows[1].Time)
	assert.Equal(t, int64(1700000600_000), rows[2].Time)
	assert.Equal(t, 1.5, rows[0].Close, "OHLC fields preserved")
}

// TestDeriveSymbolKey checks the EXCHANGE: prefix-stripping that keeps
// the manifest aligned with configs/datasets/*.yaml ticker shorthand.
func TestDeriveSymbolKey(t *testing.T) {
	cases := map[string]string{
		"OANDA:XAUUSD":    "XAUUSD",
		"BINANCE:BTCUSDT": "BTCUSDT",
		"NASDAQ:AAPL":     "AAPL",
		"XAUUSD":          "XAUUSD",  // no colon
		"FOREX:GBP:USD":   "GBP:USD", // first colon only
	}
	for in, want := range cases {
		assert.Equal(t, want, deriveSymbolKey(in), in)
	}
}

// TestFetchAndWrite_HappyPath drives the full workflow with stubs and
// asserts: bars written, manifest sidecar emitted, summary printed,
// session deleted, no abort triggered.
func TestFetchAndWrite_HappyPath(t *testing.T) {
	dir := t.TempDir()
	out := filepath.Join(dir, "smoke.parquet")

	periods := []*tradingview.Period{
		{Time: 1700000000, Open: 1, High: 2, Low: 0.5, Close: 1.5, Volume: 10},
		{Time: 1700000300, Open: 1.5, High: 2.5, Low: 1, Close: 2, Volume: 20},
		{Time: 1700000600, Open: 2, High: 3, Low: 1.5, Close: 2.5, Volume: 30},
	}
	sess := &stubSession{periods: periods}

	cfg := backtestFetchConfig{
		Symbol:         "OANDA:XAUUSD",
		Timeframe:      "5",
		From:           time.Date(2023, 11, 14, 0, 0, 0, 0, time.UTC),
		To:             time.Date(2023, 11, 14, 23, 59, 59, 0, time.UTC),
		Out:            out,
		SpecName:       "smoke",
		DatasetVersion: "v1",
		WindowName:     "in_sample",
		WindowKind:     "in_sample",
		BatchSize:      1000,
		Throttle:       0,
		MaxGapHours:    48.0,
		MaxBatches:     100,
	}

	stdout := &bytes.Buffer{}
	now := time.Date(2026, 5, 3, 12, 0, 0, 0, time.UTC)
	deps := backtestFetchDeps{
		NewSession: func() backtestFetchSession { return sess },
		NewWriter:  func(path string) (barWriter, error) { return store.NewParquetWriter(path) },
		Now:        func() time.Time { return now },
		Stdout:     stdout,
	}

	require.NoError(t, fetchAndWrite(context.Background(), cfg, deps))

	// Session called and torn down.
	require.NotNil(t, sess.setMarketArgs)
	assert.Equal(t, cfg.To.Unix(), sess.setMarketArgs.To, "SetMarket must propagate the To anchor")
	assert.Equal(t, cfg.From.Unix(), sess.fetchedFrom)
	assert.Equal(t, cfg.To.Unix(), sess.fetchedTo)
	assert.True(t, sess.deleted)

	// Parquet file produced.
	stat, err := os.Stat(out)
	require.NoError(t, err)
	assert.Greater(t, stat.Size(), int64(0))

	// Manifest sidecar produced and parses with our manifest types.
	manifestRaw, err := os.ReadFile(out + ".manifest.json")
	require.NoError(t, err)
	assert.Contains(t, string(manifestRaw), "\"symbol\": \"XAUUSD\"")
	assert.Contains(t, string(manifestRaw), "\"row_count\": 3")
	assert.Contains(t, string(manifestRaw), "\"window_kind\": \"in_sample\"")

	// Summary printed.
	assert.Contains(t, stdout.String(), "bars=3")
	assert.Contains(t, stdout.String(), "fingerprint=")
}

// TestFetchAndWrite_ZeroBarsErrors documents the explicit failure when
// the symbol returns no data — typically a daily-timeframe + intraday-
// only symbol mismatch.
func TestFetchAndWrite_ZeroBarsErrors(t *testing.T) {
	cfg := backtestFetchConfig{
		Symbol:    "OANDA:XAUUSD",
		Timeframe: "5",
		From:      time.Date(2023, 11, 14, 0, 0, 0, 0, time.UTC),
		To:        time.Date(2023, 11, 14, 1, 0, 0, 0, time.UTC),
		Out:       filepath.Join(t.TempDir(), "empty.parquet"),
		BatchSize: 1000,
	}
	deps := backtestFetchDeps{
		NewSession: func() backtestFetchSession { return &stubSession{periods: nil} },
		NewWriter:  func(path string) (barWriter, error) { return store.NewParquetWriter(path) },
		Now:        time.Now,
	}
	err := fetchAndWrite(context.Background(), cfg, deps)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "zero bars")
}

// TestFetchAndWrite_AbortOnWriteFailure ensures partial Parquet files
// are dropped when WriteBars fails — fingerprint-mismatched shards must
// never linger on disk.
func TestFetchAndWrite_AbortOnWriteFailure(t *testing.T) {
	cfg := backtestFetchConfig{
		Symbol:    "OANDA:XAUUSD",
		Timeframe: "5",
		From:      time.Date(2023, 11, 14, 0, 0, 0, 0, time.UTC),
		To:        time.Date(2023, 11, 14, 1, 0, 0, 0, time.UTC),
		Out:       filepath.Join(t.TempDir(), "never-rendered.parquet"),
		BatchSize: 1000,
	}
	periods := []*tradingview.Period{{Time: 1700000000, Close: 1.0}}
	w := &stubWriter{writeErr: errors.New("disk full")}

	deps := backtestFetchDeps{
		NewSession: func() backtestFetchSession { return &stubSession{periods: periods} },
		NewWriter:  func(path string) (barWriter, error) { return w, nil },
		Now:        time.Now,
	}
	err := fetchAndWrite(context.Background(), cfg, deps)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "write bars")
	assert.True(t, w.aborted, "writer must be aborted when WriteBars fails")
	assert.False(t, w.closed)
}

// TestFetchAndWrite_FetchRangeErrorPropagates checks that downstream
// errors from the FakeReplay walk surface with batch context preserved.
func TestFetchAndWrite_FetchRangeErrorPropagates(t *testing.T) {
	cfg := backtestFetchConfig{
		Symbol:    "OANDA:XAUUSD",
		Timeframe: "5",
		From:      time.Date(2023, 11, 14, 0, 0, 0, 0, time.UTC),
		To:        time.Date(2023, 11, 14, 1, 0, 0, 0, time.UTC),
		Out:       filepath.Join(t.TempDir(), "x.parquet"),
	}
	deps := backtestFetchDeps{
		NewSession: func() backtestFetchSession {
			return &stubSession{fetchRangeErr: errors.New("websocket broken")}
		},
		NewWriter: func(path string) (barWriter, error) { return store.NewParquetWriter(path) },
		Now:       time.Now,
	}
	err := fetchAndWrite(context.Background(), cfg, deps)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "FetchRange")
	assert.Contains(t, err.Error(), "websocket broken")
}

// resetGlobalFlags is shared by parser tests — flag.* package vars are
// shared module state so tests must restore defaults to stay isolated.
func resetGlobalFlags() {
	*symbol = "OANDA:XAUUSD"
	*timeframe = "5"
	*bfFrom = ""
	*bfTo = ""
	*bfOut = ""
	*bfSpecName = "xauusd-validation"
	*bfDatasetVersion = "v1"
	*bfWindowName = "in_sample"
	*bfWindowKind = "in_sample"
	*bfThrottleMs = 150
	*bfBatchSize = 1000
	*bfMaxGapHours = 48.0
	*bfMaxBatches = 1000
}
