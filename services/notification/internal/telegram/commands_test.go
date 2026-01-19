// Package telegram provides tests for command handlers.
package telegram

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
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

// mockBotWithPublisher creates a Bot with a Redis publisher for emergency stop testing.
func mockBotWithPublisher(username string, chatID int64, redisClient *redis.Client) *Bot {
	b := &Bot{
		api:       nil, // Not used in handler tests
		chatID:    chatID,
		debug:     false,
		username:  username,
		publisher: redisClient,
	}
	b.healthy.Store(true)
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

// Test 4.1: handleStopAll publishes to Redis emergency:stop channel
func TestHandleStopAll_PublishesToRedis(t *testing.T) {
	// Start miniredis for testing
	mr := miniredis.RunT(t)

	// Create Redis client connected to miniredis
	client := redis.NewClient(&redis.Options{
		Addr: mr.Addr(),
	})
	defer client.Close()

	// Subscribe to emergency:stop channel to capture the message
	ctx := context.Background()
	pubsub := client.Subscribe(ctx, "emergency:stop")
	defer pubsub.Close()

	// Wait for subscription confirmation
	_, err := pubsub.Receive(ctx)
	if err != nil {
		t.Fatalf("Failed to subscribe: %v", err)
	}

	// Create bot with publisher
	bot := mockBotWithPublisher("TestBot", 123456789, client)
	handler := NewCommandHandler(bot)

	// Create message from user
	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader", ID: 987654321},
	}

	// Execute stop_all
	response := handler.handleStopAll(msg)

	// Verify response
	if !strings.Contains(response, "🛑") {
		t.Errorf("Expected 🛑 emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "EMERGENCY STOP INITIATED") {
		t.Errorf("Expected 'EMERGENCY STOP INITIATED' in response, got:\n%s", response)
	}

	// Verify Redis message was published
	msgCh := pubsub.Channel()
	select {
	case redisMsg := <-msgCh:
		// Verify JSON structure
		var cmd EmergencyStopCommand
		if err := json.Unmarshal([]byte(redisMsg.Payload), &cmd); err != nil {
			t.Fatalf("Failed to unmarshal message: %v", err)
		}
		if cmd.Type != "emergency_stop" {
			t.Errorf("Expected type 'emergency_stop', got '%s'", cmd.Type)
		}
		if cmd.Command != "stop_all" {
			t.Errorf("Expected command 'stop_all', got '%s'", cmd.Command)
		}
		if cmd.Initiator != "telegram" {
			t.Errorf("Expected initiator 'telegram', got '%s'", cmd.Initiator)
		}
		if cmd.InitiatedBy != "@testtrader" {
			t.Errorf("Expected initiated_by '@testtrader', got '%s'", cmd.InitiatedBy)
		}
		if cmd.ChatID != 123456789 {
			t.Errorf("Expected chat_id 123456789, got %d", cmd.ChatID)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("Timeout waiting for Redis message")
	}
}

// Test 4.2: handleStopAll returns already stopped message when stop is active (AC#4)
func TestHandleStopAll_AlreadyStopped(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	// Set stop as already active
	bot.SetStopActive(true)

	handler := NewCommandHandler(bot)
	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
	}

	response := handler.handleStopAll(msg)

	// Verify already-stopped response
	if !strings.Contains(response, "⚠️") {
		t.Errorf("Expected ⚠️ emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "All accounts already stopped") {
		t.Errorf("Expected 'All accounts already stopped' in response, got:\n%s", response)
	}
}

// Test 4.3: EmergencyStopCommand JSON marshalling
func TestEmergencyStopCommand_JSONMarshal(t *testing.T) {
	cmd := EmergencyStopCommand{
		Type:        "emergency_stop",
		Command:     "stop_all",
		Initiator:   "telegram",
		InitiatedBy: "@testuser",
		ChatID:      123456789,
		Timestamp:   "2026-01-19T14:32:15Z",
	}

	data, err := json.Marshal(cmd)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	// Verify JSON structure
	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	expectedFields := map[string]interface{}{
		"type":         "emergency_stop",
		"command":      "stop_all",
		"initiator":    "telegram",
		"initiated_by": "@testuser",
		"chat_id":      float64(123456789),
		"timestamp":    "2026-01-19T14:32:15Z",
	}

	for key, expected := range expectedFields {
		if result[key] != expected {
			t.Errorf("Expected %s='%v', got '%v'", key, expected, result[key])
		}
	}
}

// Test handleStopAll with nil user (edge case)
func TestHandleStopAll_NilUser(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	handler := NewCommandHandler(bot)

	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: nil, // No user info
	}

	response := handler.handleStopAll(msg)

	// Should still work with "unknown" username
	if !strings.Contains(response, "EMERGENCY STOP INITIATED") {
		t.Errorf("Expected 'EMERGENCY STOP INITIATED' even with nil user, got:\n%s", response)
	}
}

// Test handleStopAll sets stopActive to true
func TestHandleStopAll_SetsStopActive(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	handler := NewCommandHandler(bot)

	// Verify initially not active
	if bot.IsStopActive() {
		t.Error("Expected stopActive to be false initially")
	}

	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
	}

	handler.handleStopAll(msg)

	// Verify now active
	if !bot.IsStopActive() {
		t.Error("Expected stopActive to be true after handleStopAll")
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

// Test handleStopAll with nil publisher returns error message
func TestHandleStopAll_NilPublisher(t *testing.T) {
	// Create bot without publisher (nil)
	bot := mockBot("TestBot", 123456789, true)
	// bot.publisher is nil by default from mockBot

	handler := NewCommandHandler(bot)
	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
	}

	response := handler.handleStopAll(msg)

	// Should return error message since publisher is nil
	if !strings.Contains(response, "FAILED") {
		t.Errorf("Expected 'FAILED' in response for nil publisher, got:\n%s", response)
	}
	if !strings.Contains(response, "not initialized") {
		t.Errorf("Expected 'not initialized' error message, got:\n%s", response)
	}
}

// Test handleStopAll with empty username (but user exists with ID)
func TestHandleStopAll_EmptyUsername(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	// Subscribe to capture the message
	ctx := context.Background()
	pubsub := client.Subscribe(ctx, "emergency:stop")
	defer pubsub.Close()
	_, _ = pubsub.Receive(ctx)

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	handler := NewCommandHandler(bot)

	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{
			UserName: "", // Empty username
			ID:       987654321,
		},
	}

	response := handler.handleStopAll(msg)

	// Should still succeed
	if !strings.Contains(response, "EMERGENCY STOP INITIATED") {
		t.Errorf("Expected 'EMERGENCY STOP INITIATED', got:\n%s", response)
	}

	// Verify the initiated_by field uses user_ID fallback
	msgCh := pubsub.Channel()
	select {
	case redisMsg := <-msgCh:
		var cmd EmergencyStopCommand
		if err := json.Unmarshal([]byte(redisMsg.Payload), &cmd); err != nil {
			t.Fatalf("Failed to unmarshal: %v", err)
		}
		// Should use user_ID format when username is empty
		if cmd.InitiatedBy != "@user_987654321" {
			t.Errorf("Expected initiated_by '@user_987654321', got '%s'", cmd.InitiatedBy)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("Timeout waiting for Redis message")
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
