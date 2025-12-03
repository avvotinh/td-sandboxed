package tradingview

import (
	"github.com/avvotinh/tv-api/internal/session"
)

// QuoteSessionOptions contains options for creating a quote session.
type QuoteSessionOptions struct {
	// Fields is the list of quote fields to subscribe to.
	// If nil, all available fields will be subscribed.
	Fields []string

	// CustomFields allows specifying custom fields beyond the defaults.
	CustomFields []string
}

// QuoteSession represents a quote session for real-time price data.
type QuoteSession struct {
	client  *Client
	session *session.QuoteSession
}

// NewQuoteSession creates a new quote session for subscribing to real-time price updates.
// Use the returned QuoteSession to create Market subscriptions for specific symbols.
func (c *Client) NewQuoteSession(options *QuoteSessionOptions) *QuoteSession {
	var fields []string
	if options != nil {
		fields = options.Fields
		if options.CustomFields != nil {
			fields = append(fields, options.CustomFields...)
		}
	}

	sess := session.NewQuoteSession(c, fields)

	// Register session with client
	if err := c.RegisterSession(sess); err != nil {
		// Log error but continue
	}

	return &QuoteSession{
		client:  c,
		session: sess,
	}
}

// NewMarket creates a new market subscription for the specified symbol.
// The symbol should be in the format "EXCHANGE:SYMBOL" (e.g., "BINANCE:BTCUSDT").
// Use the OnData callback to receive real-time price updates.
func (qs *QuoteSession) NewMarket(symbol string) (*Market, error) {
	market, err := qs.session.AddSymbol(symbol)
	if err != nil {
		return nil, NewSessionError("failed to add symbol", err)
	}

	return &Market{
		session: qs,
		market:  market,
	}, nil
}

// Delete deletes the quote session and cleans up resources.
func (qs *QuoteSession) Delete() error {
	// Unregister from client
	if err := qs.client.UnregisterSession(qs.session.ID()); err != nil {
		return err
	}

	// Delete session
	return qs.session.Delete()
}

// Market represents a market symbol subscription.
type Market struct {
	session *QuoteSession
	market  *session.QuoteMarket
}

// Symbol returns the market symbol.
func (m *Market) Symbol() string {
	return m.market.Symbol()
}

// OnData registers a callback for quote data updates.
func (m *Market) OnData(callback func(data map[string]interface{})) {
	m.market.OnData(callback)
}

// OnLoaded registers a callback for when initial data is loaded.
func (m *Market) OnLoaded(callback func()) {
	m.market.OnLoaded(callback)
}

// OnError registers a callback for errors.
func (m *Market) OnError(callback func(error)) {
	m.market.OnError(callback)
}

// OnEvent registers a callback for generic events.
func (m *Market) OnEvent(callback func(eventType string, data interface{})) {
	m.market.OnEvent(callback)
}

// LastData returns the last received quote data.
func (m *Market) LastData() map[string]interface{} {
	return m.market.LastData()
}

// Close closes the market subscription.
func (m *Market) Close() error {
	return m.market.Close()
}
