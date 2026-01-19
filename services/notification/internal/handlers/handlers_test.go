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

// Test 4.1: Unit tests for JSON parsing of risk_blocked events (AC#1)
func TestRiskHandler_Handle_RiskBlocked(t *testing.T) {
	handler := NewRiskHandler()

	payload := []byte(`{
		"type": "risk_blocked",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Daily Loss Limit",
		"rule_type": "blocked",
		"current": 4.8,
		"threshold": 5.0,
		"trade": "BUY 0.10 XAUUSD",
		"reason": "Trade would exceed daily loss limit",
		"action": "Trade rejected",
		"timestamp": "2026-01-15T14:32:15Z"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}
	if msg == "" {
		t.Error("Expected formatted message, got empty string")
	}

	// AC#1: Verify required fields in output
	expectedFields := []string{
		"🔴", "*TRADE BLOCKED*",
		"FTMO Gold Challenge",
		"Daily Loss Limit",
		"4.8% of 5.0% limit",
		"BUY 0.10 XAUUSD",
		"Trade would exceed daily loss limit",
		"Trade rejected",
		"14:32:15 UTC",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s', got:\n%s", field, msg)
		}
	}
}

// Test 4.2: Unit tests for JSON parsing of risk_warning events (AC#2)
func TestRiskHandler_Handle_RiskWarning(t *testing.T) {
	handler := NewRiskHandler()

	payload := []byte(`{
		"type": "risk_warning",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Daily Loss Limit",
		"rule_type": "warning",
		"current": 4.0,
		"threshold": 5.0,
		"warning_level": 80,
		"remaining_dollars": 1000.00,
		"action": "Trading continues, monitor closely",
		"timestamp": "2026-01-15T14:32:15Z"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}
	if msg == "" {
		t.Error("Expected formatted message, got empty string")
	}

	// AC#2: Verify required fields in output
	expectedFields := []string{
		"🟡", "*RISK WARNING*",
		"FTMO Gold Challenge",
		"Daily Loss Limit",
		"80% of limit reached",
		"4.0% of 5.0% limit",
		"$1000 (1.0%)",
		"Trading continues, monitor closely",
		"14:32:15 UTC",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s', got:\n%s", field, msg)
		}
	}
}

// Test 4.3: Unit tests for JSON parsing of trading_halted events (AC#3)
func TestRiskHandler_Handle_TradingHalted(t *testing.T) {
	handler := NewRiskHandler()

	payload := []byte(`{
		"type": "trading_halted",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Max Drawdown",
		"rule_type": "halted",
		"status": "10% limit reached",
		"action": "All trading paused for this account",
		"required_action": "Manual review before resuming",
		"timestamp": "2026-01-15T14:32:15Z"
	}`)

	msg, err := handler.Handle("ftmo-gold-001", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}
	if msg == "" {
		t.Error("Expected formatted message, got empty string")
	}

	// AC#3: Verify required fields in output
	expectedFields := []string{
		"🔴", "*TRADING HALTED*",
		"FTMO Gold Challenge",
		"Max Drawdown",
		"10% limit reached",
		"All trading paused for this account",
		"Manual review before resuming",
		"14:32:15 UTC",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s', got:\n%s", field, msg)
		}
	}
}

