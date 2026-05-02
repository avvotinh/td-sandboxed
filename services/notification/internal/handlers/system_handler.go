// Package handlers provides system alert handler.
//
// Scaffold placeholder. Full implementation in later stories.
package handlers

import (
	"log"
)

// SystemHandler processes system-wide alert events.
type SystemHandler struct{}

// NewSystemHandler creates a new system handler.
func NewSystemHandler() *SystemHandler {
	return &SystemHandler{}
}

// Handle processes a system alert message and returns formatted notification text.
// Scaffold: Returns placeholder message.
func (h *SystemHandler) Handle(accountID string, payload []byte) (string, error) {
	log.Printf("System alert received: %s", string(payload))
	// Scaffold: Return empty string (no notification sent)
	// Full implementation will parse JSON and format message
	return "", nil
}
