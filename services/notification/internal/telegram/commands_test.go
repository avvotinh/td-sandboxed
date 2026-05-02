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

// Test 6.1: handleResumeAll returns already-active message when stop is NOT active (AC#5)
func TestHandleResumeAll_AlreadyActive(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	// Stop is NOT active (default is false)
	handler := NewCommandHandler(bot)

	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
	}

	response := handler.handleResumeAll(msg)

	// AC#5: Should return already-active message
	if !strings.Contains(response, "⚠️") {
		t.Errorf("Expected ⚠️ emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "Trading is already active") {
		t.Errorf("Expected 'Trading is already active' in response, got:\n%s", response)
	}
}

// Test 6.2: handleResumeAll returns confirmation prompt when stop is active (AC#1)
func TestHandleResumeAll_ConfirmationPrompt(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	// Set stop as active
	bot.SetStopActive(true)

	handler := NewCommandHandler(bot)

	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
	}

	response := handler.handleResumeAll(msg)

	// AC#1: Should return confirmation prompt
	if !strings.Contains(response, "⚠️") {
		t.Errorf("Expected ⚠️ emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "Resume trading for all accounts") {
		t.Errorf("Expected confirmation prompt, got:\n%s", response)
	}
	if !strings.Contains(response, "/confirm_resume") {
		t.Errorf("Expected '/confirm_resume' in response, got:\n%s", response)
	}
	if !strings.Contains(response, "60 seconds") {
		t.Errorf("Expected '60 seconds' timeout mention, got:\n%s", response)
	}
}

