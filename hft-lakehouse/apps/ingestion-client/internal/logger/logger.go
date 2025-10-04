package logger

import (
	"log/slog"
	"os"
)

// New creates a new structured logger with JSON output
// Following Coding Standard Rule #3: Use structured logging only
func New() *slog.Logger {
	// Create JSON handler for structured logging
	handler := slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})

	return slog.New(handler)
}

// Event types for connection lifecycle
const (
	EventConnectionStarted = "connection_started"
	EventConnectionSuccess = "connection_success"
	EventConnectionFailed  = "connection_failed"
	EventConnectionLost    = "connection_lost"
	EventReconnecting      = "reconnecting"
)
