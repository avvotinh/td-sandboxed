// Package handlers provides tests for message handlers.
package handlers

import (
	"errors"
	"strings"
	"testing"
	"time"

	notifyerrors "github.com/user/sandboxed/services/notification/internal/errors"
)

func TestNewTradeHandler(t *testing.T) {
	handler := NewTradeHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
	if handler.formatter == nil {
		t.Error("Expected formatter to be initialized")
	}
}

// Test 5.1: Unit tests for JSON parsing of trade open events
func TestTradeHandler_Handle_TradeOpened(t *testing.T) {
	handler := NewTradeHandler()

	payload := []byte(`{
		"type": "trade_opened",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "BUY",
		"volume": 0.10,
		"price": 1850.25,
		"sl": 1845.00,
		"tp": 1860.00,
		"reason": "MA crossover (20/50 SMA)",
		"daily_pnl": -350.00,
		"daily_pnl_pct": -0.35,
		"timestamp": "2026-01-15T14:32:15Z"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}
	if msg == "" {
		t.Error("Expected formatted message, got empty string")
	}

	// Verify required fields in output
	expectedFields := []string{
		"🔵", "*TRADE EXECUTED*",
		"FTMO Gold Challenge",
		"XAUUSD",
		"BUY", "0.10",
		"1850.25",
		"1845.00", "1860.00",
		"MA crossover (20/50 SMA)",
		"-$350.00", "-0.35%",
		"14:32:15 UTC",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s', got:\n%s", field, msg)
		}
	}
}

// Test 5.2: Unit tests for JSON parsing of trade close events
func TestTradeHandler_Handle_TradeClosed(t *testing.T) {
	handler := NewTradeHandler()

	payload := []byte(`{
		"type": "trade_closed",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "SELL",
		"volume": 0.10,
		"entry_price": 1850.25,
		"exit_price": 1858.50,
		"pnl": 82.50,
		"pnl_pct": 0.45,
		"result": "PROFIT",
		"duration": "2h 15m",
		"daily_pnl": -267.50,
		"daily_pnl_pct": -0.27,
		"timestamp": "2026-01-15T16:47:30Z"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}
	if msg == "" {
		t.Error("Expected formatted message, got empty string")
	}

	// Verify required fields
	expectedFields := []string{
		"🟢", "*TRADE CLOSED - PROFIT*",
		"FTMO Gold Challenge",
		"XAUUSD",
		"SELL", "0.10", "(close)",
		"1850.25", "1858.50",
		"+$82.50",
		"-$267.50", "-0.27%",
		"16:47:30 UTC",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s', got:\n%s", field, msg)
		}
	}
}

