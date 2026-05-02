// Package config provides config loading tests.
package config

import (
	"os"
	"testing"
	"time"
)

func TestLoadConfig_MissingToken(t *testing.T) {
	// Ensure TELEGRAM_BOT_TOKEN is not set
	os.Unsetenv("TELEGRAM_BOT_TOKEN")
	os.Unsetenv("NOTIFICATION_TELEGRAM_BOT_TOKEN")

	_, err := Load()
	if err == nil {
		t.Error("Expected error when TELEGRAM_BOT_TOKEN is missing")
	}
}

func TestLoadConfig_WithToken(t *testing.T) {
	// Set required env var
	os.Setenv("TELEGRAM_BOT_TOKEN", "test-token-12345")
	defer os.Unsetenv("TELEGRAM_BOT_TOKEN")

	cfg, err := Load()
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if cfg.TelegramBotToken != "test-token-12345" {
		t.Errorf("Expected token 'test-token-12345', got '%s'", cfg.TelegramBotToken)
	}
}

func TestLoadConfig_DefaultRedisURL(t *testing.T) {
	os.Setenv("TELEGRAM_BOT_TOKEN", "test-token")
	os.Unsetenv("REDIS_URL")
	os.Unsetenv("NOTIFICATION_REDIS_URL")
	defer os.Unsetenv("TELEGRAM_BOT_TOKEN")

	cfg, err := Load()
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if cfg.RedisURL != "redis:6379" {
		t.Errorf("Expected default Redis URL 'redis:6379', got '%s'", cfg.RedisURL)
	}
}

func TestLoadConfig_DefaultLogLevel(t *testing.T) {
	os.Setenv("TELEGRAM_BOT_TOKEN", "test-token")
	defer os.Unsetenv("TELEGRAM_BOT_TOKEN")

	cfg, err := Load()
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if cfg.LogLevel != "info" {
		t.Errorf("Expected default log level 'info', got '%s'", cfg.LogLevel)
	}
}

func TestLoadConfig_DefaultRetrySettings(t *testing.T) {
	os.Setenv("TELEGRAM_BOT_TOKEN", "test-token")
	defer os.Unsetenv("TELEGRAM_BOT_TOKEN")

	cfg, err := Load()
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if cfg.MaxRetries != 5 {
		t.Errorf("Expected default MaxRetries 5, got %d", cfg.MaxRetries)
	}

	expectedBaseDelay := 1 * time.Second
	if cfg.RetryBaseDelay != expectedBaseDelay {
		t.Errorf("Expected default RetryBaseDelay %v, got %v", expectedBaseDelay, cfg.RetryBaseDelay)
	}

	expectedMaxDelay := 30 * time.Second
	if cfg.MaxRetryDelay != expectedMaxDelay {
		t.Errorf("Expected default MaxRetryDelay %v, got %v", expectedMaxDelay, cfg.MaxRetryDelay)
	}
}

func TestLoadConfig_WithChatID(t *testing.T) {
	os.Setenv("TELEGRAM_BOT_TOKEN", "test-token")
	os.Setenv("TELEGRAM_CHAT_ID", "123456789")
	defer func() {
		os.Unsetenv("TELEGRAM_BOT_TOKEN")
		os.Unsetenv("TELEGRAM_CHAT_ID")
	}()

	cfg, err := Load()
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if cfg.TelegramChatID != 123456789 {
		t.Errorf("Expected TelegramChatID 123456789, got %d", cfg.TelegramChatID)
	}
}

func TestLoadConfig_WithoutChatID(t *testing.T) {
	os.Setenv("TELEGRAM_BOT_TOKEN", "test-token")
	os.Unsetenv("TELEGRAM_CHAT_ID")
	defer os.Unsetenv("TELEGRAM_BOT_TOKEN")

	cfg, err := Load()
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if cfg.TelegramChatID != 0 {
		t.Errorf("Expected TelegramChatID 0 when not set, got %d", cfg.TelegramChatID)
	}
}

func TestLoadConfig_DebugMode(t *testing.T) {
	os.Setenv("TELEGRAM_BOT_TOKEN", "test-token")
	os.Setenv("NOTIFICATION_DEBUG", "true")
	defer func() {
		os.Unsetenv("TELEGRAM_BOT_TOKEN")
		os.Unsetenv("NOTIFICATION_DEBUG")
	}()

	cfg, err := Load()
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if !cfg.Debug {
		t.Error("Expected Debug to be true")
	}
}
