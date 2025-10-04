package config

import (
	"errors"
	"os"
	"strconv"
)

// Config holds application configuration
type Config struct {
	TradingViewWSURL    string
	TradingViewUsername string
	TradingViewPassword string
	RedisHost           string
	RedisPort           int
	RedisPassword       string
	RedisDB             int
}

// Load reads configuration from environment variables
// Following Coding Standard Rule #1: No direct environment variable access outside config package
func Load() (*Config, error) {
	// Parse Redis port (default 6379)
	redisPort := 6379
	if portStr := os.Getenv("REDIS_PORT"); portStr != "" {
		if p, err := strconv.Atoi(portStr); err == nil {
			redisPort = p
		}
	}

	// Parse Redis DB (default 0)
	redisDB := 0
	if dbStr := os.Getenv("REDIS_DB"); dbStr != "" {
		if db, err := strconv.Atoi(dbStr); err == nil {
			redisDB = db
		}
	}

	cfg := &Config{
		TradingViewWSURL:    os.Getenv("TRADINGVIEW_WS_URL"),
		TradingViewUsername: os.Getenv("TRADINGVIEW_USERNAME"),
		TradingViewPassword: os.Getenv("TRADINGVIEW_PASSWORD"),
		RedisHost:           os.Getenv("REDIS_HOST"),
		RedisPort:           redisPort,
		RedisPassword:       os.Getenv("REDIS_PASSWORD"),
		RedisDB:             redisDB,
	}

	// Validate required config values
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	return cfg, nil
}

// Validate ensures all required configuration values are present
func (c *Config) Validate() error {
	if c.TradingViewWSURL == "" {
		return errors.New("TRADINGVIEW_WS_URL is required")
	}
	if c.TradingViewUsername == "" {
		return errors.New("TRADINGVIEW_USERNAME is required")
	}
	if c.TradingViewPassword == "" {
		return errors.New("TRADINGVIEW_PASSWORD is required")
	}
	if c.RedisHost == "" {
		return errors.New("REDIS_HOST is required")
	}
	if c.RedisPort <= 0 {
		return errors.New("REDIS_PORT must be positive")
	}
	return nil
}
