package tradingview

import (
	"github.com/avvotinh/tv-api/internal/session"
)

// ChartSessionOptions contains options for creating a chart session.
type ChartSessionOptions struct {
	// Timeframe is the chart timeframe (e.g., "1D", "1", "60")
	Timeframe string

	// Range is the number of bars to retrieve
	Range int

	// To is the end timestamp (optional)
	To int64

	// Adjustment is the price adjustment type (e.g., "splits", "dividends")
	Adjustment string

	// Session is the trading session (e.g., "regular", "extended")
	Session string

	// Currency is the currency for price conversion
	Currency string
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
func (c *Client) NewChartSession() *ChartSession {
	sess := session.NewChartSession(c)

	// Register session with client
	if err := c.RegisterSession(sess); err != nil {
		// Log error but continue
	}

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
func (cs *ChartSession) SetMarket(symbol string, options *ChartSessionOptions) error {
	cs.symbol = symbol

	if options != nil {
		cs.options = options
	}

	// Set defaults
	if cs.options.Timeframe == "" {
		cs.options.Timeframe = "1D"
	}
	if cs.options.Range == 0 {
		cs.options.Range = 300
	}
	if cs.options.Adjustment == "" {
		cs.options.Adjustment = "splits"
	}

	// Resolve symbol
	if err := cs.session.ResolveSymbol(symbol, cs.options.Adjustment, cs.options.Session, cs.options.Currency); err != nil {
		return NewSessionError("failed to resolve symbol", err)
	}

	// Create series
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

// Delete deletes the chart session and cleans up resources.
func (cs *ChartSession) Delete() error {
	// Unregister from client
	if err := cs.client.UnregisterSession(cs.session.ID()); err != nil {
		return err
	}

	// Delete session
	return cs.session.Delete()
}