// Test 6.3: handleConfirmResume publishes to Redis and resets stopActive (AC#2)
func TestHandleConfirmResume_PublishesAndResets(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	// Subscribe to emergency:resume channel to capture the message
	ctx := context.Background()
	pubsub := client.Subscribe(ctx, "emergency:resume")
	defer pubsub.Close()
	_, err := pubsub.Receive(ctx)
	if err != nil {
		t.Fatalf("Failed to subscribe: %v", err)
	}

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	bot.SetStopActive(true) // Start with stop active

	// Set up pending resume confirmation
	bot.SetPendingResume("testtrader", 123456789)

	handler := NewCommandHandler(bot)

	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
	}

	response := handler.handleConfirmResume(msg)

	// AC#2: Verify response
	if !strings.Contains(response, "🟢") {
		t.Errorf("Expected 🟢 emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "TRADING RESUME INITIATED") {
		t.Errorf("Expected 'TRADING RESUME INITIATED' in response, got:\n%s", response)
	}

	// Verify stopActive reset
	if bot.IsStopActive() {
		t.Error("Expected stopActive to be false after confirm_resume")
	}

	// Verify Redis message was published
	msgCh := pubsub.Channel()
	select {
	case redisMsg := <-msgCh:
		var cmd ResumeCommand
		if err := json.Unmarshal([]byte(redisMsg.Payload), &cmd); err != nil {
			t.Fatalf("Failed to unmarshal message: %v", err)
		}
		if cmd.Type != "resume_command" {
			t.Errorf("Expected type 'resume_command', got '%s'", cmd.Type)
		}
		if cmd.Command != "resume_all" {
			t.Errorf("Expected command 'resume_all', got '%s'", cmd.Command)
		}
		if cmd.InitiatedBy != "@testtrader" {
			t.Errorf("Expected initiated_by '@testtrader', got '%s'", cmd.InitiatedBy)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("Timeout waiting for Redis message")
	}
}

// Test 6.4: handleConfirmResume rejects expired confirmation (AC#6)
func TestHandleConfirmResume_RejectsExpired(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	// No pending resume set (or expired)

	handler := NewCommandHandler(bot)

	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
	}

	response := handler.handleConfirmResume(msg)

	// AC#6: Should reject with message about no pending request
	if !strings.Contains(response, "⚠️") {
		t.Errorf("Expected ⚠️ emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "No pending resume request") {
		t.Errorf("Expected 'No pending resume request' in response, got:\n%s", response)
	}
	if !strings.Contains(response, "/resume_all first") {
		t.Errorf("Expected '/resume_all first' instruction, got:\n%s", response)
	}
}

// Test 6.5: ResumeCommand JSON marshalling
func TestResumeCommand_JSONMarshal(t *testing.T) {
	cmd := ResumeCommand{
		Type:        "resume_command",
		Command:     "resume_all",
		Initiator:   "telegram",
		InitiatedBy: "@testuser",
		ChatID:      123456789,
		Accounts:    nil,
		Timestamp:   "2026-01-20T14:32:20Z",
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
		"type":         "resume_command",
		"command":      "resume_all",
		"initiator":    "telegram",
		"initiated_by": "@testuser",
		"chat_id":      float64(123456789),
		"timestamp":    "2026-01-20T14:32:20Z",
	}

	for key, expected := range expectedFields {
		if result[key] != expected {
			t.Errorf("Expected %s='%v', got '%v'", key, expected, result[key])
		}
	}

	// Accounts should be omitted when nil
	if _, ok := result["accounts"]; ok {
		t.Error("Expected 'accounts' to be omitted when nil")
	}
}

// Test 6.5b: ResumeCommand with accounts marshalling
func TestResumeCommand_JSONMarshal_WithAccounts(t *testing.T) {
	cmd := ResumeCommand{
		Type:        "resume_command",
		Command:     "resume",
		Initiator:   "telegram",
		InitiatedBy: "@testuser",
		ChatID:      123456789,
		Accounts:    []string{"ftmo-gold-001"},
		Timestamp:   "2026-01-20T14:32:20Z",
	}

	data, err := json.Marshal(cmd)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	// Verify accounts is included
	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	accounts, ok := result["accounts"].([]interface{})
	if !ok {
		t.Fatal("Expected 'accounts' to be an array")
	}
	if len(accounts) != 1 || accounts[0] != "ftmo-gold-001" {
		t.Errorf("Expected accounts=['ftmo-gold-001'], got %v", accounts)
	}
}

// Test 6.7: handleResume publishes for single account (AC#4)
func TestHandleResume_SingleAccount(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	// Subscribe to emergency:resume channel
	ctx := context.Background()
	pubsub := client.Subscribe(ctx, "emergency:resume")
	defer pubsub.Close()
	_, err := pubsub.Receive(ctx)
	if err != nil {
		t.Fatalf("Failed to subscribe: %v", err)
	}

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	handler := NewCommandHandler(bot)

	// Create message with arguments
	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
		Text: "/resume ftmo-gold-001",
		Entities: []tgbotapi.MessageEntity{
			{Type: "bot_command", Offset: 0, Length: 7},
		},
	}

	response := handler.handleResume(msg)

	// Verify response
	if !strings.Contains(response, "🟢") {
		t.Errorf("Expected 🟢 emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "RESUME INITIATED") {
		t.Errorf("Expected 'RESUME INITIATED' in response, got:\n%s", response)
	}
	if !strings.Contains(response, "ftmo-gold-001") {
		t.Errorf("Expected account ID in response, got:\n%s", response)
	}

	// Verify Redis message
	msgCh := pubsub.Channel()
	select {
	case redisMsg := <-msgCh:
		var cmd ResumeCommand
		if err := json.Unmarshal([]byte(redisMsg.Payload), &cmd); err != nil {
			t.Fatalf("Failed to unmarshal message: %v", err)
		}
		if cmd.Type != "resume_command" {
			t.Errorf("Expected type 'resume_command', got '%s'", cmd.Type)
		}
		if cmd.Command != "resume" {
			t.Errorf("Expected command 'resume', got '%s'", cmd.Command)
		}
		if len(cmd.Accounts) != 1 || cmd.Accounts[0] != "ftmo-gold-001" {
			t.Errorf("Expected accounts=['ftmo-gold-001'], got %v", cmd.Accounts)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("Timeout waiting for Redis message")
	}
}

// Test handleResume with no account ID
func TestHandleResume_NoAccountID(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	bot := mockBotWithPublisher("TestBot", 123456789, client)
	handler := NewCommandHandler(bot)

	// Message with no arguments
	msg := &tgbotapi.Message{
		Chat: &tgbotapi.Chat{ID: 123456789},
		From: &tgbotapi.User{UserName: "testtrader"},
		Text: "/resume",
		Entities: []tgbotapi.MessageEntity{
			{Type: "bot_command", Offset: 0, Length: 7},
		},
	}

	response := handler.handleResume(msg)

	// Should return usage instructions
	if !strings.Contains(response, "⚠️") {
		t.Errorf("Expected ⚠️ emoji in response, got:\n%s", response)
	}
	if !strings.Contains(response, "specify an account ID") {
		t.Errorf("Expected usage instructions, got:\n%s", response)
	}
}

// Test pending resume timeout
func TestBot_PendingResume_Timeout(t *testing.T) {
	bot := mockBot("TestBot", 123456789, true)

	// Set pending resume
	bot.SetPendingResume("testuser", 123456789)

	// Should be valid immediately
	username, chatID, valid := bot.GetPendingResume()
	if !valid {
		t.Error("Expected pending resume to be valid immediately")
	}
	if username != "testuser" {
		t.Errorf("Expected username 'testuser', got '%s'", username)
	}
	if chatID != 123456789 {
		t.Errorf("Expected chatID 123456789, got %d", chatID)
	}

	// Clear it
	bot.ClearPendingResume()

	// Should not be valid now
	_, _, valid = bot.GetPendingResume()
	if valid {
		t.Error("Expected pending resume to be invalid after clear")
	}
}

// Test 6.9: Confirmation timeout expires after 60 seconds (AC#6)
func TestBot_PendingResume_TimeoutExpiration(t *testing.T) {
	bot := mockBot("TestBot", 123456789, true)

	// Set pending resume
	bot.SetPendingResume("testuser", 123456789)

	// Manipulate timestamp to simulate 61 seconds ago
	bot.pendingResume.mu.Lock()
	bot.pendingResume.timestamp = time.Now().Add(-61 * time.Second)
	bot.pendingResume.mu.Unlock()

	// Should NOT be valid after timeout
	_, _, valid := bot.GetPendingResume()
	if valid {
		t.Error("Expected pending resume to be invalid after 60-second timeout")
	}

	// Verify active was set to false by GetPendingResume
	bot.pendingResume.mu.Lock()
	active := bot.pendingResume.active
	bot.pendingResume.mu.Unlock()
	if active {
		t.Error("Expected active to be false after timeout check")
	}
}

// Test timeout at exactly 60 seconds boundary
func TestBot_PendingResume_TimeoutBoundary(t *testing.T) {
	bot := mockBot("TestBot", 123456789, true)

	// Set pending resume
	bot.SetPendingResume("testuser", 123456789)

	// At exactly 59 seconds - should still be valid
	bot.pendingResume.mu.Lock()
	bot.pendingResume.timestamp = time.Now().Add(-59 * time.Second)
	bot.pendingResume.mu.Unlock()

	_, _, valid := bot.GetPendingResume()
	if !valid {
		t.Error("Expected pending resume to still be valid at 59 seconds")
	}

	// At 61 seconds - should be invalid
	bot.pendingResume.mu.Lock()
	bot.pendingResume.timestamp = time.Now().Add(-61 * time.Second)
	bot.pendingResume.mu.Unlock()

	_, _, valid = bot.GetPendingResume()
	if valid {
		t.Error("Expected pending resume to be invalid at 61 seconds")
	}
}

// Test handleHelp includes new resume commands
func TestHandleHelp_IncludesResumeCommands(t *testing.T) {
	handler := NewCommandHandler(mockBot("TestBot", 0, true))

	response := handler.handleHelp()

	expectedCommands := []string{
		"/resume_all",
		"/confirm_resume",
		"/resume <id>",
	}

	for _, cmd := range expectedCommands {
		if !strings.Contains(response, cmd) {
			t.Errorf("Expected help to contain '%s', got:\n%s", cmd, response)
		}
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
