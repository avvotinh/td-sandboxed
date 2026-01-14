// Package formatters provides tests for trade message formatting.
package formatters

import (
	"strings"
	"testing"
)

// Test 5.3: Unit tests for FormatOpen() output matching AC format
func TestTradeFormatter_FormatOpen(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeEvent{
		Type:        "trade_opened",
		AccountID:   "ftmo-gold-001",
		AccountName: "FTMO Gold Challenge",
		Symbol:      "XAUUSD",
		Action:      "BUY",
		Volume:      0.10,
		Price:       1850.25,
		SL:          1845.00,
		TP:          1860.00,
		Reason:      "MA crossover (20/50 SMA)",
		DailyPnL:    -350.00,
		DailyPnLPct: -0.35,
		Timestamp:   "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatOpen(event)

	// Verify AC#1 format requirements
	expectedFields := []string{
		"🔵",                             // Blue circle emoji
		"*TRADE EXECUTED*",               // Markdown bold header
		"Account: FTMO Gold Challenge",   // Account name
		"Symbol: XAUUSD",                 // Symbol
		"Action: BUY 0.10 lots",          // Action with volume
		"Entry: $1850.25",                // Entry price
		"SL: $1845.00 | TP: $1860.00",    // Stop loss and take profit
		"Reason: MA crossover (20/50 SMA)", // Reason
		"Daily P&L: -$350.00 (-0.35%)",   // Daily PnL with negative formatting
		"Time: 14:32:15 UTC",             // Timestamp in UTC
	}

	for _, expected := range expectedFields {
		if !strings.Contains(result, expected) {
			t.Errorf("Expected output to contain '%s'\n\nGot:\n%s", expected, result)
		}
	}
}

// Test 5.4: Unit tests for FormatClose() with PROFIT scenario
func TestTradeFormatter_FormatClose_Profit(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeCloseEvent{
		Type:        "trade_closed",
		AccountID:   "ftmo-gold-001",
		AccountName: "FTMO Gold Challenge",
		Symbol:      "XAUUSD",
		Action:      "SELL",
		Volume:      0.10,
		EntryPrice:  1850.25,
		ExitPrice:   1858.50,
		PnL:         82.50,
		PnLPct:      0.45,
		Result:      "PROFIT",
		Duration:    "2h 15m",
		DailyPnL:    -267.50,
		DailyPnLPct: -0.27,
		Timestamp:   "2026-01-15T16:47:30Z",
	}

	result := formatter.FormatClose(event)

	// Verify AC#2 PROFIT format requirements
	expectedFields := []string{
		"🟢",                              // Green circle emoji for PROFIT
		"*TRADE CLOSED - PROFIT*",         // Markdown bold header with result
		"Account: FTMO Gold Challenge",    // Account name
		"Symbol: XAUUSD",                  // Symbol
		"Action: SELL 0.10 lots (close)",  // Action with volume and close marker
		"Entry: $1850.25 → Exit: $1858.50", // Entry to exit prices
		"P&L: +$82.50",                    // PnL with + sign
		"Daily P&L: -$267.50 (-0.27%)",    // Daily PnL
		"Time: 16:47:30 UTC",              // Timestamp
	}

	for _, expected := range expectedFields {
		if !strings.Contains(result, expected) {
			t.Errorf("Expected output to contain '%s'\n\nGot:\n%s", expected, result)
		}
	}
}

// Test 5.4: Unit tests for FormatClose() with LOSS scenario
func TestTradeFormatter_FormatClose_Loss(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeCloseEvent{
		Type:        "trade_closed",
		AccountID:   "ftmo-gold-001",
		AccountName: "FTMO Gold Challenge",
		Symbol:      "XAUUSD",
		Action:      "SELL",
		Volume:      0.10,
		EntryPrice:  1850.25,
		ExitPrice:   1842.00,
		PnL:         -82.50,
		PnLPct:      -0.45,
		Result:      "LOSS",
		Duration:    "1h 30m",
		DailyPnL:    -432.50,
		DailyPnLPct: -0.43,
		Timestamp:   "2026-01-15T16:02:30Z",
	}

	result := formatter.FormatClose(event)

	// Verify AC#2 LOSS format requirements
	expectedFields := []string{
		"🔴",                              // Red circle emoji for LOSS
		"*TRADE CLOSED - LOSS*",           // Markdown bold header with result
		"Account: FTMO Gold Challenge",    // Account name
		"Symbol: XAUUSD",                  // Symbol
		"Action: SELL 0.10 lots (close)",  // Action with volume and close marker
		"Entry: $1850.25 → Exit: $1842.00", // Entry to exit prices
		"P&L: -$82.50",                    // PnL with - sign
		"Daily P&L: -$432.50 (-0.43%)",    // Daily PnL
		"Time: 16:02:30 UTC",              // Timestamp
	}

	for _, expected := range expectedFields {
		if !strings.Contains(result, expected) {
			t.Errorf("Expected output to contain '%s'\n\nGot:\n%s", expected, result)
		}
	}
}

func TestNewTradeFormatter(t *testing.T) {
	formatter := NewTradeFormatter()
	if formatter == nil {
		t.Error("Expected formatter to be created, got nil")
	}
}

// Test money formatting helper function
func TestFormatMoney(t *testing.T) {
	tests := []struct {
		value    float64
		expected string
	}{
		{100.00, "$100.00"},
		{0.00, "$0.00"},
		{-350.00, "-$350.00"},
		{-0.50, "-$0.50"},
		{1234.56, "$1234.56"},
	}

	for _, tt := range tests {
		result := formatMoney(tt.value)
		if result != tt.expected {
			t.Errorf("formatMoney(%f) = %s; want %s", tt.value, result, tt.expected)
		}
	}
}

// Test money formatting with explicit sign
func TestFormatMoneyWithSign(t *testing.T) {
	tests := []struct {
		value    float64
		expected string
	}{
		{100.00, "+$100.00"},
		{0.00, "+$0.00"},
		{-350.00, "-$350.00"},
		{-0.50, "-$0.50"},
		{82.50, "+$82.50"},
	}

	for _, tt := range tests {
		result := formatMoneyWithSign(tt.value)
		if result != tt.expected {
			t.Errorf("formatMoneyWithSign(%f) = %s; want %s", tt.value, result, tt.expected)
		}
	}
}

// Test timestamp formatting
func TestFormatTimestamp(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"2026-01-15T14:32:15Z", "14:32:15 UTC"},
		{"2026-01-15T00:00:00Z", "00:00:00 UTC"},
		{"2026-12-31T23:59:59Z", "23:59:59 UTC"},
		{"invalid timestamp", "invalid timestamp"}, // Returns original on parse failure
		{"", ""},                                     // Empty string
	}

	for _, tt := range tests {
		result := formatTimestamp(tt.input)
		if result != tt.expected {
			t.Errorf("formatTimestamp(%s) = %s; want %s", tt.input, result, tt.expected)
		}
	}
}

