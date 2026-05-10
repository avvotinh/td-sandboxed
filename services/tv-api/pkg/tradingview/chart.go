package tradingview

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/avvotinh/tv-api/internal/session"
)

// ChartSessionOptions contains options for creating a chart session.
type ChartSessionOptions struct {
	// Timeframe is the chart timeframe (e.g., "1D", "1", "60")
	Timeframe string

	// Range is the number of bars to retrieve
	Range int

	// To is the FakeReplay anchor (Unix seconds). When set, SetMarket
	// activates the free-tier bar_count walk-backward path. Mutually
	// exclusive with ReplayStartFrom.
	To int64

	// Adjustment is the price adjustment type (e.g., "splits", "dividends")
	Adjustment string

	// Session is the trading session (e.g., "regular", "extended")
	Session string

	// Currency is the currency for price conversion
	Currency string

	// ReplayStartFrom activates premium ReplayMode (story 12.7.0e). When
	// set to a Unix-second timestamp, SetMarket performs the full
	// replay_create_session → replay_add_series → replay_reset →
	// resolve_symbol → create_series handshake. Requires SESSION_ID and
	// SESSION_SIGN cookies in the client config (free accounts have no
	// replay entitlement). Mutually exclusive with To.
	ReplayStartFrom int64

	// ReplayBars is the initial create_series range issued after the
	// replay handshake. Defaults to 300 when zero. Only consulted when
	// ReplayStartFrom > 0.
	ReplayBars int
}

// ChartSession represents a chart session for historical OHLCV data.
type ChartSession struct {
	client  *Client
	session *session.ChartSession
	symbol  string
	options *ChartSessionOptions
}

// NewChartSession creates a new chart session for retrieving historical OHLCV data.
// Use SetMarket to specify the symbol and timeframe for the chart data.
//
// A companion replay session (rs_*) is registered eagerly so callers can
// subscribe to OnReplayLoaded / OnReplayPoint / etc. before SetMarket
// kicks the handshake. The server only learns about the rs_* ID when
// SetMarket(opts.ReplayStartFrom > 0) runs, so the eager attachment has
// no wire cost for FakeReplay or live use.
func (c *Client) NewChartSession() *ChartSession {
	sess := session.NewChartSession(c)

	// Register chart session with client. RegisterSession only fails on
	// duplicate-ID collisions which are astronomically unlikely with
	// crypto/rand session IDs — but if the swallow happens, OnData never
	// routes for this session and the caller never receives a single bar.
	// Surface the failure via the client logger so silent breakage shows
	// up in production traces; keep the (*ChartSession) return signature
	// because changing it would ripple through every existing caller.
	if err := c.RegisterSession(sess); err != nil {
		c.logger.Error("failed to register chart session — inbound packets will not route",
			slog.String("session_id", sess.ID()),
			slog.Any("error", err))
	}

	// Eagerly create + register a paired replay session so OnReplayX
	// callbacks attach cleanly even before SetMarket activates replay.
	// A silent registration failure here is more dangerous than the
	// chart-session case because Step / Start / Stop ack channels will
	// hang forever — log loudly.
	rs := session.NewReplaySession(c)
	if err := c.RegisterSession(rs); err != nil {
		c.logger.Error("failed to register replay session — Step/Start/Stop acks will hang",
			slog.String("session_id", rs.ID()),
			slog.Any("error", err))
	}
	sess.AttachReplay(rs)

	return &ChartSession{
		client:  c,
		session: sess,
		options: &ChartSessionOptions{
			Timeframe:  "1D",
			Range:      300,
			Adjustment: "splits",
		},
	}
}

// NewChartSessionWithSymbol creates a new chart session and immediately sets up the market.
// This is a convenience function that combines NewChartSession and SetMarket.
// The symbol should be in the format "EXCHANGE:SYMBOL" (e.g., "NASDAQ:AAPL").
// Returns the chart session and the underlying session.Session for registration.
func NewChartSession(client *Client, symbol, timeframe string) (session.Session, error) {
	// Create internal chart session
	sess := session.NewChartSession(client)

	// Register session with client
	if err := client.RegisterSession(sess); err != nil {
		return nil, NewSessionError("failed to register chart session", err)
	}

	// Resolve symbol
	if err := sess.ResolveSymbol(symbol, "splits", "", ""); err != nil {
		return nil, NewSessionError("failed to resolve symbol", err)
	}

	// Create series with specified timeframe
	if err := sess.CreateSeries(timeframe, 300); err != nil {
		return nil, NewSessionError("failed to create series", err)
	}

	return sess, nil
}

