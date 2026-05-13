// backtest-fetch command — bulk historical OHLCV download for Epic 12.
//
// Walks the FakeReplay anchor (TradingView free-tier) backward from
// `--to` until `--from` is reached, writes a single Parquet file with
// matching JSON sidecar manifest. Output schema is contractually pinned
// to the Python trading-engine DatasetEntry; see internal/store/manifest.go.
package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"sort"
	"time"

	"github.com/avvotinh/tv-api/internal/store"
	"github.com/avvotinh/tv-api/pkg/tradingview"
)

// backtestFetchSession is the slice of *tradingview.ChartSession the
// command depends on. Defining it here keeps unit tests free of a real
// WebSocket while the production code path still goes through the
// concrete public API.
type backtestFetchSession interface {
	SetMarket(symbol string, options *tradingview.ChartSessionOptions) error
	FetchRange(ctx context.Context, fromTs, toTs int64, opts ...tradingview.FetchOption) ([]*tradingview.Period, error)
	FetchHistoricalReplay(ctx context.Context, fromTs, toTs int64, opts ...tradingview.FetchOption) ([]*tradingview.Period, error)
	Delete() error
}

// requiresReplayMode returns true for timeframes the free-tier
// FakeReplay path cannot serve — daily, weekly, monthly. Premium
// ReplayMode (story 12.7.0e) is the only way to bulk-fetch these.
//
// TradingView accepts both "D" and "1D" (and the lower-case variants)
// for the same daily timeframe; the switch enumerates each form
// explicitly rather than normalising so the table stays self-documenting.
func requiresReplayMode(timeframe string) bool {
	switch timeframe {
	case "D", "1D", "d", "1d",
		"W", "1W", "w", "1w",
		"M", "1M", "m", "1m":
		return true
	}
	return false
}

// barWriter mirrors the methods runBacktestFetch needs from
// store.ParquetWriter — same interface-vs-mock motivation.
type barWriter interface {
	WriteBars(rows []store.BarRow) error
	Close() error
	Abort() error
}

// backtestFetchConfig is the parsed/validated form of the CLI flags.
// Pure value type → easy to unit-test the parser without spinning a
// client.
type backtestFetchConfig struct {
	Symbol          string
	Timeframe       string
	From            time.Time
	To              time.Time
	Out             string
	SpecName        string
	DatasetVersion  string
	WindowName      string
	WindowKind      string
	Throttle        time.Duration
	BatchSize       int
	MaxGapHours     float64
	MaxBatches      int
	ForceReplay     bool
	ResponseTimeout time.Duration
}

// backtestFetchDeps wires the I/O seams runBacktestFetch needs. The
// production path uses real client + parquet writer; tests pass stubs.
type backtestFetchDeps struct {
	NewSession func() backtestFetchSession
	NewWriter  func(path string) (barWriter, error)
	Now        func() time.Time
	Stdout     io.Writer
}

// parseBacktestFetchFlags converts the global flag values into a
// validated config. Returned errors are user-facing — the caller
// surfaces them via os.Stderr.
func parseBacktestFetchFlags() (backtestFetchConfig, error) {
	if *symbol == "" {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -symbol is required")
	}
	if *timeframe == "" {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -timeframe is required")
	}
	if *bfFrom == "" {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -from is required (RFC3339 UTC, e.g. 2024-01-01T00:00:00Z)")
	}
	if *bfTo == "" {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -to is required (RFC3339 UTC)")
	}
	if *bfOut == "" {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -out is required")
	}

	from, err := time.Parse(time.RFC3339, *bfFrom)
	if err != nil {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: parse -from %q: %w", *bfFrom, err)
	}
	to, err := time.Parse(time.RFC3339, *bfTo)
	if err != nil {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: parse -to %q: %w", *bfTo, err)
	}
	if !from.Before(to) {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -from (%s) must be strictly before -to (%s)", from, to)
	}
	if *bfWindowKind != "in_sample" && *bfWindowKind != "oos_reserve" {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -window-kind must be in_sample or oos_reserve, got %q", *bfWindowKind)
	}
	if *bfBatchSize <= 0 || *bfBatchSize > 5000 {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -batch-size must be in (0, 5000], got %d", *bfBatchSize)
	}
	if *bfThrottleMs < 0 {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -throttle-ms must be ≥ 0, got %d", *bfThrottleMs)
	}
	if *bfMaxBatches <= 0 {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -max-batches must be > 0, got %d", *bfMaxBatches)
	}
	if *bfResponseTimeoutMs <= 0 {
		return backtestFetchConfig{}, fmt.Errorf("backtest-fetch: -response-timeout-ms must be > 0, got %d", *bfResponseTimeoutMs)
	}

	return backtestFetchConfig{
		Symbol:          *symbol,
		Timeframe:       *timeframe,
		From:            from.UTC(),
		To:              to.UTC(),
		Out:             *bfOut,
		SpecName:        *bfSpecName,
		DatasetVersion:  *bfDatasetVersion,
		WindowName:      *bfWindowName,
		WindowKind:      *bfWindowKind,
		Throttle:        time.Duration(*bfThrottleMs) * time.Millisecond,
		BatchSize:       *bfBatchSize,
		MaxGapHours:     *bfMaxGapHours,
		MaxBatches:      *bfMaxBatches,
		ForceReplay:     *bfReplayMode,
		ResponseTimeout: time.Duration(*bfResponseTimeoutMs) * time.Millisecond,
	}, nil
}

