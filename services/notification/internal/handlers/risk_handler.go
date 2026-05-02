// Package handlers provides risk alert handler.
//
// Processes risk alert events from Redis and formats notifications.
package handlers

import (
	"encoding/json"
	"log"

	"github.com/user/sandboxed/services/notification/internal/errors"
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

// baseRiskEvent contains the type field for routing.
type baseRiskEvent struct {
	Type string `json:"type"`
}

// Handle processes a risk alert message and returns formatted notification text.
func (h *RiskHandler) Handle(accountID string, payload []byte) (string, error) {
	// First, determine event type
	var base baseRiskEvent
	if err := json.Unmarshal(payload, &base); err != nil {
		log.Printf("Failed to parse risk event base: %v", err)
		return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
	}

	switch base.Type {
	case "risk_blocked":
		var event formatters.RiskBlockedEvent
		if err := json.Unmarshal(payload, &event); err != nil {
			log.Printf("Failed to parse risk_blocked event: %v", err)
			return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
		}
		return h.formatter.FormatRiskBlocked(&event), nil

	case "risk_warning":
		var event formatters.RiskWarningEvent
		if err := json.Unmarshal(payload, &event); err != nil {
			log.Printf("Failed to parse risk_warning event: %v", err)
			return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
		}
		return h.formatter.FormatRiskWarning(&event), nil

	case "trading_halted":
		var event formatters.TradingHaltedEvent
		if err := json.Unmarshal(payload, &event); err != nil {
			log.Printf("Failed to parse trading_halted event: %v", err)
			return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
		}
		return h.formatter.FormatTradingHalted(&event), nil

	default:
		log.Printf("Unknown risk event type: %s", base.Type)
		return "", errors.Wrap("Handle", errors.ErrUnknownEventType, base.Type)
	}
}
