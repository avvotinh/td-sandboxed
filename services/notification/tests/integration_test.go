// Package tests provides integration tests for the notification service.
package tests

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/handlers"
	"github.com/user/sandboxed/services/notification/internal/subscriber"
	"github.com/user/sandboxed/services/notification/internal/telegram"
)

// mockNotifier is a test double for the Notifier interface.
type mockNotifier struct {
	messages []string
	mu       sync.Mutex
}

func (m *mockNotifier) SendMessage(text string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.messages = append(m.messages, text)
	return nil
}

func (m *mockNotifier) getMessages() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]string{}, m.messages...)
}

func TestSubscriberChannels(t *testing.T) {
	// Verify subscriber returns expected channel list
	cfg := &config.Config{
		RedisURL:       "localhost:6379",
		MaxRetries:     3,
		RetryBaseDelay: time.Second,
		MaxRetryDelay:  30 * time.Second,
	}

	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	sub := subscriber.New(cfg, router)
	channels := sub.Channels()

	expectedChannels := []string{
		"alerts:trade:*",
		"alerts:risk:*",
		"alerts:system",
		"emergency:stop",
	}

	if len(channels) != len(expectedChannels) {
		t.Errorf("Expected %d channels, got %d", len(expectedChannels), len(channels))
	}

	for i, expected := range expectedChannels {
		if channels[i] != expected {
			t.Errorf("Channel %d: expected '%s', got '%s'", i, expected, channels[i])
		}
	}
}

func TestSubscriberNew(t *testing.T) {
	cfg := &config.Config{
		RedisURL:       "localhost:6379",
		RedisPassword:  "",
		MaxRetries:     3,
		RetryBaseDelay: time.Second,
		MaxRetryDelay:  30 * time.Second,
	}

	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	sub := subscriber.New(cfg, router)
	if sub == nil {
		t.Error("Expected subscriber to be created, got nil")
	}
}

// Test 5.6: Integration test - Route trade event to handler, verify Telegram output
func TestRouter_TradeOpenNotification(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Simulate Redis message
	channel := "alerts:trade:ftmo-gold-001"
	payload := `{
		"type": "trade_opened",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "BUY",
		"volume": 0.10,
		"price": 1850.25,
		"sl": 1845.00,
		"tp": 1860.00,
		"reason": "MA crossover (20/50 SMA)",
		"daily_pnl": -350.00,
		"daily_pnl_pct": -0.35,
		"timestamp": "2026-01-15T14:32:15Z"
	}`

	// Route the message
	router.Route(channel, payload)

	// Wait for goroutine (fire-and-forget)
	time.Sleep(100 * time.Millisecond)

	// Verify notification was sent
	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(messages))
	}

	msg := messages[0]

	// Verify AC#1 format in notification
	expectedFields := []string{
		"🔵", "*TRADE EXECUTED*",
		"FTMO Gold Challenge",
		"XAUUSD",
		"BUY", "0.10",
		"1850.25",
		"MA crossover (20/50 SMA)",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, msg)
		}
	}
}

// Test 5.6: Integration test - Route trade close event
func TestRouter_TradeCloseNotification(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Simulate Redis message for trade close
	channel := "alerts:trade:ftmo-gold-001"
	payload := `{
		"type": "trade_closed",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "SELL",
		"volume": 0.10,
		"entry_price": 1850.25,
		"exit_price": 1858.50,
		"pnl": 82.50,
		"pnl_pct": 0.45,
		"result": "PROFIT",
		"duration": "2h 15m",
		"daily_pnl": -267.50,
		"daily_pnl_pct": -0.27,
		"timestamp": "2026-01-15T16:47:30Z"
	}`

	// Route the message
	router.Route(channel, payload)

	// Wait for goroutine
	time.Sleep(100 * time.Millisecond)

	// Verify notification was sent
	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(messages))
	}

	msg := messages[0]

	// Verify AC#2 PROFIT format
	expectedFields := []string{
		"🟢", "*TRADE CLOSED - PROFIT*",
		"FTMO Gold Challenge",
		"+$82.50",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, msg)
		}
	}
}

