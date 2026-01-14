// Package handlers provides emergency stop handler.
//
// Scaffold placeholder. Full implementation in Story 6.5.
package handlers

import (
	"log"
)

// EmergencyHandler processes emergency stop commands.
type EmergencyHandler struct{}

// NewEmergencyHandler creates a new emergency handler.
func NewEmergencyHandler() *EmergencyHandler {
	return &EmergencyHandler{}
}

// Handle processes an emergency stop message and returns formatted notification text.
// Scaffold: Returns placeholder message. Full implementation in Story 6.5.
func (h *EmergencyHandler) Handle(accountID string, payload []byte) (string, error) {
	log.Printf("Emergency stop received: %s", string(payload))
	// Scaffold: Return empty string (no notification sent)
	// Full implementation in Story 6.5 will:
	// 1. Parse JSON payload
	// 2. Trigger emergency stop across all accounts
	// 3. Return formatted alert message
	return "", nil
}
