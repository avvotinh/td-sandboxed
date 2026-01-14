// Package errors provides custom error types for the notification service.
package errors

import (
	"errors"
	"fmt"
)

// Sentinel errors for common failure cases.
var (
	// ErrTelegramConnection indicates failure to connect to Telegram API.
	ErrTelegramConnection = errors.New("failed to connect to Telegram API")

	// ErrRedisConnection indicates failure to connect to Redis.
	ErrRedisConnection = errors.New("failed to connect to Redis")

	// ErrSubscriptionFailed indicates failure to subscribe to Redis channels.
	ErrSubscriptionFailed = errors.New("failed to subscribe to Redis channels")

	// ErrMessageParseError indicates failure to parse a message payload.
	ErrMessageParseError = errors.New("failed to parse message payload")

	// ErrMissingConfig indicates required configuration is missing.
	ErrMissingConfig = errors.New("required configuration missing")

	// ErrMessageSendFailed indicates a message could not be sent.
	ErrMessageSendFailed = errors.New("failed to send message")

	// ErrInvalidTradeEvent indicates the trade event payload is malformed.
	ErrInvalidTradeEvent = errors.New("invalid trade event payload")

	// ErrUnknownEventType indicates an unrecognized event type in the payload.
	ErrUnknownEventType = errors.New("unknown event type")
)

// NotificationError wraps errors with additional context.
type NotificationError struct {
	Op      string // Operation that failed
	Err     error  // Underlying error
	Context string // Additional context
}

func (e *NotificationError) Error() string {
	if e.Context != "" {
		return fmt.Sprintf("%s: %s (%s)", e.Op, e.Err.Error(), e.Context)
	}
	return fmt.Sprintf("%s: %s", e.Op, e.Err.Error())
}

func (e *NotificationError) Unwrap() error {
	return e.Err
}

// Wrap creates a NotificationError with context.
func Wrap(op string, err error, context string) error {
	return &NotificationError{Op: op, Err: err, Context: context}
}
