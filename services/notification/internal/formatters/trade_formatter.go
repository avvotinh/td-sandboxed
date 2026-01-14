// Package formatters provides message formatters for Telegram notifications.
//
// Formats trade execution notifications for Telegram.
package formatters

import (
	"fmt"
	"time"
)

// TradeEvent represents a trade execution event.
type TradeEvent struct {
	Type        string  `json:"type"`
	AccountID   string  `json:"account_id"`
	AccountName string  `json:"account_name"`
	Symbol      string  `json:"symbol"`
	Action      string  `json:"action"` // BUY, SELL
	Volume      float64 `json:"volume"`
	Price       float64 `json:"price"`
	SL          float64 `json:"sl,omitempty"`
	TP          float64 `json:"tp,omitempty"`
	Reason      string  `json:"reason"`
	DailyPnL    float64 `json:"daily_pnl"`
	DailyPnLPct float64 `json:"daily_pnl_pct"`
	Timestamp   string  `json:"timestamp"`
}

// TradeCloseEvent represents a trade close event with flat structure.
type TradeCloseEvent struct {
	Type        string  `json:"type"`
	AccountID   string  `json:"account_id"`
	AccountName string  `json:"account_name"`
	Symbol      string  `json:"symbol"`
	Action      string  `json:"action"`
	Volume      float64 `json:"volume"`
	EntryPrice  float64 `json:"entry_price"`
	ExitPrice   float64 `json:"exit_price"`
	PnL         float64 `json:"pnl"`
	PnLPct      float64 `json:"pnl_pct"`
	Result      string  `json:"result"` // PROFIT, LOSS
	Duration    string  `json:"duration"`
	DailyPnL    float64 `json:"daily_pnl"`
	DailyPnLPct float64 `json:"daily_pnl_pct"`
	Timestamp   string  `json:"timestamp"`
}

// TradeFormatter formats trade notifications.
type TradeFormatter struct{}

// NewTradeFormatter creates a new trade formatter.
func NewTradeFormatter() *TradeFormatter {
	return &TradeFormatter{}
}

// FormatOpen formats a trade open notification with emoji.
func (f *TradeFormatter) FormatOpen(e *TradeEvent) string {
	return fmt.Sprintf(`🔵 *TRADE EXECUTED*
Account: %s
Symbol: %s
Action: %s %.2f lots
Entry: $%.2f
SL: $%.2f | TP: $%.2f
Reason: %s
Daily P&L: %s (%.2f%%)
Time: %s`,
		e.AccountName,
		e.Symbol,
		e.Action, e.Volume,
		e.Price,
		e.SL, e.TP,
		e.Reason,
		formatMoney(e.DailyPnL), e.DailyPnLPct,
		formatTimestamp(e.Timestamp))
}

// FormatClose formats a trade close notification with result emoji.
func (f *TradeFormatter) FormatClose(e *TradeCloseEvent) string {
	emoji := "🔴"
	if e.Result == "PROFIT" {
		emoji = "🟢"
	}

	return fmt.Sprintf(`%s *TRADE CLOSED - %s*
Account: %s
Symbol: %s
Action: %s %.2f lots (close)
Entry: $%.2f → Exit: $%.2f
P&L: %s
Daily P&L: %s (%.2f%%)
Time: %s`,
		emoji, e.Result,
		e.AccountName,
		e.Symbol,
		e.Action, e.Volume,
		e.EntryPrice, e.ExitPrice,
		formatMoneyWithSign(e.PnL),
		formatMoney(e.DailyPnL), e.DailyPnLPct,
		formatTimestamp(e.Timestamp))
}

// formatMoney formats a money value with dollar sign and proper negative handling.
func formatMoney(value float64) string {
	if value < 0 {
		return fmt.Sprintf("-$%.2f", -value)
	}
	return fmt.Sprintf("$%.2f", value)
}

// formatMoneyWithSign formats money with explicit + or - sign.
func formatMoneyWithSign(value float64) string {
	if value >= 0 {
		return fmt.Sprintf("+$%.2f", value)
	}
	return fmt.Sprintf("-$%.2f", -value)
}

// formatTimestamp formats ISO timestamp to readable UTC format.
func formatTimestamp(ts string) string {
	t, err := time.Parse(time.RFC3339, ts)
	if err != nil {
		return ts // Return original if parse fails
	}
	return t.UTC().Format("15:04:05 UTC")
}