// SetMarket sets the market symbol for the chart and begins loading historical data.
// The symbol should be in the format "EXCHANGE:SYMBOL" (e.g., "BINANCE:BTCUSDT").
// Use the OnUpdate callback to receive chart data updates.
//
// Three modes branch on the options struct:
//
//   - options.ReplayStartFrom > 0 → premium ReplayMode (intraday + D/W/M),
//     full replay_create_session handshake. Mutually exclusive with To.
//   - options.To > 0              → FakeReplay anchored fetch (free-tier,
//     intraday-only). Pair with FetchUntil / FetchRange to walk backward.
//   - otherwise                   → live tail.
func (cs *ChartSession) SetMarket(symbol string, options *ChartSessionOptions) error {
	cs.symbol = symbol

	if options != nil {
		cs.options = options
	}

	if cs.options.ReplayStartFrom > 0 && cs.options.To > 0 {
		return NewSessionError("ReplayStartFrom and To are mutually exclusive — pick FakeReplay (To) or premium Replay (ReplayStartFrom), not both", nil)
	}

	// Set defaults
	if cs.options.Timeframe == "" {
		cs.options.Timeframe = "1D"
	}
	if cs.options.Adjustment == "" {
		cs.options.Adjustment = "splits"
	}
	// Default range only for live (non-anchored) queries. FakeReplay accepts
	// negative ranges (walk-backward), so leaving Range == 0 here lets us
	// pick a sensible initial batch below.
	if cs.options.Range == 0 && cs.options.To == 0 && cs.options.ReplayStartFrom == 0 {
		cs.options.Range = 300
	}

	// Premium ReplayMode (story 12.7.0e): full handshake bundled in the
	// internal session helper so the wire-order matches JS upstream.
	if cs.options.ReplayStartFrom > 0 {
		bars := cs.options.ReplayBars
		if bars <= 0 {
			bars = 300
		}
		if err := cs.session.SetMarketWithReplay(
			symbol,
			cs.options.Timeframe,
			bars,
			cs.options.ReplayStartFrom,
			cs.options.Adjustment,
			cs.options.Session,
			cs.options.Currency,
		); err != nil {
			return NewSessionError("failed to set market in replay mode", err)
		}
		return nil
	}

	// Resolve symbol
	if err := cs.session.ResolveSymbol(symbol, cs.options.Adjustment, cs.options.Session, cs.options.Currency); err != nil {
		return NewSessionError("failed to resolve symbol", err)
	}

	if cs.options.To > 0 {
		rangeCount := cs.options.Range
		if rangeCount == 0 {
			// Positive count: TradingView's bar_count tuple semantic returns N
			// bars at-or-before the To anchor (walk backward). The JS reference
			// example used a negative literal but empirical testing against the
			// live server (2026-05-11) showed negative produces bars FORWARD
			// from the anchor — so a 4-hour FetchRange would land 1 bar after
			// the filter narrowed the FORWARD-walking batch. 1000 bars covers
			// ~3.5 days of M5 in the initial batch; FetchUntil pages further
			// back via request_more_data when the requested fromTs is older.
			rangeCount = 1000
		}
		cs.session.SetSubscriptionWithReference(symbol, cs.options.Timeframe, cs.options.To)
		if err := cs.session.CreateSeriesWithReference(cs.options.Timeframe, rangeCount, cs.options.To); err != nil {
			return NewSessionError("failed to create series with reference", err)
		}
		return nil
	}

	if err := cs.session.CreateSeries(cs.options.Timeframe, cs.options.Range); err != nil {
		return NewSessionError("failed to create series", err)
	}

	return nil
}

// SetSeries sets the timeframe and range for the chart.
func (cs *ChartSession) SetSeries(timeframe string, rangeCount int) error {
	cs.options.Timeframe = timeframe
	cs.options.Range = rangeCount

	// For simplicity, we'll modify the series
	// In practice, you might want to track series IDs
	return cs.session.ModifySeries("s1", timeframe, rangeCount)
}

// FetchMore fetches more historical data.
func (cs *ChartSession) FetchMore(count int) error {
	return cs.session.RequestMoreData("s1", count)
}

