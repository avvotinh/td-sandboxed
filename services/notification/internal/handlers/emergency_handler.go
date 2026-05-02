// Package handlers provides emergency stop handler.
package handlers

import (
	"encoding/json"
	"log"

	"github.com/user/sandboxed/services/notification/internal/errors"
	"github.com/user/sandboxed/services/notification/internal/formatters"
)

// EmergencyHandler processes emergency stop commands and confirmations.
type EmergencyHandler struct {
	formatter *formatters.AlertFormatter
}

// NewEmergencyHandler creates a new emergency handler.
func NewEmergencyHandler() *EmergencyHandler {
	return &EmergencyHandler{
		formatter: formatters.NewAlertFormatter(),
	}
}

// Handle processes an emergency stop message and returns formatted notification text.
// Routes based on message type:
// - "emergency_stop": Self-echo from command, ignored (returns empty string)
// - "emergency_stop_confirmation": Confirmation from trading engine, formatted for Telegram
func (h *EmergencyHandler) Handle(accountID string, payload []byte) (string, error) {
	// Parse base type to determine message kind
	var base struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(payload, &base); err != nil {
		return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
	}

	log.Printf("Emergency handler processing type: %s", base.Type)

	switch base.Type {
	case "emergency_stop":
		// Self-echo of our command, ignore
		log.Printf("Ignoring self-echo of emergency_stop command")
		return "", nil

	case "emergency_stop_confirmation":
		var event formatters.EmergencyStopConfirmation
		if err := json.Unmarshal(payload, &event); err != nil {
			return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
		}
		log.Printf("Emergency stop confirmed: %d accounts paused, %d positions preserved",
			event.AccountsPaused, event.PositionsPreserved)
		return h.formatter.FormatEmergencyStopConfirmation(&event), nil

	case "resume_command":
		// Self-echo of our command, ignore
		log.Printf("Ignoring self-echo of resume_command")
		return "", nil

	case "resume_confirmation":
		var event formatters.ResumeConfirmation
		if err := json.Unmarshal(payload, &event); err != nil {
			return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
		}
		log.Printf("Resume confirmed: %d accounts restarted", event.AccountsRestarted)
		return h.formatter.FormatResumeConfirmation(&event), nil

	default:
		log.Printf("Unknown emergency event type: %s", base.Type)
		return "", nil
	}
}