// Test trade close with LOSS result
func TestTradeHandler_Handle_TradeClosed_Loss(t *testing.T) {
	handler := NewTradeHandler()

	payload := []byte(`{
		"type": "trade_closed",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "SELL",
		"volume": 0.10,
		"entry_price": 1850.25,
		"exit_price": 1842.00,
		"pnl": -82.50,
		"pnl_pct": -0.45,
		"result": "LOSS",
		"duration": "1h 30m",
		"daily_pnl": -432.50,
		"daily_pnl_pct": -0.43,
		"timestamp": "2026-01-15T16:02:30Z"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}

	// Verify LOSS emoji and formatting
	if !strings.Contains(msg, "🔴") {
		t.Error("Expected red emoji for LOSS")
	}
	if !strings.Contains(msg, "*TRADE CLOSED - LOSS*") {
		t.Error("Expected 'TRADE CLOSED - LOSS' header")
	}
	if !strings.Contains(msg, "-$82.50") {
		t.Error("Expected negative P&L formatting")
	}
	if !strings.Contains(msg, "16:02:30 UTC") {
		t.Error("Expected timestamp in close notification")
	}
}

// Test 5.5: Unit tests for invalid JSON handling
func TestTradeHandler_Handle_InvalidJSON(t *testing.T) {
	handler := NewTradeHandler()

	testCases := []struct {
		name    string
		payload []byte
	}{
		{
			name:    "completely invalid JSON",
			payload: []byte(`not valid json at all`),
		},
		{
			name:    "truncated JSON",
			payload: []byte(`{"type": "trade_opened", "account_id":`),
		},
		{
			name:    "empty payload",
			payload: []byte(``),
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			msg, err := handler.Handle("ftmo-001", tc.payload)
			if err == nil {
				t.Error("Expected error for invalid JSON, got nil")
			}
			if msg != "" {
				t.Errorf("Expected empty message on error, got: %s", msg)
			}
			// Should wrap with ErrMessageParseError
			if !errors.Is(err, notifyerrors.ErrMessageParseError) {
				t.Errorf("Expected ErrMessageParseError, got: %v", err)
			}
		})
	}
}

// Test unknown event type handling
func TestTradeHandler_Handle_UnknownEventType(t *testing.T) {
	handler := NewTradeHandler()

	payload := []byte(`{
		"type": "trade_unknown",
		"account_id": "ftmo-gold-001"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err == nil {
		t.Error("Expected error for unknown event type, got nil")
	}
	if msg != "" {
		t.Errorf("Expected empty message on error, got: %s", msg)
	}
	// Should wrap with ErrUnknownEventType
	if !errors.Is(err, notifyerrors.ErrUnknownEventType) {
		t.Errorf("Expected ErrUnknownEventType, got: %v", err)
	}
}

// Test 5.7: Fire-and-forget behavior - handler returns immediately
func TestTradeHandler_Handle_ReturnsImmediately(t *testing.T) {
	handler := NewTradeHandler()

	payload := []byte(`{
		"type": "trade_opened",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "BUY",
		"volume": 0.10,
		"price": 1850.25,
		"sl": 1845.00,
		"tp": 1860.00,
		"reason": "MA crossover",
		"daily_pnl": -350.00,
		"daily_pnl_pct": -0.35,
		"timestamp": "2026-01-15T14:32:15Z"
	}`)

	// Handler should return quickly (< 10ms for formatting)
	start := time.Now()
	_, err := handler.Handle("ftmo-gold-001", payload)
	elapsed := time.Since(start)

	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if elapsed > 10*time.Millisecond {
		t.Errorf("Handler took too long: %v (expected < 10ms)", elapsed)
	}
}

// Test with missing optional fields (sl, tp)
func TestTradeHandler_Handle_MissingOptionalFields(t *testing.T) {
	handler := NewTradeHandler()

	// No SL/TP fields
	payload := []byte(`{
		"type": "trade_opened",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "BUY",
		"volume": 0.10,
		"price": 1850.25,
		"reason": "Manual trade",
		"daily_pnl": 0,
		"daily_pnl_pct": 0,
		"timestamp": "2026-01-15T14:32:15Z"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err != nil {
		t.Fatalf("Expected no error for missing optional fields, got: %v", err)
	}
	if msg == "" {
		t.Error("Expected formatted message, got empty string")
	}

	// SL/TP should show 0.00
	if !strings.Contains(msg, "SL: $0.00 | TP: $0.00") {
		t.Errorf("Expected zero SL/TP values, got:\n%s", msg)
	}
}

func TestNewRiskHandler(t *testing.T) {
	handler := NewRiskHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
	if handler.formatter == nil {
		t.Error("Expected formatter to be initialized")
	}
}

func TestRiskHandler_Handle(t *testing.T) {
	handler := NewRiskHandler()

	// Scaffold mode just logs, should not error
	msg, err := handler.Handle("ftmo-001", []byte(`{"rule":"daily_loss","current":4.5}`))
	if err != nil {
		t.Errorf("Expected no error, got: %v", err)
	}
	// Scaffold returns empty string (no notification sent)
	if msg != "" {
		t.Errorf("Expected empty message in scaffold mode, got: %s", msg)
	}
}

func TestNewSystemHandler(t *testing.T) {
	handler := NewSystemHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
}

func TestSystemHandler_Handle(t *testing.T) {
	handler := NewSystemHandler()

	// Scaffold mode just logs, should not error
	msg, err := handler.Handle("", []byte(`{"type":"system_alert","severity":"info"}`))
	if err != nil {
		t.Errorf("Expected no error, got: %v", err)
	}
	// Scaffold returns empty string (no notification sent)
	if msg != "" {
		t.Errorf("Expected empty message in scaffold mode, got: %s", msg)
	}
}

func TestNewEmergencyHandler(t *testing.T) {
	handler := NewEmergencyHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
}

func TestEmergencyHandler_Handle(t *testing.T) {
	handler := NewEmergencyHandler()

	// Scaffold mode just logs, should not error
	msg, err := handler.Handle("", []byte(`{"type":"emergency_stop","source":"user"}`))
	if err != nil {
		t.Errorf("Expected no error, got: %v", err)
	}
	// Scaffold returns empty string (no notification sent)
	if msg != "" {
		t.Errorf("Expected empty message in scaffold mode, got: %s", msg)
	}
}

func TestNewHealthHandler(t *testing.T) {
	handler := NewHealthHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
}

func TestHealthHandler_Handle(t *testing.T) {
	handler := NewHealthHandler()

	// Scaffold mode just logs, should not error
	err := handler.Handle([]byte(`{"component":"redis","status":"healthy"}`))
	if err != nil {
		t.Errorf("Expected no error, got: %v", err)
	}
}
