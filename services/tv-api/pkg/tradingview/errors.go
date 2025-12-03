package tradingview

import "fmt"

// ErrorType represents the category of error that occurred.
type ErrorType string

const (
	// ErrAuth indicates an authentication failure.
	ErrAuth ErrorType = "authentication_error"

	// ErrConnection indicates a WebSocket connection error.
	ErrConnection ErrorType = "connection_error"

	// ErrProtocol indicates a protocol parsing or packet format error.
	ErrProtocol ErrorType = "protocol_error"

	// ErrSession indicates a session management error.
	ErrSession ErrorType = "session_error"
)

// TradingViewError represents an error that occurred in the TradingView API.
type TradingViewError struct {
	Type    ErrorType
	Message string
	Cause   error
}

// Error returns the error message.
func (e *TradingViewError) Error() string {
	if e.Cause != nil {
		return fmt.Sprintf("%s: %s: %v", e.Type, e.Message, e.Cause)
	}
	return fmt.Sprintf("%s: %s", e.Type, e.Message)
}

// Unwrap returns the underlying cause of the error.
func (e *TradingViewError) Unwrap() error {
	return e.Cause
}

// NewAuthError creates a new authentication error.
func NewAuthError(message string, cause error) *TradingViewError {
	return &TradingViewError{
		Type:    ErrAuth,
		Message: message,
		Cause:   cause,
	}
}

// NewConnectionError creates a new connection error.
func NewConnectionError(message string, cause error) *TradingViewError {
	return &TradingViewError{
		Type:    ErrConnection,
		Message: message,
		Cause:   cause,
	}
}

// NewProtocolError creates a new protocol error.
func NewProtocolError(message string, cause error) *TradingViewError {
	return &TradingViewError{
		Type:    ErrProtocol,
		Message: message,
		Cause:   cause,
	}
}

// NewSessionError creates a new session error.
func NewSessionError(message string, cause error) *TradingViewError {
	return &TradingViewError{
		Type:    ErrSession,
		Message: message,
		Cause:   cause,
	}
}
