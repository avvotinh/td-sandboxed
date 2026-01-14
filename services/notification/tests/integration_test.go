// Package tests provides integration tests for the notification service.
package tests

import (
	"os"
	"strings"
	"sync"
	"testing"
	"time"

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