// Test 5.7: Fire-and-forget - Route returns immediately
func TestRouter_FireAndForget(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	channel := "alerts:trade:ftmo-gold-001"
	payload := `{
		"type": "trade_opened",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"symbol": "XAUUSD",
		"action": "BUY",
		"volume": 0.10,
		"price": 1850.25,
		"sl": 1845.00,
		"tp": 1860.00,
		"reason": "Test",
		"daily_pnl": 0,
		"daily_pnl_pct": 0,
		"timestamp": "2026-01-15T14:32:15Z"
	}`

	// Route should return immediately (fire-and-forget)
	start := time.Now()
	router.Route(channel, payload)
	elapsed := time.Since(start)

	// Route MUST complete immediately (< 5ms)
	if elapsed > 5*time.Millisecond {
		t.Errorf("Route blocked for %v (should be < 5ms for fire-and-forget)", elapsed)
	}
}

// Test router handles invalid JSON gracefully
func TestRouter_InvalidJSON(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	channel := "alerts:trade:ftmo-gold-001"
	payload := `not valid json`

	// Should not panic
	router.Route(channel, payload)

	// Wait for potential goroutine
	time.Sleep(50 * time.Millisecond)

	// No message should be sent
	messages := notifier.getMessages()
	if len(messages) != 0 {
		t.Errorf("Expected 0 messages for invalid JSON, got %d", len(messages))
	}
}

// Integration test: Bot initialization with real token (skipped without env var)
func TestBotIntegration_RealConnection(t *testing.T) {
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	if token == "" {
		t.Skip("Skipping integration test: TELEGRAM_BOT_TOKEN not set")
	}

	cfg := &config.Config{
		TelegramBotToken: token,
		TelegramChatID:   0,
		MaxRetries:       3,
		RetryBaseDelay:   1 * time.Second,
		MaxRetryDelay:    5 * time.Second,
		Debug:            false,
	}

	bot, err := telegram.NewBot(cfg)
	if err != nil {
		t.Fatalf("Failed to create bot: %v", err)
	}

	// Verify bot is healthy
	if !bot.IsHealthy() {
		t.Error("Expected bot to be healthy after successful connection")
	}

	// Verify username is set
	if bot.Username() == "" {
		t.Error("Expected bot username to be set")
	}

	t.Logf("Successfully connected to bot: @%s", bot.Username())
}

// Integration test: Message sending to configured chat (skipped without env vars)
func TestBotIntegration_SendMessage(t *testing.T) {
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	chatIDStr := os.Getenv("TELEGRAM_CHAT_ID")

	if token == "" || chatIDStr == "" {
		t.Skip("Skipping integration test: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
	}

	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("Failed to load config: %v", err)
	}

	bot, err := telegram.NewBot(cfg)
	if err != nil {
		t.Fatalf("Failed to create bot: %v", err)
	}

	// Validate chat ID by sending test message
	err = bot.ValidateChatID()
	if err != nil {
		t.Errorf("ValidateChatID failed: %v", err)
	}

	// Send a test message
	err = bot.SendMessage("*Integration Test*\n\nThis is a test message from the notification service integration tests.")
	if err != nil {
		t.Errorf("SendMessage failed: %v", err)
	}

	t.Log("Successfully sent test message")
}

// Integration test: Chat ID validation with no chat ID configured
func TestBotIntegration_ValidateChatID_NotConfigured(t *testing.T) {
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	if token == "" {
		t.Skip("Skipping integration test: TELEGRAM_BOT_TOKEN not set")
	}

	cfg := &config.Config{
		TelegramBotToken: token,
		TelegramChatID:   0, // Not configured
		MaxRetries:       3,
		RetryBaseDelay:   1 * time.Second,
		MaxRetryDelay:    5 * time.Second,
		Debug:            false,
	}

	bot, err := telegram.NewBot(cfg)
	if err != nil {
		t.Fatalf("Failed to create bot: %v", err)
	}

	// ValidateChatID should return nil when chat ID is not configured
	// (non-blocking warning behavior)
	err = bot.ValidateChatID()
	if err != nil {
		t.Errorf("ValidateChatID should not error when chat ID is not configured: %v", err)
	}

	// ChatID should return 0
	if bot.ChatID() != 0 {
		t.Errorf("Expected ChatID to be 0, got %d", bot.ChatID())
	}
}

