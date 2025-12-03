package session

import (
	"fmt"
	"sync"

	"github.com/avvotinh/tv-api/internal/protocol"
)

// QuoteSession represents a real-time quote session.
type QuoteSession struct {
	id              string
	client          ClientBridge
	fields          []string
	markets         map[string]*QuoteMarket
	symbolListeners map[string][]func(map[string]interface{})
	mu              sync.RWMutex
}

// QuoteMarket represents a market symbol subscription.
type QuoteMarket struct {
	symbol    string
	session   *QuoteSession
	symbolKey string
	listeners []func(map[string]interface{})
	lastData  map[string]interface{}
	mu        sync.RWMutex
}

// ClientBridge is an interface for sending packets to the client.
type ClientBridge interface {
	Send(packet protocol.Packet) error
}

// NewQuoteSession creates a new quote session.
func NewQuoteSession(client ClientBridge, fields []string) *QuoteSession {
	if fields == nil || len(fields) == 0 {
		fields = GetQuoteFields()
	}

	sessionID := GenSessionID("qs")

	qs := &QuoteSession{
		id:              sessionID,
		client:          client,
		fields:          fields,
		markets:         make(map[string]*QuoteMarket),
		symbolListeners: make(map[string][]func(map[string]interface{})),
	}

	// Send quote_create_session packet
	qs.createSession()

	// Send quote_set_fields packet
	qs.setFields()

	return qs
}

// ID returns the session ID.
func (qs *QuoteSession) ID() string {
	return qs.id
}

// Type returns the session type.
func (qs *QuoteSession) Type() string {
	return "quote"
}

// OnData handles incoming packet data for this session.
func (qs *QuoteSession) OnData(packet protocol.Packet) error {
	switch packet.Type {
	case "qsd":
		return qs.handleQuoteData(packet)
	case "quote_completed":
		return qs.handleQuoteCompleted(packet)
	case "symbol_error":
		return qs.handleSymbolError(packet)
	default:
		// Unknown packet type for quote session
		return nil
	}
}

// Close closes the session.
func (qs *QuoteSession) Close() error {
	return qs.Delete()
}

// createSession sends the quote_create_session packet.
func (qs *QuoteSession) createSession() error {
	packet := protocol.Packet{
		Type: "quote_create_session",
		Data: []interface{}{qs.id},
	}

	return qs.client.Send(packet)
}

// setFields sends the quote_set_fields packet.
func (qs *QuoteSession) setFields() error {
	// Build data array: [sessionID, field1, field2, ...]
	data := []interface{}{qs.id}
	for _, field := range qs.fields {
		data = append(data, field)
	}

	packet := protocol.Packet{
		Type: "quote_set_fields",
		Data: data,
	}

	return qs.client.Send(packet)
}

// AddSymbol subscribes to a symbol.
func (qs *QuoteSession) AddSymbol(symbol string) (*QuoteMarket, error) {
	qs.mu.Lock()
	defer qs.mu.Unlock()

	// Check if already subscribed
	if market, exists := qs.markets[symbol]; exists {
		return market, nil
	}

	// Create symbol key (format: ={"session":"regular","symbol":"BINANCE:BTCUSDT"})
	// Session parameter is required to match TradingView protocol
	symbolKey := fmt.Sprintf(`={"session":"regular","symbol":"%s"}`, symbol)

	// Send quote_add_symbols packet
	packet := protocol.Packet{
		Type: "quote_add_symbols",
		Data: []interface{}{qs.id, symbolKey},
	}

	if err := qs.client.Send(packet); err != nil {
		return nil, err
	}

	// Create market
	market := &QuoteMarket{
		symbol:    symbol,
		session:   qs,
		symbolKey: symbolKey,
		listeners: []func(map[string]interface{}){},
		lastData:  make(map[string]interface{}),
	}

	qs.markets[symbol] = market
	return market, nil
}

// RemoveSymbol unsubscribes from a symbol.
func (qs *QuoteSession) RemoveSymbol(symbol string) error {
	qs.mu.Lock()
	defer qs.mu.Unlock()

	market, exists := qs.markets[symbol]
	if !exists {
		return fmt.Errorf("symbol %s not subscribed", symbol)
	}

	// Send quote_remove_symbols packet
	packet := protocol.Packet{
		Type: "quote_remove_symbols",
		Data: []interface{}{qs.id, market.symbolKey},
	}

	if err := qs.client.Send(packet); err != nil {
		return err
	}

	delete(qs.markets, symbol)
	delete(qs.symbolListeners, market.symbolKey)
	return nil
}

