// Package formatters provides tests for alert message formatting.
package formatters

import (
	"strings"
	"testing"
)

func TestAlertFormatter_FormatRiskWarning(t *testing.T) {
	formatter := NewAlertFormatter()

	alert := &RiskAlert{
		AccountID:   "ftmo-001",
		AccountName: "FTMO Gold",
		RuleName:    "Daily Loss Limit",
		RuleType:    "warning",
		Current:     4.2,
		Threshold:   5.0,
	}

	result := formatter.FormatRiskWarning(alert)

	if !strings.Contains(result, "RISK WARNING") {
		t.Error("Expected 'RISK WARNING' in output")
	}
	if !strings.Contains(result, "FTMO Gold") {
		t.Error("Expected account name in output")
	}
	if !strings.Contains(result, "Daily Loss Limit") {
		t.Error("Expected rule name in output")
	}
}

func TestAlertFormatter_FormatRiskBlocked(t *testing.T) {
	formatter := NewAlertFormatter()

	alert := &RiskAlert{
		AccountID:   "ftmo-001",
		AccountName: "FTMO Gold",
		RuleName:    "Max Drawdown",
		RuleType:    "blocked",
		Current:     10.1,
		Threshold:   10.0,
		Trade:       "BUY 0.1 XAUUSD",
		Reason:      "Drawdown limit exceeded",
		Action:      "Trade rejected",
	}

	result := formatter.FormatRiskBlocked(alert)

	if !strings.Contains(result, "TRADE BLOCKED") {
		t.Error("Expected 'TRADE BLOCKED' in output")
	}
	if !strings.Contains(result, "Max Drawdown") {
		t.Error("Expected rule name in output")
	}
	if !strings.Contains(result, "Trade rejected") {
		t.Error("Expected action in output")
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
			},
			expected: "SYSTEM ERROR",
		},
		{
			name: "warning level",
			alert: &SystemAlert{
				Component: "Redis",
				Level:     "warning",
				Message:   "High memory usage",
			},
			expected: "SYSTEM WARNING",
		},
		{
			name: "info level",
			alert: &SystemAlert{
				Component: "Trading Engine",
				Level:     "info",
				Message:   "Started successfully",
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