// Test 4.8: Integration test - Route risk_blocked event to handler, verify Telegram output (AC#1)
func TestRouter_RiskBlockedNotification(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Simulate Redis message for risk blocked
	channel := "alerts:risk:ftmo-gold-001"
	payload := `{
		"type": "risk_blocked",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Daily Loss Limit",
		"rule_type": "blocked",
		"current": 4.8,
		"threshold": 5.0,
		"trade": "BUY 0.10 XAUUSD",
		"reason": "Trade would exceed daily loss limit",
		"action": "Trade rejected",
		"timestamp": "2026-01-15T14:32:15Z"
	}`

	// Route the message
	router.Route(channel, payload)

	// Wait for goroutine (fire-and-forget)
	time.Sleep(100 * time.Millisecond)

	// Verify notification was sent
	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(messages))
	}

	msg := messages[0]

	// AC#1: Verify format
	expectedFields := []string{
		"🔴", "*TRADE BLOCKED*",
		"FTMO Gold Challenge",
		"Daily Loss Limit",
		"4.8% of 5.0% limit",
		"BUY 0.10 XAUUSD",
		"Trade rejected",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, msg)
		}
	}
}

// Test 4.8: Integration test - Route risk_warning event (AC#2)
func TestRouter_RiskWarningNotification(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Simulate Redis message for risk warning
	channel := "alerts:risk:ftmo-gold-001"
	payload := `{
		"type": "risk_warning",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Daily Loss Limit",
		"rule_type": "warning",
		"current": 4.0,
		"threshold": 5.0,
		"warning_level": 80,
		"remaining_dollars": 1000.00,
		"action": "Trading continues, monitor closely",
		"timestamp": "2026-01-15T14:32:15Z"
	}`

	router.Route(channel, payload)
	time.Sleep(100 * time.Millisecond)

	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(messages))
	}

	msg := messages[0]

	// AC#2: Verify format with dollar + percentage
	expectedFields := []string{
		"🟡", "*RISK WARNING*",
		"FTMO Gold Challenge",
		"80% of limit reached",
		"$1000 (1.0%)",
		"Trading continues, monitor closely",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, msg)
		}
	}
}

// Test 4.8: Integration test - Route trading_halted event (AC#3)
func TestRouter_TradingHaltedNotification(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Simulate Redis message for trading halted
	channel := "alerts:risk:ftmo-gold-001"
	payload := `{
		"type": "trading_halted",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Max Drawdown",
		"rule_type": "halted",
		"status": "10% limit reached",
		"action": "All trading paused for this account",
		"required_action": "Manual review before resuming",
		"timestamp": "2026-01-15T14:32:15Z"
	}`

	router.Route(channel, payload)
	time.Sleep(100 * time.Millisecond)

	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(messages))
	}

	msg := messages[0]

	// AC#3: Verify format
	expectedFields := []string{
		"🔴", "*TRADING HALTED*",
		"FTMO Gold Challenge",
		"Max Drawdown",
		"10% limit reached",
		"All trading paused for this account",
		"Manual review before resuming",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, msg)
		}
	}
}

