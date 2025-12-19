// Package handlers provides tests for message handlers.
package handlers

import (
	"testing"
)

func TestNewTradeHandler(t *testing.T) {
	handler := NewTradeHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
	if handler.formatter == nil {
		t.Error("Expected formatter to be initialized")
	}
}

func TestTradeHandler_Handle(t *testing.T) {
	handler := NewTradeHandler()

	// Scaffold mode just logs, should not error
	err := handler.Handle("ftmo-001", []byte(`{"symbol":"XAUUSD","action":"BUY"}`))
	if err != nil {
		t.Errorf("Expected no error, got: %v", err)
	}
}

func TestNewRiskHandler(t *testing.T) {
	handler := NewRiskHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
	if handler.formatter == nil {
		t.Error("Expected formatter to be initialized")
	}
}

func TestRiskHandler_Handle(t *testing.T) {
	handler := NewRiskHandler()

	// Scaffold mode just logs, should not error
	err := handler.Handle("ftmo-001", []byte(`{"rule":"daily_loss","current":4.5}`))
	if err != nil {
		t.Errorf("Expected no error, got: %v", err)
	}
}

func TestNewHealthHandler(t *testing.T) {
	handler := NewHealthHandler()
	if handler == nil {
		t.Error("Expected handler to be created, got nil")
	}
}

func TestHealthHandler_Handle(t *testing.T) {
	handler := NewHealthHandler()

	// Scaffold mode just logs, should not error
	err := handler.Handle([]byte(`{"component":"redis","status":"healthy"}`))
	if err != nil {
		t.Errorf("Expected no error, got: %v", err)
	}
}