// SetTimezone changes the chart timezone.
func (cs *ChartSession) SetTimezone(timezone string) error {
	return cs.session.SwitchTimezone(timezone)
}

// Periods returns all chart periods sorted by time descending.
func (cs *ChartSession) Periods() []*Period {
	periods := cs.session.GetPeriods()
	result := make([]*Period, len(periods))
	for i, p := range periods {
		result[i] = &Period{
			Time:   p.Time,
			Open:   p.Open,
			Close:  p.Close,
			High:   p.High,
			Low:    p.Low,
			Volume: p.Volume,
		}
	}
	return result
}

// Infos returns market information.
func (cs *ChartSession) Infos() *MarketInfo {
	info := cs.session.GetMarketInfo()
	if info == nil {
		return nil
	}

	return &MarketInfo{
		Symbol:      info.Symbol,
		Exchange:    info.Exchange,
		FullName:    info.Symbol,
		Description: info.Description,
		Type:        info.Type,
		Currency:    info.Currency,
		Session:     info.Session,
		Timezone:    info.Timezone,
		PriceScale:  info.PriceScale,
		MinMove:     info.MinMove,
		HasIntraday: info.HasIntraday,
		HasDaily:    info.HasDaily,
		HasWeekly:   info.HasWeekly,
	}
}

// OnSymbolLoaded registers a callback for when symbol info is loaded.
func (cs *ChartSession) OnSymbolLoaded(callback func(*MarketInfo)) {
	cs.session.On("symbol_loaded", func(args ...interface{}) {
		if len(args) > 0 {
			if info, ok := args[0].(*session.MarketInfo); ok {
				callback(&MarketInfo{
					Symbol:      info.Symbol,
					Exchange:    info.Exchange,
					Description: info.Description,
					Type:        info.Type,
					Currency:    info.Currency,
					Timezone:    info.Timezone,
					Session:     info.Session,
				})
			}
		}
	})
}

// OnUpdate registers a callback for chart data updates.
// The callback receives the current list of periods sorted by time descending (newest first).
func (cs *ChartSession) OnUpdate(callback func([]*Period)) {
	cs.session.On("update", func(args ...interface{}) {
		callback(cs.Periods())
	})
}

// OnError registers a callback for errors.
func (cs *ChartSession) OnError(callback func(error)) {
	cs.session.On("error", func(args ...interface{}) {
		if len(args) > 0 {
			if err, ok := args[0].(error); ok {
				callback(err)
			}
		}
	})
}

// OnEvent registers a callback for generic events.
func (cs *ChartSession) OnEvent(callback func(eventType string, data interface{})) {
	cs.session.On("event", func(args ...interface{}) {
		if len(args) >= 2 {
			if eventType, ok := args[0].(string); ok {
				callback(eventType, args[1])
			}
		}
	})
}

// fetchSession is the small interface FetchUntil needs from the underlying
// session.ChartSession. Defined here to enable mock-based unit tests of the
// loop logic without spinning up a live WebSocket bridge.
type fetchSession interface {
	MinPeriodTime() int64
	RequestMoreData(seriesID string, count int) error
	SubscribeUpdate(buf int) (<-chan struct{}, func())
}

// FetchUntil walks backward through history one batch at a time until the
// session's smallest period timestamp is at-or-before untilTs. The caller
// must have invoked SetMarket with options.To set first; without an anchor
// the server interprets the request as a live tail and the walk never
// terminates.
//
// Stop conditions:
//   - min(period.Time) <= untilTs              ⇒ success.
//   - two consecutive batches with no new bars ⇒ terminal (server out of data).
//   - maxBatches reached                       ⇒ error (safety cap).
//   - ctx cancelled                            ⇒ error (wraps ctx.Err()).
func (cs *ChartSession) FetchUntil(ctx context.Context, untilTs int64, opts ...FetchOption) error {
	return fetchUntil(ctx, cs.session, untilTs, opts...)
}

