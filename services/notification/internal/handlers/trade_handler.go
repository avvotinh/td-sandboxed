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

// Handle processes a trade event message.
// Scaffold: Just logs the event.
func (h *TradeHandler) Handle(accountID string, payload []byte) error {
	log.Printf("Trade event for account %s (scaffold): %s", accountID, string(payload))
	return nil
}
