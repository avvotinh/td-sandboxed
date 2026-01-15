// Package formatters provides alert message formatters for Telegram.
//
// Formats risk and system alerts for Telegram.
package formatters

import (
	"fmt"
	"strings"
	"time"
)

// RiskBlockedEvent represents a trade blocked by risk rule.
type RiskBlockedEvent struct {
	Type        string  `json:"type"`         // "risk_blocked"
	AccountID   string  `json:"account_id"`
	AccountName string  `json:"account_name"`
	RuleName    string  `json:"rule_name"`
	RuleType    string  `json:"rule_type"`    // "blocked"
	Current     float64 `json:"current"`
	Threshold   float64 `json:"threshold"`
	Trade       string  `json:"trade"`
	Reason      string  `json:"reason"`
	Action      string  `json:"action"`
	Timestamp   string  `json:"timestamp"`
}

// RiskWarningEvent represents a risk warning threshold reached.
type RiskWarningEvent struct {
	Type             string  `json:"type"`              // "risk_warning"
	AccountID        string  `json:"account_id"`
	AccountName      string  `json:"account_name"`
	RuleName         string  `json:"rule_name"`
	RuleType         string  `json:"rule_type"`         // "warning"
	Current          float64 `json:"current"`
	Threshold        float64 `json:"threshold"`
	WarningLevel     int     `json:"warning_level"`     // 80 for 80% of limit
	RemainingDollars float64 `json:"remaining_dollars"` // Dollar amount remaining
	Action           string  `json:"action"`            // "Trading continues, monitor closely"
	Timestamp        string  `json:"timestamp"`
}

// TradingHaltedEvent represents trading halted due to critical limit breach.
type TradingHaltedEvent struct {
	Type           string `json:"type"`            // "trading_halted"
	AccountID      string `json:"account_id"`
	AccountName    string `json:"account_name"`
	RuleName       string `json:"rule_name"`
	RuleType       string `json:"rule_type"`       // "halted"
	Status         string `json:"status"`          // "10% limit reached"
	Action         string `json:"action"`          // "All trading paused for this account"
	RequiredAction string `json:"required_action"` // "Manual review before resuming"
	Timestamp      string `json:"timestamp"`
}

// SystemAlert represents a system-level alert.
type SystemAlert struct {
	Component string `json:"component"`
	Level     string `json:"level"` // info, warning, error
	Message   string `json:"message"`
	Action    string `json:"action,omitempty"`
	Timestamp string `json:"timestamp"`
}

// AlertFormatter formats alert notifications.
type AlertFormatter struct{}

// NewAlertFormatter creates a new alert formatter.
func NewAlertFormatter() *AlertFormatter {
	return &AlertFormatter{}
}

// FormatRiskWarning formats a risk warning alert with emoji.
func (f *AlertFormatter) FormatRiskWarning(e *RiskWarningEvent) string {
	remaining := e.Threshold - e.Current

	return fmt.Sprintf(`🟡 *RISK WARNING*
Account: %s
Rule: %s
Status: %d%% of limit reached
Current: %.1f%% of %.1f%% limit
Remaining: $%.0f (%.1f%%)
Action: %s
Time: %s`,
		e.AccountName,
		e.RuleName,
		e.WarningLevel,
		e.Current, e.Threshold,
		e.RemainingDollars, remaining,
		e.Action,
		formatAlertTimestamp(e.Timestamp))
}

// FormatRiskBlocked formats a trade blocked alert with emoji.
func (f *AlertFormatter) FormatRiskBlocked(e *RiskBlockedEvent) string {
	return fmt.Sprintf(`🔴 *TRADE BLOCKED*
Account: %s
Rule: %s
Current: %.1f%% of %.1f%% limit
Trade: %s
Reason: %s
Action: %s
Time: %s`,
		e.AccountName,
		e.RuleName,
		e.Current, e.Threshold,
		e.Trade,
		e.Reason,
		e.Action,
		formatAlertTimestamp(e.Timestamp))
}

// FormatTradingHalted formats a trading halted alert with emoji.
func (f *AlertFormatter) FormatTradingHalted(e *TradingHaltedEvent) string {
	return fmt.Sprintf(`🔴 *TRADING HALTED*
Account: %s
Rule: %s
Status: %s
Action: %s
Required: %s
Time: %s`,
		e.AccountName,
		e.RuleName,
		e.Status,
		e.Action,
		e.RequiredAction,
		formatAlertTimestamp(e.Timestamp))
}

// FormatSystemAlert formats a system alert.
func (f *AlertFormatter) FormatSystemAlert(a *SystemAlert) string {
	level := strings.ToUpper(a.Level)

	msg := fmt.Sprintf(`*SYSTEM %s*
Component: %s
Message: %s`,
		level,
		a.Component,
		a.Message)

	if a.Action != "" {
		msg += fmt.Sprintf("\nAction: %s", a.Action)
	}

	msg += fmt.Sprintf("\nTime: %s", formatAlertTimestamp(a.Timestamp))

	return msg
}

// formatAlertTimestamp formats ISO timestamp to readable UTC format.
func formatAlertTimestamp(ts string) string {
	t, err := time.Parse(time.RFC3339, ts)
	if err != nil {
		return ts // Return original if parse fails
	}
	return t.UTC().Format("15:04:05 UTC")
}