// runBacktestFetch is the entry point invoked by main.run when -command
// is "backtest-fetch". It composes production deps and delegates to
// fetchAndWrite for the testable core.
func runBacktestFetch(ctx context.Context, client *tradingview.Client) error {
	cfg, err := parseBacktestFetchFlags()
	if err != nil {
		return err
	}
	deps := backtestFetchDeps{
		NewSession: func() backtestFetchSession { return client.NewChartSession() },
		NewWriter: func(path string) (barWriter, error) {
			return store.NewParquetWriter(path)
		},
		Now:    time.Now,
		Stdout: os.Stdout,
	}
	return fetchAndWrite(ctx, cfg, deps)
}

// fetchAndWrite runs the full campaign: open session, fetch range, write
// Parquet, compute manifest, write sidecar, print summary. Errors trigger
// best-effort cleanup of the temp Parquet file via writer.Abort.
func fetchAndWrite(ctx context.Context, cfg backtestFetchConfig, deps backtestFetchDeps) error {
	started := deps.Now()

	sess := deps.NewSession()
	defer func() { _ = sess.Delete() }()

	useReplay := cfg.ForceReplay || requiresReplayMode(cfg.Timeframe)

	var setMarketOpts *tradingview.ChartSessionOptions
	if useReplay {
		setMarketOpts = &tradingview.ChartSessionOptions{
			Timeframe:       cfg.Timeframe,
			ReplayStartFrom: cfg.To.Unix(),
		}
	} else {
		setMarketOpts = &tradingview.ChartSessionOptions{
			Timeframe: cfg.Timeframe,
			To:        cfg.To.Unix(),
		}
	}

	if err := sess.SetMarket(cfg.Symbol, setMarketOpts); err != nil {
		return fmt.Errorf("backtest-fetch: SetMarket: %w", err)
	}

	fetchOpts := []tradingview.FetchOption{
		tradingview.WithBatchSize(cfg.BatchSize),
		tradingview.WithThrottle(cfg.Throttle),
		tradingview.WithMaxBatches(cfg.MaxBatches),
		tradingview.WithResponseTimeout(cfg.ResponseTimeout),
	}

	var periods []*tradingview.Period
	var err error
	if useReplay {
		periods, err = sess.FetchHistoricalReplay(ctx, cfg.From.Unix(), cfg.To.Unix(), fetchOpts...)
		if err != nil {
			return fmt.Errorf("backtest-fetch: FetchHistoricalReplay: %w", err)
		}
	} else {
		periods, err = sess.FetchRange(ctx, cfg.From.Unix(), cfg.To.Unix(), fetchOpts...)
		if err != nil {
			return fmt.Errorf("backtest-fetch: FetchRange: %w", err)
		}
	}
	if len(periods) == 0 {
		mode := "FakeReplay"
		if useReplay {
			mode = "ReplayMode"
		}
		return fmt.Errorf("backtest-fetch (%s): zero bars in [%s, %s] — likely symbol-feed mismatch or premium-account entitlement missing", mode, cfg.From, cfg.To)
	}

	rows := convertPeriodsToBarRows(periods)

	w, err := deps.NewWriter(cfg.Out)
	if err != nil {
		return fmt.Errorf("backtest-fetch: open writer: %w", err)
	}
	abortNeeded := true
	defer func() {
		if abortNeeded {
			_ = w.Abort()
		}
	}()

	if err := w.WriteBars(rows); err != nil {
		return fmt.Errorf("backtest-fetch: write bars: %w", err)
	}
	if err := w.Close(); err != nil {
		return fmt.Errorf("backtest-fetch: close writer: %w", err)
	}
	abortNeeded = false

	fp := store.ComputeFingerprint(rows)
	gaps := store.DetectGaps(rows, cfg.Timeframe, cfg.WindowName, cfg.MaxGapHours)

	manifest := store.DatasetManifest{
		SchemaVersion:  store.ManifestSchemaVersion,
		SpecName:       cfg.SpecName,
		DatasetVersion: cfg.DatasetVersion,
		Symbol:         deriveSymbolKey(cfg.Symbol),
		GeneratedAt:    store.FormatRFC3339UTC(deps.Now()),
		MaxGapHours:    cfg.MaxGapHours,
		Entries: []store.DatasetEntry{
			{
				Timeframe:   cfg.Timeframe,
				WindowName:  cfg.WindowName,
				WindowKind:  cfg.WindowKind,
				Start:       store.FormatRFC3339UTC(cfg.From),
				End:         store.FormatRFC3339UTC(cfg.To),
				ParquetPath: cfg.Out,
				Fingerprint: fp,
				RowCount:    len(rows),
				Gaps:        gaps,
			},
		},
	}

	manifestPath := cfg.Out + ".manifest.json"
	if err := store.WriteManifest(manifestPath, manifest); err != nil {
		return fmt.Errorf("backtest-fetch: write manifest: %w", err)
	}

	duration := deps.Now().Sub(started)
	printBacktestFetchSummary(deps.Stdout, cfg, fp, len(rows), len(gaps), gapMaxHours(gaps), duration, manifestPath)
	return nil
}

