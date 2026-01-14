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

// Handle processes a risk alert message and returns formatted notification text.
// Scaffold: Returns placeholder message. Full implementation in Story 6.4.
func (h *RiskHandler) Handle(accountID string, payload []byte) (string, error) {
	log.Printf("Risk alert for account %s: %s", accountID, string(payload))
	// Scaffold: Return empty string (no notification sent)
	// Full implementation in Story 6.4 will parse JSON and format message
	return "", nil
}
