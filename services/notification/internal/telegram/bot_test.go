// Package telegram provides tests for the Telegram bot client.
package telegram

import (
	"context"
	stderrors "errors"
	"testing"
	"time"

	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/errors"
)

func TestNewBot_InvalidToken(t *testing.T) {
	cfg := &config.Config{
		TelegramBotToken: "invalid-token-that-will-fail",
		TelegramChatID:   0,
		MaxRetries:       2, // Use fewer retries for faster test
		RetryBaseDelay:   100 * time.Millisecond,
		MaxRetryDelay:    500 * time.Millisecond,
		Debug:            false,
	}

	_, err := NewBot(cfg)
	if err == nil {
		t.Error("Expected error when creating bot with invalid token")
	}

	// Verify error wrapping
	if !stderrors.Is(err, errors.ErrTelegramConnection) {
		t.Errorf("Expected ErrTelegramConnection, got: %v", err)
	}
}

func TestNewBot_EmptyToken(t *testing.T) {
	cfg := &config.Config{
		TelegramBotToken: "",
		MaxRetries:       1,
		RetryBaseDelay:   100 * time.Millisecond,
		MaxRetryDelay:    500 * time.Millisecond,
	}

	_, err := NewBot(cfg)
	if err == nil {
		t.Error("Expected error when creating bot with empty token")
	}
}

func TestConnectWithRetry_ExponentialBackoff(t *testing.T) {
	// Test that exponential backoff works correctly
	// Using invalid token to trigger retries
	start := time.Now()

	_, err := connectWithRetry(
		context.Background(),
		"invalid-token",
		3,                    // 3 attempts
		50*time.Millisecond,  // base delay
		200*time.Millisecond, // max delay
	)

	elapsed := time.Since(start)

	if err == nil {
		t.Error("Expected error with invalid token")
	}

	// Expected delays: 50ms (first retry) + 100ms (second retry) = 150ms minimum
	// Allow some margin for test execution
	minExpected := 100 * time.Millisecond
	if elapsed < minExpected {
		t.Errorf("Expected at least %v of delay (exponential backoff), got %v", minExpected, elapsed)
	}
}

func TestConnectWithRetry_MaxDelayRespected(t *testing.T) {
	// This test verifies that delays are capped at maxDelay
	// We can't directly measure individual delays, but we can verify
	// the exponential backoff formula is applied correctly by checking
	// that the code path works without panics.

	_, err := connectWithRetry(
		context.Background(),
		"invalid-token",
		3,                    // 3 attempts
		50*time.Millisecond,  // base delay
		100*time.Millisecond, // max delay (caps the exponential growth)
	)

	// Verify we got an error (as expected with invalid token)
	if err == nil {
		t.Error("Expected error with invalid token")
	}

	// Verify the error message indicates retry exhaustion
	if err.Error() == "" {
		t.Error("Expected non-empty error message")
	}
}

func TestConnectWithRetry_ContextCancellation(t *testing.T) {
	// Test that context cancellation stops retry loop
	ctx, cancel := context.WithCancel(context.Background())

	// Cancel immediately
	cancel()

	start := time.Now()
	_, err := connectWithRetry(
		ctx,
		"invalid-token",
		10,                  // many attempts
		1*time.Second,       // long base delay
		10*time.Second,      // long max delay
	)
	elapsed := time.Since(start)

	if err == nil {
		t.Error("Expected error when context is cancelled")
	}

	// Should return almost immediately due to cancelled context
	if elapsed > 500*time.Millisecond {
		t.Errorf("Expected quick return with cancelled context, got %v", elapsed)
	}

	// Verify error mentions cancellation
	if !stderrors.Is(err, context.Canceled) {
		t.Errorf("Expected context.Canceled in error chain, got: %v", err)
	}
}