// convertPeriodsToBarRows converts tv-api Periods (Time as Unix seconds)
// into store.BarRow (Time as Unix milliseconds, ascending order). The
// ascending sort is the precondition ComputeFingerprint and DetectGaps
// rely on.
func convertPeriodsToBarRows(periods []*tradingview.Period) []store.BarRow {
	rows := make([]store.BarRow, 0, len(periods))
	for _, p := range periods {
		rows = append(rows, store.BarRow{
			Time:   p.Time * 1000, // s → ms
			Open:   p.Open,
			High:   p.High,
			Low:    p.Low,
			Close:  p.Close,
			Volume: p.Volume,
		})
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].Time < rows[j].Time })
	return rows
}

// deriveSymbolKey strips the EXCHANGE: prefix used by TradingView so the
// manifest's `symbol` field carries the bare ticker — matching what
// configs/datasets/*.yaml uses ("XAUUSD", not "OANDA:XAUUSD").
func deriveSymbolKey(symbol string) string {
	for i := 0; i < len(symbol); i++ {
		if symbol[i] == ':' {
			return symbol[i+1:]
		}
	}
	return symbol
}

// gapMaxHours returns the largest gap duration in hours from the gap
// list, 0 when no gaps were detected.
func gapMaxHours(gaps []store.BarGap) float64 {
	var peak float64
	for _, g := range gaps {
		if g.DurationHours > peak {
			peak = g.DurationHours
		}
	}
	return peak
}

func printBacktestFetchSummary(out io.Writer, cfg backtestFetchConfig, fp store.Fingerprint, rowCount, gapCount int, maxGapHours float64, duration time.Duration, manifestPath string) {
	if out == nil {
		return
	}
	fmt.Fprintf(out, "backtest-fetch: %s %s [%s, %s]\n",
		cfg.Symbol, cfg.Timeframe,
		cfg.From.Format(time.RFC3339),
		cfg.To.Format(time.RFC3339))
	fmt.Fprintf(out, "  bars=%d  fingerprint=%s  gaps=%d  max_gap_hours=%.2f\n",
		rowCount, fp.Sha256Short, gapCount, maxGapHours)
	fmt.Fprintf(out, "  parquet=%s\n", cfg.Out)
	fmt.Fprintf(out, "  manifest=%s\n", manifestPath)
	fmt.Fprintf(out, "  elapsed=%s\n", duration.Round(time.Millisecond))
}
