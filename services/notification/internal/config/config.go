// Package config provides configuration loading for the notification service.
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/spf13/viper"
)

// Config holds all configuration for the notification service.
type Config struct {
	// Telegram configuration
	TelegramBotToken string
	TelegramChatID   int64

	// Redis configuration
	RedisURL      string
	RedisPassword string

	// Service configuration
	LogLevel string
	Debug    bool
}

// Load reads configuration from environment variables.
func Load() (*Config, error) {
	v := viper.New()

	// Set environment variable prefix
	v.SetEnvPrefix("NOTIFICATION")
	v.AutomaticEnv()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))

	// Set defaults
	v.SetDefault("log_level", "info")
	v.SetDefault("debug", false)
	v.SetDefault("redis_url", "redis:6379")

	// Also check for common env var names without prefix (using os.Getenv for test isolation)
	if token := os.Getenv("TELEGRAM_BOT_TOKEN"); token != "" {
		v.Set("telegram_bot_token", token)
	}
	if chatIDStr := os.Getenv("TELEGRAM_CHAT_ID"); chatIDStr != "" {
		if chatID, err := strconv.ParseInt(chatIDStr, 10, 64); err == nil {
			v.Set("telegram_chat_id", chatID)
		}
	}
	if redisURL := os.Getenv("REDIS_URL"); redisURL != "" {
		v.Set("redis_url", redisURL)
	}

	cfg := &Config{
		TelegramBotToken: v.GetString("telegram_bot_token"),
		TelegramChatID:   v.GetInt64("telegram_chat_id"),
		RedisURL:         v.GetString("redis_url"),
		RedisPassword:    v.GetString("redis_password"),
		LogLevel:         v.GetString("log_level"),
		Debug:            v.GetBool("debug"),
	}

	// Validate required configuration
	if cfg.TelegramBotToken == "" {
		return nil, fmt.Errorf("TELEGRAM_BOT_TOKEN is required")
	}

	return cfg, nil
}
