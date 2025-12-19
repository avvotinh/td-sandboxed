// Package formatters provides tests for trade message formatting.
package formatters

import (
	"strings"
	"testing"
)

func TestTradeFormatter_FormatOpen(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeEvent{
		AccountID:   "ftmo-001",
		AccountName: "FTMO Gold",
		Symbol:      "XAUUSD",
		Action:      "BUY",
		Volume:      0.10,
		Price:       1850.25,
		SL:          1845.00,
		TP:          1860.00,
		Reason:      "MA crossover",
		DailyPnL:    -350.00,
		DailyPnLPct: -0.35,
		Timestamp:   "14:32:15 UTC",
	}

	result := formatter.FormatOpen(event)

	// Verify key fields are present
	if !strings.Contains(result, "TRADE EXECUTED") {
		t.Error("Expected 'TRADE EXECUTED' in output")
	}
	if !strings.Contains(result, "FTMO Gold") {
		t.Error("Expected account name in output")
	}
	if !strings.Contains(result, "XAUUSD") {
		t.Error("Expected symbol in output")
	}
	if !strings.Contains(result, "BUY") {
		t.Error("Expected action in output")
	}
	if !strings.Contains(result, "0.10") {
		t.Error("Expected volume in output")
	}
	if !strings.Contains(result, "1850.25") {
		t.Error("Expected price in output")
	}
}

func TestTradeFormatter_FormatClose_Profit(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeCloseEvent{
		TradeEvent: TradeEvent{
			AccountName: "FTMO Gold",
			Symbol:      "XAUUSD",
		},
		Result:   "PROFIT",
		PnL:      150.00,
		PnLPct:   1.5,
		Duration: "2h 15m",
	}

	result := formatter.FormatClose(event)

	if !strings.Contains(result, "TRADE CLOSED") {
		t.Error("Expected 'TRADE CLOSED' in output")
	}
	if !strings.Contains(result, "PROFIT") {
		t.Error("Expected 'PROFIT' in output")
	}
	if !strings.Contains(result, "+") {
		t.Error("Expected '+' prefix for profit")
	}
}

func TestTradeFormatter_FormatClose_Loss(t *testing.T) {
	formatter := NewTradeFormatter()

	event := &TradeCloseEvent{
		TradeEvent: TradeEvent{
			AccountName: "FTMO Gold",
			Symbol:      "XAUUSD",
		},
		Result:   "LOSS",
		PnL:      -75.00,
		PnLPct:   -0.75,
		Duration: "45m",
	}

	result := formatter.FormatClose(event)

	if !strings.Contains(result, "LOSS") {
		t.Error("Expected 'LOSS' in output")
	}
	if !strings.Contains(result, "-") {
		t.Error("Expected '-' prefix for loss")
	}
}

func TestNewTradeFormatter(t *testing.T) {
	formatter := NewTradeFormatter()
	if formatter == nil {
		t.Error("Expected formatter to be created, got nil")
	}
}
