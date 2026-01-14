// Package tests provides integration tests for the notification service.
package tests

import (
	"os"
	"testing"
	"time"

	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/handlers"
	"github.com/user/sandboxed/services/notification/internal/subscriber"
	"github.com/user/sandboxed/services/notification/internal/telegram"
)

// mockNotifier is a test double for the Notifier interface.
type mockNotifier struct{}

func (m *mockNotifier) SendMessage(text string) error {
	return nil
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