// Delete deletes the session.
func (qs *QuoteSession) Delete() error {
	packet := protocol.Packet{
		Type: "quote_delete_session",
		Data: []interface{}{qs.id},
	}

	return qs.client.Send(packet)
}

// handleQuoteData processes qsd (quote symbol data) packets.
// QSD packet structure: { type: "qsd", data: [sessionID, {n: symbolKey, s: status, v: data}] }
func (qs *QuoteSession) handleQuoteData(packet protocol.Packet) error {
	if len(packet.Data) < 2 {
		return fmt.Errorf("invalid qsd packet: insufficient data")
	}

	// Extract the data object at index 1
	dataObj, ok := packet.Data[1].(map[string]interface{})
	if !ok {
		return fmt.Errorf("invalid qsd packet: data[1] is not an object")
	}

	// Extract symbol key from 'n' field
	symbolKey, ok := dataObj["n"].(string)
	if !ok {
		return fmt.Errorf("invalid qsd packet: missing or invalid 'n' field")
	}

	// Extract status from 's' field
	status, ok := dataObj["s"].(string)
	if !ok {
		return fmt.Errorf("invalid qsd packet: missing or invalid 's' field")
	}

	// Check status
	if status == "error" {
		// Handle error case
		errorMsg := "unknown error"
		if errData, ok := dataObj["v"].(map[string]interface{}); ok {
			if msg, ok := errData["message"].(string); ok {
				errorMsg = msg
			}
		}
		return fmt.Errorf("quote data error for %s: %s", symbolKey, errorMsg)
	}

	// Only process if status is 'ok'
	if status != "ok" {
		// Unknown status, ignore
		return nil
	}

	// Extract quote data from 'v' field
	var quoteData map[string]interface{}
	if v, ok := dataObj["v"].(map[string]interface{}); ok {
		quoteData = v
	} else {
		// No data in 'v' field
		quoteData = make(map[string]interface{})
	}

	// Find the market and notify listeners
	qs.mu.RLock()
	defer qs.mu.RUnlock()

	for _, market := range qs.markets {
		if market.symbolKey == symbolKey {
			market.updateData(quoteData)
			break
		}
	}

	// Notify session-level listeners
	if listeners, exists := qs.symbolListeners[symbolKey]; exists {
		for _, listener := range listeners {
			listener(quoteData)
		}
	}

	return nil
}

// handleQuoteCompleted processes quote_completed packets.
func (qs *QuoteSession) handleQuoteCompleted(packet protocol.Packet) error {
	// Quote completed just signals that initial data has been sent
	// We don't need to do anything special here
	return nil
}

// handleSymbolError processes symbol_error packets.
func (qs *QuoteSession) handleSymbolError(packet protocol.Packet) error {
	// Extract error details from packet data
	var symbol string
	var errorMsg string

	if len(packet.Data) > 0 {
		if sessionID, ok := packet.Data[0].(string); ok {
			// Try to find which symbol caused the error
			qs.mu.RLock()
			for _, market := range qs.markets {
				if market.symbolKey == sessionID {
					symbol = market.symbol
					break
				}
			}
			qs.mu.RUnlock()
		}
	}

	if len(packet.Data) > 1 {
		errorMsg = fmt.Sprintf("%v", packet.Data[1])
	} else {
		errorMsg = fmt.Sprintf("%v", packet.Data)
	}

	// Create a clear error message
	if symbol != "" {
		return fmt.Errorf("invalid symbol '%s': %s", symbol, errorMsg)
	}
	return fmt.Errorf("symbol error: %s", errorMsg)
}

