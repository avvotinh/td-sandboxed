package display

import (
	"fmt"
	"sync"
	"time"

	"github.com/avvotinh/tv-api/internal/session"
)

// SectionState tracks the display state for a symbol-timeframe pair.
type SectionState struct {
	Symbol           string
	Timeframe        string
	HeaderPrinted    bool
	LastUpdate       time.Time
	LatestPeriod     *session.Period
	UpdateCount      int
	LastDisplayedTime  int64   // Track last displayed candle timestamp
	LastDisplayedClose float64 // Track last displayed close price
}

// QuoteSectionState tracks the display state for a quote symbol.
type QuoteSectionState struct {
	Symbol           string
	HeaderPrinted    bool
	LastUpdate       time.Time
	LastData         map[string]interface{}
	UpdateCount      int
	LastDisplayedPrice float64 // Track last displayed price to avoid duplicates
}

// Manager manages output display state for multiple symbol-timeframe subscriptions and quote symbols.
// It ensures proper section headers and serializes updates to prevent garbled output.
type Manager struct {
	sections      map[string]*SectionState      // key: "SYMBOL:TIMEFRAME"
	quoteSections map[string]*QuoteSectionState // key: "SYMBOL"
	mu            sync.Mutex
}

// NewManager creates a new display manager.
func NewManager() *Manager {
	return &Manager{
		sections:      make(map[string]*SectionState),
		quoteSections: make(map[string]*QuoteSectionState),
	}
}

// UpdateSection displays an update for a symbol-timeframe pair.
// It automatically prints a section header on the first update for each pair.
// Output format:
//
//	=== NASDAQ:AAPL [1] ===
//	[10:31:09] NASDAQ:AAPL [1] O=150.25 H=150.50 L=150.10 C=150.45 V=1234567
func (m *Manager) UpdateSection(symbol, timeframe string, period *session.Period) {
	m.mu.Lock()
	defer m.mu.Unlock()

	key := fmt.Sprintf("%s:%s", symbol, timeframe)
	state, exists := m.sections[key]

	if !exists {
		// Create new section state
		state = &SectionState{
			Symbol:    symbol,
			Timeframe: timeframe,
		}
		m.sections[key] = state

		// Print section header for new subscription
		fmt.Printf("\n=== %s [%s] ===\n", symbol, timeframe)
		state.HeaderPrinted = true
	}

	// Only print if this is a different candle or the close price has changed
	// This prevents duplicate output for the same candle
	if period.Time != state.LastDisplayedTime || period.Close != state.LastDisplayedClose {
		timestamp := time.Unix(period.Time, 0)
		fmt.Printf("[%s] %s [%s] O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f\n",
			timestamp.Format("15:04:05"),
			symbol,
			timeframe,
			period.Open,
			period.High,
			period.Low,
			period.Close,
			period.Volume,
		)

		// Update tracking state
		state.LastDisplayedTime = period.Time
		state.LastDisplayedClose = period.Close
		state.UpdateCount++
	}

	// Always update latest period and timestamp
	state.LastUpdate = time.Now()
	state.LatestPeriod = period
}

// GetSection retrieves the current state for a symbol-timeframe pair.
// Returns nil if the section doesn't exist.
func (m *Manager) GetSection(symbol, timeframe string) *SectionState {
	m.mu.Lock()
	defer m.mu.Unlock()

	key := fmt.Sprintf("%s:%s", symbol, timeframe)
	return m.sections[key]
}

// GetSectionCount returns the total number of active sections.
func (m *Manager) GetSectionCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.sections)
}

// Clear removes all section states (useful for testing or reset scenarios).
func (m *Manager) Clear() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sections = make(map[string]*SectionState)
	m.quoteSections = make(map[string]*QuoteSectionState)
}

// UpdateQuoteSection displays an update for a quote symbol.
// It automatically prints a section header on the first update for each symbol.
// Output format:
//
//	=== NASDAQ:AAPL [QUOTE] ===
//	[10:31:09] NASDAQ:AAPL Last=150.45 Bid=150.40 Ask=150.50 Vol=1234567
func (m *Manager) UpdateQuoteSection(symbol string, data map[string]interface{}) {
	m.mu.Lock()
	defer m.mu.Unlock()

	state, exists := m.quoteSections[symbol]

	if !exists {
		// Create new quote section state
		state = &QuoteSectionState{
			Symbol:   symbol,
			LastData: make(map[string]interface{}),
		}
		m.quoteSections[symbol] = state

		// Print section header for new subscription
		fmt.Printf("\n=== %s [QUOTE] ===\n", symbol)
		state.HeaderPrinted = true
	}

	// Extract key fields for display
	lastPrice := getFloat64Value(data, "lp")
	bid := getFloat64Value(data, "bid")
	ask := getFloat64Value(data, "ask")
	volume := getFloat64Value(data, "volume")
	change := getFloat64Value(data, "ch")
	changePercent := getFloat64Value(data, "chp")

	// Only print if the last price has changed to avoid duplicates
	if lastPrice != state.LastDisplayedPrice {
		timestamp := time.Now()

		// Format output with available data
		output := fmt.Sprintf("[%s] %s", timestamp.Format("15:04:05"), symbol)

		if lastPrice > 0 {
			output += fmt.Sprintf(" Last=%.4f", lastPrice)
		}

		if bid > 0 {
			output += fmt.Sprintf(" Bid=%.4f", bid)
		}

		if ask > 0 {
			output += fmt.Sprintf(" Ask=%.4f", ask)
		}

		if change != 0 || changePercent != 0 {
			output += fmt.Sprintf(" Chg=%.4f (%.2f%%)", change, changePercent)
		}

		if volume > 0 {
			output += fmt.Sprintf(" Vol=%.0f", volume)
		}

		fmt.Println(output)

		// Update tracking state
		state.LastDisplayedPrice = lastPrice
		state.UpdateCount++
	}

	// Always update latest data and timestamp
	state.LastUpdate = time.Now()
	for k, v := range data {
		state.LastData[k] = v
	}
}

// GetQuoteSection retrieves the current state for a quote symbol.
// Returns nil if the section doesn't exist.
func (m *Manager) GetQuoteSection(symbol string) *QuoteSectionState {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.quoteSections[symbol]
}

// getFloat64Value safely extracts a float64 value from the data map.
// Returns 0 if the key doesn't exist or the value can't be converted.
func getFloat64Value(data map[string]interface{}, key string) float64 {
	if val, ok := data[key]; ok {
		switch v := val.(type) {
		case float64:
			return v
		case float32:
			return float64(v)
		case int:
			return float64(v)
		case int64:
			return float64(v)
		}
	}
	return 0
}
