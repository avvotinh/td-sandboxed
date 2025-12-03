package config

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

// Subscription represents a single symbol-timeframe pair to monitor for chart data.
type Subscription struct {
	// Symbol is the trading symbol in format "EXCHANGE:TICKER"
	// Examples: "NASDAQ:AAPL", "BINANCE:BTCUSDT", "OANDA:XAUUSD"
	Symbol string `yaml:"symbol" validate:"required,symbol_format"`

	// Timeframe is the chart interval
	// Allowed values: "1", "5", "15", "30", "60", "D", "W", "M"
	Timeframe string `yaml:"timeframe" validate:"required,oneof=1 5 15 30 60 D W M"`
}

// QuoteSubscription represents a single symbol to monitor for real-time quote data.
type QuoteSubscription struct {
	// Symbol is the trading symbol in format "EXCHANGE:TICKER"
	// Examples: "NASDAQ:AAPL", "BINANCE:BTCUSDT", "OANDA:XAUUSD"
	Symbol string `yaml:"symbol" validate:"required,symbol_format"`
}

// LoggingConfig represents logging configuration.
type LoggingConfig struct {
	// Level is the log level: debug, info, warn, error
	// Default: "info"
	Level string `yaml:"level" validate:"omitempty,oneof=debug info warn error"`

	// Format is the log format: text, json
	// Default: "text"
	Format string `yaml:"format" validate:"omitempty,oneof=text json"`
}

// Configuration represents the root configuration structure.
type Configuration struct {
	// Subscriptions is the list of symbol-timeframe pairs to monitor for chart data
	// Constraints: max=50 (at least one of Subscriptions or QuoteSubscriptions must be present)
	Subscriptions []Subscription `yaml:"subscriptions,omitempty" validate:"omitempty,max=50,dive"`

	// QuoteSubscriptions is the list of symbols to monitor for real-time quote data
	// Constraints: max=50 (at least one of Subscriptions or QuoteSubscriptions must be present)
	QuoteSubscriptions []QuoteSubscription `yaml:"quote_subscriptions,omitempty" validate:"omitempty,max=50,dive"`

	// Logging configuration (optional)
	Logging LoggingConfig `yaml:"logging,omitempty"`
}

// LoadConfig loads and parses a YAML configuration file.
// It performs YAML parsing but does NOT validate the configuration.
// Call ValidateConfig separately to validate the loaded configuration.
func LoadConfig(filename string) (*Configuration, error) {
	// Read file
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	// Parse YAML
	var config Configuration
	if err := yaml.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("failed to parse YAML: %w", err)
	}

	// Apply defaults for logging if not specified
	if config.Logging.Level == "" {
		config.Logging.Level = "info"
	}
	if config.Logging.Format == "" {
		config.Logging.Format = "text"
	}

	return &config, nil
}
