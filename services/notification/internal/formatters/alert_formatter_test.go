// Package formatters provides tests for alert message formatting.
package formatters

import (
	"strings"
	"testing"
)

func TestAlertFormatter_FormatRiskWarning(t *testing.T) {
	formatter := NewAlertFormatter()

	event := &RiskWarningEvent{
		Type:             "risk_warning",
		AccountID:        "ftmo-gold-001",
		AccountName:      "FTMO Gold Challenge",
		RuleName:         "Daily Loss Limit",
		RuleType:         "warning",
		Current:          4.0,
		Threshold:        5.0,
		WarningLevel:     80,
		RemainingDollars: 1000.00,
		Action:           "Trading continues, monitor closely",
		Timestamp:        "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatRiskWarning(event)

	// AC#2: Verify exact format
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
		if !strings.Contains(result, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, result)
		}
	}
}

func TestAlertFormatter_FormatRiskBlocked(t *testing.T) {
	formatter := NewAlertFormatter()

	event := &RiskBlockedEvent{
		Type:        "risk_blocked",
		AccountID:   "ftmo-gold-001",
		AccountName: "FTMO Gold Challenge",
		RuleName:    "Daily Loss Limit",
		RuleType:    "blocked",
		Current:     4.8,
		Threshold:   5.0,
		Trade:       "BUY 0.10 XAUUSD",
		Reason:      "Trade would exceed daily loss limit",
		Action:      "Trade rejected",
		Timestamp:   "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatRiskBlocked(event)

	// AC#1: Verify exact format
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
		if !strings.Contains(result, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, result)
		}
	}
}

func TestAlertFormatter_FormatTradingHalted(t *testing.T) {
	formatter := NewAlertFormatter()

	event := &TradingHaltedEvent{
		Type:           "trading_halted",
		AccountID:      "ftmo-gold-001",
		AccountName:    "FTMO Gold Challenge",
		RuleName:       "Max Drawdown",
		RuleType:       "halted",
		Status:         "10% limit reached",
		Action:         "All trading paused for this account",
		RequiredAction: "Manual review before resuming",
		Timestamp:      "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatTradingHalted(event)

	// AC#3: Verify exact format
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
		if !strings.Contains(result, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, result)
		}
	}
}

func TestAlertFormatter_FormatSystemAlert(t *testing.T) {
	formatter := NewAlertFormatter()

	tests := []struct {
		name     string
		alert    *SystemAlert
		expected string
	}{
		{
			name: "error level",
			alert: &SystemAlert{
				Component: "MT5-Bridge",
				Level:     "error",
				Message:   "Connection lost",
				Action:    "Reconnecting",
				Timestamp: "2026-01-15T14:32:15Z",
			},
			expected: "SYSTEM ERROR",
		},
		{
			name: "warning level",
			alert: &SystemAlert{
				Component: "Redis",
				Level:     "warning",
				Message:   "High memory usage",
				Timestamp: "2026-01-15T14:32:15Z",
			},
			expected: "SYSTEM WARNING",
		},
		{
			name: "info level",
			alert: &SystemAlert{
				Component: "Trading Engine",
				Level:     "info",
				Message:   "Started successfully",
				Timestamp: "2026-01-15T14:32:15Z",
			},
			expected: "SYSTEM INFO",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := formatter.FormatSystemAlert(tt.alert)
			if !strings.Contains(result, tt.expected) {
				t.Errorf("Expected '%s' in output, got: %s", tt.expected, result)
			}
			if !strings.Contains(result, tt.alert.Component) {
				t.Errorf("Expected component '%s' in output", tt.alert.Component)
			}
		})
	}
}

func TestAlertFormatter_FormatSystemAlert_WithAction(t *testing.T) {
	formatter := NewAlertFormatter()

	alert := &SystemAlert{
		Component: "MT5-Bridge",
		Level:     "error",
		Message:   "Connection lost",
		Action:    "Reconnecting in 5s",
		Timestamp: "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatSystemAlert(alert)

	if !strings.Contains(result, "Action:") {
		t.Error("Expected 'Action:' in output when action is set")
	}
	if !strings.Contains(result, "Reconnecting in 5s") {
		t.Error("Expected action text in output")
	}
}

func TestNewAlertFormatter(t *testing.T) {
	formatter := NewAlertFormatter()
	if formatter == nil {
		t.Error("Expected formatter to be created, got nil")
	}
}

func TestFormatAlertTimestamp(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{
		{
			name:     "valid RFC3339",
			input:    "2026-01-15T14:32:15Z",
			expected: "14:32:15 UTC",
		},
		{
			name:     "with timezone offset",
			input:    "2026-01-15T16:32:15+02:00",
			expected: "14:32:15 UTC",
		},
		{
			name:     "invalid format",
			input:    "not a timestamp",
			expected: "not a timestamp", // Returns original on parse failure
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := formatAlertTimestamp(tt.input)
			if result != tt.expected {
				t.Errorf("Expected '%s', got '%s'", tt.expected, result)
			}
		})
	}
}

// Test warning percentage remaining calculation
func TestAlertFormatter_FormatRiskWarning_RemainingCalculation(t *testing.T) {
	formatter := NewAlertFormatter()

	event := &RiskWarningEvent{
		Type:             "risk_warning",
		AccountID:        "ftmo-gold-001",
		AccountName:      "FTMO Gold Challenge",
		RuleName:         "Daily Loss Limit",
		RuleType:         "warning",
		Current:          4.5,
		Threshold:        5.0,
		WarningLevel:     90,
		RemainingDollars: 500.00,
		Action:           "Trading continues, monitor closely",
		Timestamp:        "2026-01-15T14:32:15Z",
	}

	result := formatter.FormatRiskWarning(event)

	// Should show $500 (0.5%)
	if !strings.Contains(result, "$500 (0.5%)") {
		t.Errorf("Expected remaining '$500 (0.5%%)', got:\n%s", result)
	}
	if !strings.Contains(result, "90% of limit reached") {
		t.Errorf("Expected '90%% of limit reached', got:\n%s", result)
	}
}