// Test 4.7: Unit tests for invalid JSON handling (graceful error)
func TestRiskHandler_Handle_InvalidJSON(t *testing.T) {
	handler := NewRiskHandler()

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
			payload: []byte(`{"type": "risk_blocked", "account_id":`),
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

// Test unknown risk event type handling
func TestRiskHandler_Handle_UnknownEventType(t *testing.T) {
	handler := NewRiskHandler()

	payload := []byte(`{
		"type": "risk_unknown",
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

// Test risk handler returns immediately (fire-and-forget support)
func TestRiskHandler_Handle_ReturnsImmediately(t *testing.T) {
	handler := NewRiskHandler()

	payload := []byte(`{
		"type": "risk_blocked",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Daily Loss Limit",
		"rule_type": "blocked",
		"current": 4.8,
		"threshold": 5.0,
		"trade": "BUY 0.10 XAUUSD",
		"reason": "Trade would exceed daily loss limit",
		"action": "Trade rejected",
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
	if handler.formatter == nil {
		t.Error("Expected formatter to be initialized")
	}
}

// Test 4.4: EmergencyHandler parses confirmation and returns formatted message
func TestEmergencyHandler_Handle_Confirmation(t *testing.T) {
	handler := NewEmergencyHandler()

	payload := []byte(`{
		"type": "emergency_stop_confirmation",
		"status": "completed",
		"accounts_paused": 3,
		"positions_preserved": 5,
		"orders_cancelled": 2,
		"timestamp": "2026-01-19T14:32:15Z"
	}`)

	msg, err := handler.Handle("", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}
	if msg == "" {
		t.Error("Expected formatted message, got empty string")
	}

	// Verify AC#3 format
	expectedFields := []string{
		"🔴", "*EMERGENCY STOP COMPLETE*",
		"Accounts Paused: 3",
		"Pending Orders: Cancelled",
		"Open Positions: 5 (preserved)",
		"Action: Use /resume_all to restart trading",
		"14:32:15 UTC",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s', got:\n%s", field, msg)
		}
	}
}

// Test EmergencyHandler ignores self-echo (emergency_stop type)
func TestEmergencyHandler_Handle_SelfEcho(t *testing.T) {
	handler := NewEmergencyHandler()

	payload := []byte(`{
		"type": "emergency_stop",
		"command": "stop_all",
		"initiator": "telegram",
		"initiated_by": "@testuser",
		"chat_id": 123456789,
		"timestamp": "2026-01-19T14:32:15Z"
	}`)

	msg, err := handler.Handle("", payload)
	if err != nil {
		t.Errorf("Expected no error for self-echo, got: %v", err)
	}
	// Self-echo returns empty string (no notification)
	if msg != "" {
		t.Errorf("Expected empty message for self-echo, got: %s", msg)
	}
}

// Test EmergencyHandler with invalid JSON
func TestEmergencyHandler_Handle_InvalidJSON(t *testing.T) {
	handler := NewEmergencyHandler()

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
			payload: []byte(`{"type": "emergency_stop_confirmation", "accounts_paused":`),
		},
		{
			name:    "empty payload",
			payload: []byte(``),
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			msg, err := handler.Handle("", tc.payload)
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

// Test EmergencyHandler with unknown event type
func TestEmergencyHandler_Handle_UnknownEventType(t *testing.T) {
	handler := NewEmergencyHandler()

	payload := []byte(`{
		"type": "unknown_emergency_type",
		"data": "something"
	}`)

	msg, err := handler.Handle("", payload)
	// Unknown types return empty without error (logged only)
	if err != nil {
		t.Errorf("Expected no error for unknown type, got: %v", err)
	}
	if msg != "" {
		t.Errorf("Expected empty message for unknown type, got: %s", msg)
	}
}

// Test confirmation with no orders cancelled
func TestEmergencyHandler_Handle_Confirmation_NoOrdersCancelled(t *testing.T) {
	handler := NewEmergencyHandler()

	payload := []byte(`{
		"type": "emergency_stop_confirmation",
		"status": "completed",
		"accounts_paused": 2,
		"positions_preserved": 3,
		"orders_cancelled": 0,
		"timestamp": "2026-01-19T14:32:15Z"
	}`)

	msg, err := handler.Handle("", payload)
	if err != nil {
		t.Fatalf("Expected no error, got: %v", err)
	}

	// Should show "None pending" instead of "Cancelled"
	if !strings.Contains(msg, "Pending Orders: None pending") {
		t.Errorf("Expected 'Pending Orders: None pending' for 0 orders, got:\n%s", msg)
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
