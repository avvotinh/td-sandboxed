// Package errors provides tests for custom error types.
package errors

import (
	"errors"
	"testing"
)

func TestNotificationError_Error(t *testing.T) {
	tests := []struct {
		name     string
		err      *NotificationError
		expected string
	}{
		{
			name: "with context",
			err: &NotificationError{
				Op:      "SendMessage",
				Err:     ErrMessageSendFailed,
				Context: "chat_id=12345",
			},
			expected: "SendMessage: failed to send message (chat_id=12345)",
		},
		{
			name: "without context",
			err: &NotificationError{
				Op:  "Connect",
				Err: ErrTelegramConnection,
			},
			expected: "Connect: failed to connect to Telegram API",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.err.Error()
			if result != tt.expected {
				t.Errorf("Expected '%s', got '%s'", tt.expected, result)
			}
		})
	}
}

func TestNotificationError_Unwrap(t *testing.T) {
	underlying := ErrRedisConnection
	err := &NotificationError{
		Op:  "Subscribe",
		Err: underlying,
	}

	if !errors.Is(err, underlying) {
		t.Error("Expected Unwrap to return underlying error")
	}
}

func TestWrap(t *testing.T) {
	err := Wrap("TestOp", ErrMissingConfig, "token not set")

	notifErr, ok := err.(*NotificationError)
	if !ok {
		t.Fatal("Expected NotificationError type")
	}

	if notifErr.Op != "TestOp" {
		t.Errorf("Expected Op 'TestOp', got '%s'", notifErr.Op)
	}
	if notifErr.Context != "token not set" {
		t.Errorf("Expected Context 'token not set', got '%s'", notifErr.Context)
	}
	if !errors.Is(notifErr, ErrMissingConfig) {
		t.Error("Expected underlying error to be ErrMissingConfig")
	}
}

func TestSentinelErrors(t *testing.T) {
	// Verify sentinel errors are distinct
	sentinels := []error{
		ErrTelegramConnection,
		ErrRedisConnection,
		ErrMissingConfig,
		ErrMessageSendFailed,
	}

	for i, err1 := range sentinels {
		for j, err2 := range sentinels {
			if i != j && errors.Is(err1, err2) {
				t.Errorf("Sentinel errors %d and %d should not be equal", i, j)
			}
		}
	}
}
