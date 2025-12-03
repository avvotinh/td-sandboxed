package config

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLoadConfig(t *testing.T) {
	tests := []struct {
		name        string
		content     string
		expectError bool
		errorMsg    string
		validate    func(*testing.T, *Configuration)
	}{
		{
			name: "valid config with single subscription",
			content: `subscriptions:
  - symbol: "NASDAQ:AAPL"
    timeframe: "1"`,
			expectError: false,
			validate: func(t *testing.T, cfg *Configuration) {
				require.NotNil(t, cfg)
				assert.Len(t, cfg.Subscriptions, 1)
				assert.Equal(t, "NASDAQ:AAPL", cfg.Subscriptions[0].Symbol)
				assert.Equal(t, "1", cfg.Subscriptions[0].Timeframe)
			},
		},
		{
			name: "valid config with multiple subscriptions",
			content: `subscriptions:
  - symbol: "NASDAQ:AAPL"
    timeframe: "1"
  - symbol: "BINANCE:BTCUSDT"
    timeframe: "5"
  - symbol: "OANDA:XAUUSD"
    timeframe: "60"`,
			expectError: false,
			validate: func(t *testing.T, cfg *Configuration) {
				require.NotNil(t, cfg)
				assert.Len(t, cfg.Subscriptions, 3)
				assert.Equal(t, "NASDAQ:AAPL", cfg.Subscriptions[0].Symbol)
				assert.Equal(t, "BINANCE:BTCUSDT", cfg.Subscriptions[1].Symbol)
				assert.Equal(t, "OANDA:XAUUSD", cfg.Subscriptions[2].Symbol)
			},
		},
		{
			name: "valid config with all timeframe formats",
			content: `subscriptions:
  - symbol: "NASDAQ:AAPL"
    timeframe: "1"
  - symbol: "NASDAQ:GOOGL"
    timeframe: "5"
  - symbol: "NASDAQ:MSFT"
    timeframe: "15"
  - symbol: "NASDAQ:AMZN"
    timeframe: "30"
  - symbol: "NASDAQ:TSLA"
    timeframe: "60"
  - symbol: "BINANCE:BTCUSDT"
    timeframe: "D"
  - symbol: "BINANCE:ETHUSDT"
    timeframe: "W"
  - symbol: "BINANCE:BNBUSDT"
    timeframe: "M"`,
			expectError: false,
			validate: func(t *testing.T, cfg *Configuration) {
				require.NotNil(t, cfg)
				assert.Len(t, cfg.Subscriptions, 8)
				timeframes := []string{"1", "5", "15", "30", "60", "D", "W", "M"}
				for i, tf := range timeframes {
					assert.Equal(t, tf, cfg.Subscriptions[i].Timeframe)
				}
			},
		},
		{
			name: "malformed YAML - invalid syntax",
			content: `subscriptions:
  - symbol: "NASDAQ:AAPL"
    timeframe: "1"
  - symbol: BINANCE:BTCUSDT"
    timeframe: "5`,
			expectError: true,
			errorMsg:    "failed to parse YAML",
		},
		{
			name:        "malformed YAML - invalid structure",
			content:     `this is not valid yaml: {{}}}`,
			expectError: true,
			errorMsg:    "failed to parse YAML",
		},
		{
			name:        "empty file",
			content:     "",
			expectError: false,
			validate: func(t *testing.T, cfg *Configuration) {
				require.NotNil(t, cfg)
				assert.Len(t, cfg.Subscriptions, 0)
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create temporary file
			tmpDir := t.TempDir()
			tmpFile := filepath.Join(tmpDir, "config.yaml")
			err := os.WriteFile(tmpFile, []byte(tt.content), 0644)
			require.NoError(t, err)

			// Load config
			cfg, err := LoadConfig(tmpFile)

			if tt.expectError {
				require.Error(t, err)
				if tt.errorMsg != "" {
					assert.Contains(t, err.Error(), tt.errorMsg)
				}
			} else {
				require.NoError(t, err)
				if tt.validate != nil {
					tt.validate(t, cfg)
				}
			}
		})
	}
}

func TestLoadConfig_MissingFile(t *testing.T) {
	_, err := LoadConfig("/nonexistent/path/config.yaml")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to read config file")
}
