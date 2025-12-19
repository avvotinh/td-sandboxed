// Package formatters provides alert message formatters for Telegram.
//
// Formats risk and system alerts for Telegram.
package formatters

import (
	"fmt"
	"strings"
	"time"
)

// RiskAlert represents a risk warning or violation.
type RiskAlert struct {
	AccountID   string  `json:"account_id"`
	AccountName string  `json:"account_name"`
	RuleName    string  `json:"rule_name"`
	RuleType    string  `json:"rule_type"` // warning, blocked
	Current     float64 `json:"current"`
	Threshold   float64 `json:"threshold"`
	Trade       string  `json:"trade,omitempty"`
	Reason      string  `json:"reason"`
	Action      string  `json:"action"`
	Timestamp   string  `json:"timestamp"`
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

// FormatRiskWarning formats a risk warning alert.
func (f *AlertFormatter) FormatRiskWarning(a *RiskAlert) string {
	return fmt.Sprintf(`*RISK WARNING*
Account: %s
Rule: %s
Status: %.0f%% of limit reached
Current: %.1f%% of %.1f%% limit
Remaining: %.1f%%
Time: %s`,
		a.AccountName,
		a.RuleName,
		(a.Current/a.Threshold)*100,
		a.Current, a.Threshold,
		a.Threshold-a.Current,
		time.Now().UTC().Format("15:04:05 UTC"))
}

// FormatRiskBlocked formats a trade blocked alert.
func (f *AlertFormatter) FormatRiskBlocked(a *RiskAlert) string {
	return fmt.Sprintf(`*TRADE BLOCKED*
Account: %s
Rule: %s
Current: %.1f%% of %.1f%% limit
Trade: %s
Reason: %s
Action: %s
Time: %s`,
		a.AccountName,
		a.RuleName,
		a.Current, a.Threshold,
		a.Trade,
		a.Reason,
		a.Action,
		time.Now().UTC().Format("15:04:05 UTC"))
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

	msg += fmt.Sprintf("\nTime: %s", time.Now().UTC().Format("15:04:05 UTC"))

	return msg
}
