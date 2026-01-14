// Package telegram provides tests for command handlers.
package telegram

import (
	"strings"
	"testing"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// mockRedisStatusChecker is a test double for RedisStatusChecker.
type mockRedisStatusChecker struct {
	connected bool
	channels  []string
}

func (m *mockRedisStatusChecker) IsConnected() bool {
	return m.connected
}

func (m *mockRedisStatusChecker) Channels() []string {
	return m.channels
}

// mockBot creates a Bot struct for testing without actual Telegram connection.
// Sets lastHealthCheck to far future to ensure IsHealthy() uses cached value.
func mockBot(username string, chatID int64, healthy bool) *Bot {
	b := &Bot{
		api:      nil, // Not used in handler tests
		chatID:   chatID,
		debug:    false,
		username: username,
	}
	b.healthy.Store(healthy)
	// Set lastHealthCheck to far future so IsHealthy uses cached value (avoids nil api panic)
	b.lastHealthCheck.Store(9999999999)
	return b
}

func TestHandleStart_ResponseContent(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, true))

	// Create a tgbotapi.Message struct for testing
	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{
			ID:   123456789,
			Type: "private",
		},
		From: &tgbotapi.User{
			ID:        987654321,
			UserName:  "testuser",
			FirstName: "Test",
			LastName:  "User",
		},
	}

	response := handler.handleStart(msg)

	// Verify welcome message contains expected content
	expectedParts := []string{
		"Welcome to Sandboxed Trading Bot",
		"123456789",        // Chat ID should be in response
		"@testuser",        // Username should be mentioned
		"TELEGRAM_CHAT_ID", // Should have configuration instructions
		"Trade executions", // Should mention notification types
		"/status",          // Should mention available commands
	}

	for _, part := range expectedParts {
		if !strings.Contains(response, part) {
			t.Errorf("Expected response to contain '%s', got:\n%s", part, response)
		}
	}
}

func TestHandleStart_NilUser(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, true))

	// Test with nil From (edge case)
	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{
			ID:   123456789,
			Type: "private",
		},
		From: nil, // No user info
	}

	response := handler.handleStart(msg)

	// Should still work with "unknown" username
	if !strings.Contains(response, "123456789") {
		t.Errorf("Expected chat ID in response even with nil user, got:\n%s", response)
	}
}

func TestHandleStatus_HealthyBot(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 123456789, true))

	response := handler.handleStatus()

	// Verify status shows connected (uses cached healthy value)
	if !strings.Contains(response, "Status: Connected") {
		t.Errorf("Expected 'Status: Connected' for healthy bot, got:\n%s", response)
	}

	// Verify username is shown
	if !strings.Contains(response, "@TestBot") {
		t.Errorf("Expected '@TestBot' in response, got:\n%s", response)
	}

	// Verify chat ID is shown as configured
	if !strings.Contains(response, "Configured") {
		t.Errorf("Expected 'Configured' for set chat ID, got:\n%s", response)
	}
}

func TestHandleStatus_UnhealthyBot(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, false))

	response := handler.handleStatus()

	// Verify status shows disconnected
	if !strings.Contains(response, "Status: Disconnected") {
		t.Errorf("Expected 'Status: Disconnected' for unhealthy bot, got:\n%s", response)
	}

	// Verify chat ID not configured warning
	if !strings.Contains(response, "Not configured") {
		t.Errorf("Expected 'Not configured' for missing chat ID, got:\n%s", response)
	}
}

func TestHandleStatus_NoChatID(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, true))

	response := handler.handleStatus()

	// Verify warning about missing chat ID
	if !strings.Contains(response, "Not configured") {
		t.Errorf("Expected 'Not configured' warning for zero chat ID, got:\n%s", response)
	}
}

func TestHandleHelp_Content(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, true))

	response := handler.handleHelp()

	// Verify help contains expected commands
	expectedCommands := []string{
		"/status",
		"/stop_all",
		"/resume_all",
		"/help",
	}

	for _, cmd := range expectedCommands {
		if !strings.Contains(response, cmd) {
			t.Errorf("Expected help to contain '%s', got:\n%s", cmd, response)
		}
	}
}

func TestHandleStopAll_ScaffoldResponse(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, true))

	response := handler.handleStopAll()

	// Verify scaffold response mentions it's not fully implemented
	if !strings.Contains(response, "Scaffold") || !strings.Contains(response, "Story 6.5") {
		t.Errorf("Expected scaffold response with story reference, got:\n%s", response)
	}
}

func TestHandleResumeAll_ScaffoldResponse(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, true))

	response := handler.handleResumeAll()

	// Verify scaffold response mentions it's not fully implemented
	if !strings.Contains(response, "Scaffold") || !strings.Contains(response, "Story 6.6") {
		t.Errorf("Expected scaffold response with story reference, got:\n%s", response)
	}
}

func TestHandleStatus_RedisConnected(t *testing.T) {
	// Set up mock Redis subscriber as connected
	mockSub := &mockRedisStatusChecker{
		connected: true,
		channels:  []string{"alerts:trade:*", "alerts:risk:*", "alerts:system", "emergency:stop"},
	}
	oldSub := redisSubscriber
	SetSubscriber(mockSub)
	defer SetSubscriber(oldSub)

	handler := NewCommandHandler(mockBot("TestBot", 123456789, true))
	response := handler.handleStatus()

	// Verify Redis shows as connected
	if !strings.Contains(response, "Redis Subscriber") {
		t.Errorf("Expected 'Redis Subscriber' section in response, got:\n%s", response)
	}
	if !strings.Contains(response, "Status: Connected") {
		t.Errorf("Expected Redis 'Status: Connected' in response, got:\n%s", response)
	}
	// Verify channels are displayed
	if !strings.Contains(response, "alerts:trade:*") {
		t.Errorf("Expected channel list in response, got:\n%s", response)
	}
}

func TestHandleStatus_RedisDisconnected(t *testing.T) {
	// Set up mock Redis subscriber as disconnected
	mockSub := &mockRedisStatusChecker{
		connected: false,
		channels:  []string{"alerts:trade:*", "alerts:risk:*"},
	}
	oldSub := redisSubscriber
	SetSubscriber(mockSub)
	defer SetSubscriber(oldSub)

	handler := NewCommandHandler(mockBot("TestBot", 0, true))
	response := handler.handleStatus()

	// Verify Redis shows as disconnected
	if !strings.Contains(response, "Redis Subscriber") {
		t.Errorf("Expected 'Redis Subscriber' section in response, got:\n%s", response)
	}
	// Count occurrences - should have "Status: Disconnected" for Redis (not just Telegram)
	if strings.Count(response, "Disconnected") < 1 {
		t.Errorf("Expected 'Disconnected' for Redis status, got:\n%s", response)
	}
}

func TestHandleStatus_RedisNotInitialized(t *testing.T) {
	// Set subscriber to nil to simulate not initialized
	oldSub := redisSubscriber
	SetSubscriber(nil)
	defer SetSubscriber(oldSub)

	handler := NewCommandHandler(mockBot("TestBot", 0, true))
	response := handler.handleStatus()

	// Verify Redis shows as not initialized
	if !strings.Contains(response, "Not initialized") {
		t.Errorf("Expected 'Not initialized' for Redis status, got:\n%s", response)
	}
}
