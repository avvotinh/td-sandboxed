// Package config provides config loading tests.
package config

import (
	"os"
	"testing"
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
