package session

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/cenkalti/backoff/v4"
)

// SessionState represents the current state of a session.
type SessionState string

const (
	// SessionStateConnecting indicates the session is establishing initial connection.
	SessionStateConnecting SessionState = "connecting"

	// SessionStateConnected indicates the session is actively connected and receiving data.
	SessionStateConnected SessionState = "connected"

	// SessionStateReconnecting indicates the session is attempting to reconnect after an error.
	SessionStateReconnecting SessionState = "reconnecting"

	// SessionStateDisconnected indicates the session was gracefully closed.
	SessionStateDisconnected SessionState = "disconnected"

	// SessionStateFailed indicates the session failed permanently after max retries.
	SessionStateFailed SessionState = "failed"
)

// ReconnectionState tracks exponential backoff state for a reconnecting session.
type ReconnectionState struct {
	// SessionID is the associated session identifier.
	SessionID string

	// RetryCount is the current retry attempt number.
	RetryCount int

	// CurrentInterval is the current backoff interval.
	CurrentInterval time.Duration

	// NextRetryAt is the scheduled next retry time.
	NextRetryAt time.Time

	// BackoffInstance is the backoff algorithm instance.
	BackoffInstance backoff.BackOff
}

// createBackoff creates and configures an exponential backoff instance
// with settings optimized for WebSocket reconnection.
//
// Configuration:
// - InitialInterval: 1 second (first retry)
// - MaxInterval: 60 seconds (cap for exponential growth)
// - Multiplier: 2.0 (double each retry)
// - RandomizationFactor: 0.5 (±50% jitter to prevent thundering herd)
// - MaxElapsedTime: 0 (unlimited retries)
//
// Backoff sequence (without jitter): 1s, 2s, 4s, 8s, 16s, 32s, 60s, 60s, ...
func createBackoff() backoff.BackOff {
	b := backoff.NewExponentialBackOff()
	b.InitialInterval = 1 * time.Second
	b.MaxInterval = 60 * time.Second
	b.Multiplier = 2.0
	b.RandomizationFactor = 0.5
	b.MaxElapsedTime = 0 // Never stop retrying
	b.Reset()
	return b
}

// reconnectWithBackoff attempts to reconnect a chart session using exponential backoff.
// It respects context cancellation for graceful shutdown.
func (s *ChartSession) reconnectWithBackoff(ctx context.Context, logger *slog.Logger) error {
	b := createBackoff()
	s.reconnectionState = &ReconnectionState{
		SessionID:       s.sessionID,
		RetryCount:      0,
		BackoffInstance: b,
	}

	// Define the operation to retry
	operation := func() error {
		select {
		case <-ctx.Done():
			// Context cancelled, stop retrying
			return backoff.Permanent(ctx.Err())
		default:
		}

		s.reconnectionState.RetryCount++
		s.reconnectionState.NextRetryAt = time.Now().Add(s.reconnectionState.CurrentInterval)

		logger.Info("attempting reconnection",
			slog.String("session_id", s.sessionID),
			slog.String("symbol", s.symbol),
			slog.String("timeframe", s.timeframe),
			slog.Int("retry_count", s.reconnectionState.RetryCount),
			slog.String("event_type", "reconnecting"),
		)

		// Attempt to reconnect
		err := s.connect(ctx)
		if err != nil {
			// Log the error and continue retrying
			logger.Warn("reconnection attempt failed",
				slog.String("session_id", s.sessionID),
				slog.String("symbol", s.symbol),
				slog.String("timeframe", s.timeframe),
				slog.Int("retry_count", s.reconnectionState.RetryCount),
				slog.String("error", err.Error()),
			)
			return err // Retry
		}

		// Successful reconnection
		logger.Info("reconnection successful",
			slog.String("session_id", s.sessionID),
			slog.String("symbol", s.symbol),
			slog.String("timeframe", s.timeframe),
			slog.Int("retry_count", s.reconnectionState.RetryCount),
			slog.String("event_type", "connected"),
		)

		// Reset retry count on success
		s.reconnectionState.RetryCount = 0
		s.setState(SessionStateConnected)
		return nil
	}

	// Notify function to track backoff intervals
	notify := func(err error, duration time.Duration) {
		s.reconnectionState.CurrentInterval = duration
		logger.Debug("backoff retry scheduled",
			slog.String("session_id", s.sessionID),
			slog.String("symbol", s.symbol),
			slog.String("timeframe", s.timeframe),
			slog.Duration("next_retry_in", duration),
			slog.String("error", err.Error()),
		)
	}

	// Perform retry with backoff
	err := backoff.RetryNotify(operation, b, notify)
	if err != nil {
		// Permanent failure or context cancelled
		s.setState(SessionStateFailed)
		logger.Error("reconnection failed permanently",
			slog.String("session_id", s.sessionID),
			slog.String("symbol", s.symbol),
			slog.String("timeframe", s.timeframe),
			slog.String("event_type", "failed"),
			slog.String("error", err.Error()),
		)
		return fmt.Errorf("reconnection failed: %w", err)
	}

	return nil
}
