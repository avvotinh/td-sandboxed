package logger

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"testing"
)

func TestNew(t *testing.T) {
	log := New()

	if log == nil {
		t.Fatal("New() returned nil logger")
	}

	// Verify logger is properly configured
	if !log.Enabled(nil, slog.LevelInfo) {
		t.Error("Logger should have Info level enabled")
	}
}

func TestLogFormat(t *testing.T) {
	// Capture log output
	var buf bytes.Buffer

	// Create logger with custom handler writing to buffer
	handler := slog.NewJSONHandler(&buf, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})
	log := slog.New(handler)

	// Log a test message
	log.Info("test message",
		slog.String("event", EventConnectionStarted),
		slog.String("key", "value"),
	)

	// Parse the JSON output
	var logEntry map[string]interface{}
	if err := json.Unmarshal(buf.Bytes(), &logEntry); err != nil {
		t.Fatalf("Failed to parse log as JSON: %v", err)
	}

	// Verify required fields are present
	requiredFields := []string{"time", "level", "msg"}
	for _, field := range requiredFields {
		if _, ok := logEntry[field]; !ok {
			t.Errorf("Log entry missing required field: %s", field)
		}
	}

	// Verify custom fields
	if logEntry["msg"] != "test message" {
		t.Errorf("msg = %v, want 'test message'", logEntry["msg"])
	}

	if logEntry["event"] != EventConnectionStarted {
		t.Errorf("event = %v, want %v", logEntry["event"], EventConnectionStarted)
	}

	if logEntry["key"] != "value" {
		t.Errorf("key = %v, want 'value'", logEntry["key"])
	}
}

func TestEventConstants(t *testing.T) {
	events := []string{
		EventConnectionStarted,
		EventConnectionSuccess,
		EventConnectionFailed,
		EventConnectionLost,
		EventReconnecting,
	}

	for _, event := range events {
		if event == "" {
			t.Errorf("Event constant is empty")
		}
	}

	// Verify all events are unique
	seen := make(map[string]bool)
	for _, event := range events {
		if seen[event] {
			t.Errorf("Duplicate event constant: %s", event)
		}
		seen[event] = true
	}
}
