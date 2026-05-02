// Package handlers provides message handlers for notifications.
package handlers

import (
	"encoding/json"
	"log"

	"github.com/user/sandboxed/services/notification/internal/errors"
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

// baseTradeEvent contains the type field for routing.
type baseTradeEvent struct {
	Type string `json:"type"`
}

// Handle processes a trade event message and returns formatted notification text.
func (h *TradeHandler) Handle(accountID string, payload []byte) (string, error) {
	// First, determine event type
	var base baseTradeEvent
	if err := json.Unmarshal(payload, &base); err != nil {
		log.Printf("Failed to parse trade event base: %v", err)
		return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
	}

	switch base.Type {
	case "trade_opened":
		var event formatters.TradeEvent
		if err := json.Unmarshal(payload, &event); err != nil {
			log.Printf("Failed to parse trade_opened event: %v", err)
			return "", errors.Wrap("Handle", errors.ErrInvalidTradeEvent, err.Error())
		}
		return h.formatter.FormatOpen(&event), nil

	case "trade_closed":
		var event formatters.TradeCloseEvent
		if err := json.Unmarshal(payload, &event); err != nil {
			log.Printf("Failed to parse trade_closed event: %v", err)
			return "", errors.Wrap("Handle", errors.ErrInvalidTradeEvent, err.Error())
		}
		return h.formatter.FormatClose(&event), nil

	default:
		log.Printf("Unknown trade event type: %s", base.Type)
		return "", errors.Wrap("Handle", errors.ErrUnknownEventType, base.Type)
	}
}