// fetchUntil is the testable core of FetchUntil. It accepts the small
// fetchSession interface so unit tests can drive the loop with a stub.
func fetchUntil(ctx context.Context, sess fetchSession, untilTs int64, opts ...FetchOption) error {
	cfg := defaultFetchConfig()
	for _, opt := range opts {
		opt(&cfg)
	}

	updates, release := sess.SubscribeUpdate(16)
	defer release()

	waitForUpdate := func(d time.Duration) bool {
		select {
		case <-updates:
			return true
		case <-time.After(d):
			return false
		case <-ctx.Done():
			return false
		}
	}

	// Wait for the initial create_series batch to land before pumping
	// request_more_data — otherwise the server may drop subsequent calls
	// while still resolving the symbol.
	if sess.MinPeriodTime() == 0 {
		if !waitForUpdate(cfg.responseTimeout) {
			if err := ctx.Err(); err != nil {
				return fmt.Errorf("fetch_until cancelled before initial batch: %w", err)
			}
			return fmt.Errorf("fetch_until: no initial batch within %s", cfg.responseTimeout)
		}
	}

	var prevMin int64
	sameStreak := 0

	for batch := 0; batch < cfg.maxBatches; batch++ {
		if err := ctx.Err(); err != nil {
			return fmt.Errorf("fetch_until cancelled: %w", err)
		}

		minTs := sess.MinPeriodTime()
		if minTs > 0 && minTs <= untilTs {
			return nil
		}

		if err := sess.RequestMoreData("s1", -cfg.batchSize); err != nil {
			return fmt.Errorf("fetch_until request batch=%d at min_ts=%d: %w", batch, minTs, err)
		}

		// Wait for a new update event, falling through on timeout so the
		// no-progress streak can detect a quiet server.
		_ = waitForUpdate(cfg.responseTimeout)
		if err := ctx.Err(); err != nil {
			return fmt.Errorf("fetch_until cancelled: %w", err)
		}

		select {
		case <-time.After(cfg.throttle):
		case <-ctx.Done():
			return fmt.Errorf("fetch_until cancelled: %w", ctx.Err())
		}

		newMin := sess.MinPeriodTime()
		if newMin == prevMin && newMin > 0 {
			sameStreak++
			if sameStreak >= 2 {
				// Two consecutive no-progress batches — server has no
				// older bars. Treat as terminal-success; caller decides
				// whether the current min meets their needs.
				return nil
			}
		} else {
			sameStreak = 0
		}
		prevMin = newMin
	}

	return fmt.Errorf("fetch_until exceeded max_batches=%d (min_ts=%d, target=%d)", cfg.maxBatches, prevMin, untilTs)
}

// FetchRange fetches every bar in [fromTs, toTs] (Unix seconds, inclusive).
// Caller must have invoked SetMarket(symbol, &ChartSessionOptions{To: toTs, ...})
// beforehand so the FakeReplay anchor is in place. The returned slice is
// sorted ascending by Time (oldest first) for direct consumption by the
// Parquet writer.
func (cs *ChartSession) FetchRange(ctx context.Context, fromTs, toTs int64, opts ...FetchOption) ([]*Period, error) {
	if cs.symbol == "" {
		return nil, fmt.Errorf("FetchRange: SetMarket must be called before FetchRange")
	}
	if fromTs >= toTs {
		return nil, fmt.Errorf("FetchRange: fromTs (%d) must be strictly less than toTs (%d)", fromTs, toTs)
	}

	if err := cs.FetchUntil(ctx, fromTs, opts...); err != nil {
		return nil, err
	}

	all := cs.Periods() // newest-first
	out := make([]*Period, 0, len(all))
	for i := len(all) - 1; i >= 0; i-- {
		p := all[i]
		if p.Time >= fromTs && p.Time <= toTs {
			out = append(out, p)
		}
	}
	return out, nil
}

// Delete deletes the chart session and cleans up resources. Order is
// load-bearing:
//
//  1. cs.session.Delete() — sends replay_delete_session +
//     chart_delete_session on the wire. The manager must still be
//     able to route any late-arriving replay_ok the server emits in
//     parallel with our deletes, so we keep registrations live until
//     the wire packets have been queued.
//  2. UnregisterSession for chart + replay — local cleanup; releases
//     the manager slot so the caller may re-register a fresh session
//     under the same Client.
//
// Reversing this order leaves a window in which the server believes
// the rs_* session exists, our manager has dropped its routing entry,
// and any in-flight replay_ok is silently lost.
func (cs *ChartSession) Delete() error {
	if err := cs.session.Delete(); err != nil {
		return err
	}
	if rs := cs.session.Replay(); rs != nil {
		if err := cs.client.UnregisterSession(rs.ID()); err != nil {
			return err
		}
	}
	return cs.client.UnregisterSession(cs.session.ID())
}
