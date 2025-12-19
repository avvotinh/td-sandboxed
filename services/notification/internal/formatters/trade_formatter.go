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

// TradeCloseEvent represents a trade close event.
type TradeCloseEvent struct {
	TradeEvent
	Result   string  `json:"result"` // PROFIT, LOSS
	PnL      float64 `json:"pnl"`
	PnLPct   float64 `json:"pnl_pct"`
	Duration string  `json:"duration"`
}

// TradeFormatter formats trade notifications.
type TradeFormatter struct{}

// NewTradeFormatter creates a new trade formatter.
func NewTradeFormatter() *TradeFormatter {
	return &TradeFormatter{}
}

// FormatOpen formats a trade open notification.
func (f *TradeFormatter) FormatOpen(e *TradeEvent) string {
	return fmt.Sprintf(`*TRADE EXECUTED*
Account: %s
Symbol: %s
Action: %s %.2f lots
Entry: $%.2f
SL: $%.2f | TP: $%.2f
Reason: %s
Daily P&L: $%.2f (%.2f%%)
Time: %s`,
		e.AccountName,
		e.Symbol,
		e.Action, e.Volume,
		e.Price,
		e.SL, e.TP,
		e.Reason,
		e.DailyPnL, e.DailyPnLPct,
		e.Timestamp)
}

// FormatClose formats a trade close notification.
func (f *TradeFormatter) FormatClose(e *TradeCloseEvent) string {
	emoji := ""
	if e.Result == "PROFIT" {
		emoji = "+"
	} else {
		emoji = "-"
	}

	return fmt.Sprintf(`%s *TRADE CLOSED - %s*
Account: %s
Symbol: %s
P&L: $%.2f (%.2f%%)
Duration: %s
Time: %s`,
		emoji, e.Result,
		e.AccountName,
		e.Symbol,
		e.PnL, e.PnLPct,
		e.Duration,
		time.Now().UTC().Format("15:04:05 UTC"))
}
