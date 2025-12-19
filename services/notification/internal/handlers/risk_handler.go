// Package handlers provides risk alert handler.
//
// Scaffold placeholder. Full implementation in Story 6.4.
package handlers

import (
	"log"

	"github.com/user/sandboxed/services/notification/internal/formatters"
)

// RiskHandler processes risk alert events.
type RiskHandler struct {
	formatter *formatters.AlertFormatter
}

// NewRiskHandler creates a new risk handler.
func NewRiskHandler() *RiskHandler {
	return &RiskHandler{
		formatter: formatters.NewAlertFormatter(),
	}
}

// Handle processes a risk alert message.
// Scaffold: Just logs the event.
func (h *RiskHandler) Handle(accountID string, payload []byte) error {
	log.Printf("Risk alert for account %s (scaffold): %s", accountID, string(payload))
	return nil
}