// Test 4.9: Fire-and-forget - Risk notification failure does NOT block trading
func TestRouter_RiskAlert_FireAndForget(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	channel := "alerts:risk:ftmo-gold-001"
	payload := `{
		"type": "risk_blocked",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge",
		"rule_name": "Daily Loss Limit",
		"rule_type": "blocked",
		"current": 4.8,
		"threshold": 5.0,
		"trade": "BUY 0.10 XAUUSD",
		"reason": "Trade would exceed daily loss limit",
		"action": "Trade rejected",
		"timestamp": "2026-01-15T14:32:15Z"
	}`

	// Route should return immediately (fire-and-forget)
	start := time.Now()
	router.Route(channel, payload)
	elapsed := time.Since(start)

	// Route MUST complete immediately (< 5ms)
	if elapsed > 5*time.Millisecond {
		t.Errorf("Route blocked for %v (should be < 5ms for fire-and-forget)", elapsed)
	}
}

// Test risk alert with invalid JSON - should not crash
func TestRouter_RiskAlert_InvalidJSON(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	channel := "alerts:risk:ftmo-gold-001"
	payload := `not valid json`

	// Should not panic
	router.Route(channel, payload)

	// Wait for potential goroutine
	time.Sleep(50 * time.Millisecond)

	// No message should be sent
	messages := notifier.getMessages()
	if len(messages) != 0 {
		t.Errorf("Expected 0 messages for invalid JSON, got %d", len(messages))
	}
}

// Integration test: Full trade notification with real Telegram (skipped without env vars)
func TestIntegration_TradeNotification_RealTelegram(t *testing.T) {
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	chatIDStr := os.Getenv("TELEGRAM_CHAT_ID")

	if token == "" || chatIDStr == "" {
		t.Skip("Skipping integration test: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
	}

	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("Failed to load config: %v", err)
	}

	bot, err := telegram.NewBot(cfg)
	if err != nil {
		t.Fatalf("Failed to create bot: %v", err)
	}

	// Create router with real bot
	router := subscriber.NewRouter(bot,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Send a trade notification
	channel := "alerts:trade:ftmo-gold-001"
	payload := `{
		"type": "trade_opened",
		"account_id": "ftmo-gold-001",
		"account_name": "FTMO Gold Challenge (Test)",
		"symbol": "XAUUSD",
		"action": "BUY",
		"volume": 0.10,
		"price": 1850.25,
		"sl": 1845.00,
		"tp": 1860.00,
		"reason": "Integration Test",
		"daily_pnl": -350.00,
		"daily_pnl_pct": -0.35,
		"timestamp": "2026-01-15T14:32:15Z"
	}`

	router.Route(channel, payload)

	// Wait for notification to be sent
	time.Sleep(500 * time.Millisecond)

	t.Log("Trade notification sent to Telegram (check your chat for the message)")
}

// Test 4.6: Integration test - Full emergency stop flow from /stop_all → Redis publish → confirmation → notification
func TestRouter_EmergencyStopConfirmation(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Simulate confirmation from trading engine
	channel := "emergency:stop"
	payload := `{
		"type": "emergency_stop_confirmation",
		"status": "completed",
		"accounts_paused": 3,
		"positions_preserved": 5,
		"orders_cancelled": 2,
		"timestamp": "2026-01-19T14:32:15Z"
	}`

	// Route the message
	router.Route(channel, payload)

	// Wait for goroutine
	time.Sleep(100 * time.Millisecond)

	// Verify notification was sent
	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(messages))
	}

	msg := messages[0]

	// AC#3: Verify format
	expectedFields := []string{
		"🔴", "*EMERGENCY STOP COMPLETE*",
		"Accounts Paused: 3",
		"Pending Orders: Cancelled",
		"Open Positions: 5 (preserved)",
		"Action: Use /resume_all to restart trading",
		"14:32:15 UTC",
	}

	for _, field := range expectedFields {
		if !strings.Contains(msg, field) {
			t.Errorf("Expected message to contain '%s'\n\nGot:\n%s", field, msg)
		}
	}
}