// GetQuoteFields returns the default list of quote fields.
func GetQuoteFields() []string {
	return []string{
		"lp",                         // Last price
		"ch",                         // Change
		"chp",                        // Change percent
		"volume",                     // Volume
		"ask",                        // Ask price
		"bid",                        // Bid price
		"high_price",                 // High price
		"low_price",                  // Low price
		"open_price",                 // Open price
		"prev_close_price",           // Previous close
		"last_update",                // Last update timestamp
		"rch",                        // Relative change
		"rchp",                       // Relative change percent
		"rtc",                        // Real-time change
		"rtc_time",                   // Real-time change time
		"lp_time",                    // Last price time
		"ask_size",                   // Ask size
		"bid_size",                   // Bid size
		"volume_today",               // Today's volume
		"trades_count",               // Number of trades
		"currency_code",              // Currency code
		"original_name",              // Original symbol name
		"short_name",                 // Short name
		"pro_name",                   // Pro name
		"update_mode",                // Update mode
		"type",                       // Instrument type
		"typespecs",                  // Type specs
		"exchange",                   // Exchange
		"provider_id",                // Provider ID
		"country_code",               // Country code
		"currency_id",                // Currency ID
		"fiscal_year",                // Fiscal year
		"market_cap_basic",           // Market cap
		"earnings_per_share_basic",   // EPS
		"price_earnings_ttm",         // P/E ratio
		"sector",                     // Sector
		"industry",                   // Industry
		"description",                // Description
		"logoid",                     // Logo ID
		"country",                    // Country
		"market",                     // Market
		"premarket",                  // Premarket data
		"postmarket",                 // Postmarket data
		"fundamentals",               // Fundamentals
		"dividend_yield_recent",      // Dividend yield
		"earnings_release_date",      // Earnings date
		"earnings_release_next_date", // Next earnings
		"earnings_release_next_time", // Next earnings time
		"market_open",                // Market open
		"market_close",               // Market close
		"timezone",                   // Timezone
		"fractional",                 // Fractional support
		"minmov",                     // Minimum movement
		"minmove2",                   // Minimum movement 2
		"pricescale",                 // Price scale
	}
}

// QuoteMarket methods

// Symbol returns the market symbol.
func (qm *QuoteMarket) Symbol() string {
	return qm.symbol
}

// OnData registers a callback for quote data updates.
func (qm *QuoteMarket) OnData(callback func(map[string]interface{})) {
	qm.mu.Lock()
	defer qm.mu.Unlock()
	qm.listeners = append(qm.listeners, callback)
}

// OnLoaded registers a callback for when initial data is loaded.
func (qm *QuoteMarket) OnLoaded(callback func()) {
	// In TradingView, quote_completed signals initial load
	// We'll trigger it on first data receive
	firstCall := true
	qm.OnData(func(data map[string]interface{}) {
		if firstCall {
			firstCall = false
			callback()
		}
	})
}

// OnError registers a callback for errors.
func (qm *QuoteMarket) OnError(callback func(error)) {
	// Errors are handled at the session level
	// This is here for API compatibility
}

// OnEvent registers a callback for generic events.
func (qm *QuoteMarket) OnEvent(callback func(string, interface{})) {
	// Generic events are handled at the session level
	// This is here for API compatibility
}

// LastData returns the last received quote data.
func (qm *QuoteMarket) LastData() map[string]interface{} {
	qm.mu.RLock()
	defer qm.mu.RUnlock()

	// Return a copy to avoid concurrent modification
	dataCopy := make(map[string]interface{})
	for k, v := range qm.lastData {
		dataCopy[k] = v
	}
	return dataCopy
}

// updateData updates the last received data and notifies listeners.
func (qm *QuoteMarket) updateData(data map[string]interface{}) {
	qm.mu.Lock()
	// Merge new data into lastData
	for k, v := range data {
		qm.lastData[k] = v
	}

	// Create a copy of accumulated data to send to listeners
	// This matches JavaScript behavior which sends full lastData on each update
	accumulatedData := make(map[string]interface{}, len(qm.lastData))
	for k, v := range qm.lastData {
		accumulatedData[k] = v
	}

	listeners := make([]func(map[string]interface{}), len(qm.listeners))
	copy(listeners, qm.listeners)
	qm.mu.Unlock()

	// Notify listeners outside the lock with accumulated data
	for _, listener := range listeners {
		listener(accumulatedData)
	}
}

// Close closes the market subscription.
func (qm *QuoteMarket) Close() error {
	return qm.session.RemoveSymbol(qm.symbol)
}