// Test positive daily P&L formatting
func TestTradeFormatter_FormatOpen_PositiveDailyPnL(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeEvent{
		Type:        "trade_opened",
		AccountID:   "ftmo-gold-001",
		AccountName: "FTMO Gold Challenge",
		Symbol:      "XAUUSD",
		Action:      "BUY",
		Volume:      0.10,
		Price:       1850.25,
		SL:          1845.00,
		TP:          1860.00,
		Reason:      "MA crossover",
		DailyPnL:    250.00, // Positive P&L
		DailyPnLPct: 0.25,
		Timestamp:   "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatOpen(event)

	// Positive P&L should not have minus sign
	if !strings.Contains(result, "Daily P&L: $250.00 (0.25%)") {
		t.Errorf("Expected positive P&L formatting, got:\n%s", result)
	}
}

// Test zero values
func TestTradeFormatter_FormatOpen_ZeroValues(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeEvent{
		Type:        "trade_opened",
		AccountID:   "ftmo-gold-001",
		AccountName: "FTMO Gold Challenge",
		Symbol:      "XAUUSD",
		Action:      "BUY",
		Volume:      0.01,
		Price:       1850.00,
		SL:          0.00,
		TP:          0.00,
		Reason:      "Test",
		DailyPnL:    0.00,
		DailyPnLPct: 0.00,
		Timestamp:   "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatOpen(event)

	// Zero values should display correctly
	if !strings.Contains(result, "SL: $0.00 | TP: $0.00") {
		t.Errorf("Expected zero SL/TP values, got:\n%s", result)
	}
	if !strings.Contains(result, "Daily P&L: $0.00 (0.00%)") {
		t.Errorf("Expected zero daily P&L, got:\n%s", result)
	}
}

// Test zero P&L in close event
func TestTradeFormatter_FormatClose_ZeroPnL(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeCloseEvent{
		Type:        "trade_closed",
		AccountID:   "ftmo-gold-001",
		AccountName: "FTMO Gold Challenge",
		Symbol:      "XAUUSD",
		Action:      "SELL",
		Volume:      0.10,
		EntryPrice:  1850.00,
		ExitPrice:   1850.00, // Same as entry = break even
		PnL:         0.00,
		PnLPct:      0.00,
		Result:      "PROFIT", // Break-even counted as profit
		Duration:    "30m",
		DailyPnL:    0.00,
		DailyPnLPct: 0.00,
		Timestamp:   "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatClose(event)

	// Zero PnL should show +$0.00
	if !strings.Contains(result, "P&L: +$0.00") {
		t.Errorf("Expected +$0.00 for zero P&L, got:\n%s", result)
	}
	// Verify Time field is present
	if !strings.Contains(result, "Time: 14:32:15 UTC") {
		t.Errorf("Expected Time field in close output, got:\n%s", result)
	}
}
