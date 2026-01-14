// Package handlers provides message handlers for notifications.
//
// Scaffold placeholder. Full implementation in Story 6.3.
package handlers

import (
	"log"

	"github.com/user/sandboxed/services/notification/internal/formatters"
)

// TradeHandler processes trade execution events.
type TradeHandler struct {
	formatter *formatters.TradeFormatter
}

// NewTradeHandler creates a new trade handler.
func NewTradeHandler() *TradeHandler {
	return &TradeHandler{
		formatter: formatters.NewTradeFormatter(),
	}
}

// Handle processes a trade event message and returns formatted notification text.
// Scaffold: Returns placeholder message. Full implementation in Story 6.3.
func (h *TradeHandler) Handle(accountID string, payload []byte) (string, error) {
	log.Printf("Trade event for account %s: %s", accountID, string(payload))
	// Scaffold: Return empty string (no notification sent)
	// Full implementation in Story 6.3 will parse JSON and format message
	return "", nil
}