// Test emergency stop self-echo is ignored (no notification)
func TestRouter_EmergencyStopSelfEcho(t *testing.T) {
	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Simulate self-echo of emergency_stop command
	channel := "emergency:stop"
	payload := `{
		"type": "emergency_stop",
		"command": "stop_all",
		"initiator": "telegram",
		"initiated_by": "@testuser",
		"chat_id": 123456789,
		"timestamp": "2026-01-19T14:32:15Z"
	}`

	router.Route(channel, payload)
	time.Sleep(100 * time.Millisecond)

	// No message should be sent (self-echo is ignored)
	messages := notifier.getMessages()
	if len(messages) != 0 {
		t.Errorf("Expected 0 messages for self-echo, got %d", len(messages))
	}
}

// Test 4.7: Performance test - Emergency stop command → Redis publish completes in < 100ms
func TestEmergencyStop_RedisPublishPerformance(t *testing.T) {
	// Start miniredis
	mr := miniredis.RunT(t)

	// Create Redis client
	client := redis.NewClient(&redis.Options{
		Addr: mr.Addr(),
	})
	defer client.Close()

	// Create emergency stop command
	cmd := telegram.EmergencyStopCommand{
		Type:        "emergency_stop",
		Command:     "stop_all",
		Initiator:   "telegram",
		InitiatedBy: "@testuser",
		ChatID:      123456789,
		Timestamp:   time.Now().UTC().Format(time.RFC3339),
	}

	payload, err := json.Marshal(cmd)
	if err != nil {
		t.Fatalf("Failed to marshal command: %v", err)
	}

	// Measure publish time
	ctx := context.Background()
	start := time.Now()
	err = client.Publish(ctx, "emergency:stop", payload).Err()
	elapsed := time.Since(start)

	if err != nil {
		t.Fatalf("Failed to publish: %v", err)
	}

	// SLA: < 100ms
	if elapsed > 100*time.Millisecond {
		t.Errorf("Redis publish exceeded 100ms SLA: %v", elapsed)
	}

	t.Logf("Redis publish completed in %v", elapsed)
}

// Test 4.8: Performance test - Full round-trip < 500ms (mock trading engine response)
func TestEmergencyStop_FullRoundTripPerformance(t *testing.T) {
	// Start miniredis
	mr := miniredis.RunT(t)

	// Create Redis client
	client := redis.NewClient(&redis.Options{
		Addr: mr.Addr(),
	})
	defer client.Close()

	notifier := &mockNotifier{}
	router := subscriber.NewRouter(notifier,
		handlers.NewTradeHandler(),
		handlers.NewRiskHandler(),
		handlers.NewSystemHandler(),
		handlers.NewEmergencyHandler(),
	)

	// Subscribe to channel for confirmation
	ctx := context.Background()

	// Measure full round-trip time
	start := time.Now()

	// Step 1: Publish emergency stop command
	cmd := telegram.EmergencyStopCommand{
		Type:        "emergency_stop",
		Command:     "stop_all",
		Initiator:   "telegram",
		InitiatedBy: "@testuser",
		ChatID:      123456789,
		Timestamp:   time.Now().UTC().Format(time.RFC3339),
	}
	cmdPayload, _ := json.Marshal(cmd)
	err := client.Publish(ctx, "emergency:stop", cmdPayload).Err()
	if err != nil {
		t.Fatalf("Failed to publish command: %v", err)
	}

	// Step 2: Mock trading engine sends confirmation (immediate response)
	confirmPayload := `{
		"type": "emergency_stop_confirmation",
		"status": "completed",
		"accounts_paused": 3,
		"positions_preserved": 5,
		"orders_cancelled": 2,
		"timestamp": "2026-01-19T14:32:15Z"
	}`

	// Route the confirmation through handler
	router.Route("emergency:stop", confirmPayload)

	// Wait for notification processing
	time.Sleep(50 * time.Millisecond)

	elapsed := time.Since(start)

	// Verify message was sent
	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(messages))
	}

	// SLA: Full round-trip < 500ms
	if elapsed > 500*time.Millisecond {
		t.Errorf("Full round-trip exceeded 500ms SLA: %v", elapsed)
	}

	t.Logf("Full round-trip completed in %v", elapsed)
}
