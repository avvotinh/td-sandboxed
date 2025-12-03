package config

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidateConfig(t *testing.T) {
	tests := []struct {
		name        string
		config      *Configuration
		expectError bool
		errorMsg    string
	}{
		{
			name: "valid config with single subscription",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"},
				},
			},
			expectError: false,
		},
		{
			name: "valid config with maximum subscriptions (50)",
			config: &Configuration{
				Subscriptions: make([]Subscription, 50),
			},
			expectError: false,
		},
		{
			name:        "invalid - nil configuration",
			config:      nil,
			expectError: true,
			errorMsg:    "configuration cannot be nil",
		},
		{
			name: "invalid - empty subscriptions array",
			config: &Configuration{
				Subscriptions: []Subscription{},
			},
			expectError: true,
			errorMsg:    "at least 1 subscription(s) required",
		},
		{
			name: "invalid - exceeds maximum subscriptions (51)",
			config: &Configuration{
				Subscriptions: make([]Subscription, 51),
			},
			expectError: true,
			errorMsg:    "maximum 50 subscriptions allowed (found 51)",
		},
		{
			name: "invalid - missing symbol",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "", Timeframe: "1"},
				},
			},
			expectError: true,
			errorMsg:    "field 'symbol' is required",
		},
		{
			name: "invalid - missing timeframe",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: ""},
				},
			},
			expectError: true,
			errorMsg:    "field 'timeframe' is required",
		},
		{
			name: "invalid - wrong symbol format (missing exchange)",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "AAPL", Timeframe: "1"},
				},
			},
			expectError: true,
			errorMsg:    "symbol 'AAPL' must be in format 'EXCHANGE:TICKER'",
		},
		{
			name: "invalid - wrong symbol format (empty exchange)",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: ":AAPL", Timeframe: "1"},
				},
			},
			expectError: true,
			errorMsg:    "symbol ':AAPL' must be in format 'EXCHANGE:TICKER'",
		},
		{
			name: "invalid - wrong symbol format (empty ticker)",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:", Timeframe: "1"},
				},
			},
			expectError: true,
			errorMsg:    "symbol 'NASDAQ:' must be in format 'EXCHANGE:TICKER'",
		},
		{
			name: "invalid - wrong symbol format (multiple colons)",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL:EXTRA", Timeframe: "1"},
				},
			},
			expectError: true,
			errorMsg:    "symbol 'NASDAQ:AAPL:EXTRA' must be in format 'EXCHANGE:TICKER'",
		},
		{
			name: "invalid - wrong timeframe (not in allowed list)",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "2"},
				},
			},
			expectError: true,
			errorMsg:    "field 'timeframe' must be one of: 1 5 15 30 60 D W M",
		},
		{
			name: "invalid - wrong timeframe (lowercase)",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "d"},
				},
			},
			expectError: true,
			errorMsg:    "field 'timeframe' must be one of: 1 5 15 30 60 D W M",
		},
		{
			name: "valid - all allowed timeframes",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"},
					{Symbol: "NASDAQ:GOOGL", Timeframe: "5"},
					{Symbol: "NASDAQ:MSFT", Timeframe: "15"},
					{Symbol: "NASDAQ:AMZN", Timeframe: "30"},
					{Symbol: "NASDAQ:TSLA", Timeframe: "60"},
					{Symbol: "BINANCE:BTCUSDT", Timeframe: "D"},
					{Symbol: "BINANCE:ETHUSDT", Timeframe: "W"},
					{Symbol: "BINANCE:BNBUSDT", Timeframe: "M"},
				},
			},
			expectError: false,
		},
	}

	// Initialize valid subscriptions for maximum test case
	for i := range tests {
		if tests[i].name == "valid config with maximum subscriptions (50)" {
			for j := 0; j < 50; j++ {
				tests[i].config.Subscriptions[j] = Subscription{
					Symbol:    "NASDAQ:AAPL",
					Timeframe: "1",
				}
			}
		}
		if tests[i].name == "invalid - exceeds maximum subscriptions (51)" {
			for j := 0; j < 51; j++ {
				tests[i].config.Subscriptions[j] = Subscription{
					Symbol:    "NASDAQ:AAPL",
					Timeframe: "1",
				}
			}
		}
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateConfig(tt.config)

			if tt.expectError {
				require.Error(t, err)
				if tt.errorMsg != "" {
					assert.Contains(t, err.Error(), tt.errorMsg)
				}
			} else {
				assert.NoError(t, err)
			}
		})
	}
}

func TestDeduplicateSubscriptions(t *testing.T) {
	tests := []struct {
		name             string
		input            *Configuration
		expectedCount    int
		expectedWarnings []string
	}{
		{
			name: "no duplicates",
			input: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"},
					{Symbol: "BINANCE:BTCUSDT", Timeframe: "5"},
					{Symbol: "OANDA:XAUUSD", Timeframe: "60"},
				},
			},
			expectedCount:    3,
			expectedWarnings: []string{},
		},
		{
			name: "duplicate symbol-timeframe pair",
			input: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"},
					{Symbol: "BINANCE:BTCUSDT", Timeframe: "5"},
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"}, // Duplicate
				},
			},
			expectedCount: 2,
			expectedWarnings: []string{
				"duplicate subscription removed",
				"NASDAQ:AAPL",
				"timeframe=1",
			},
		},
		{
			name: "same symbol different timeframes (not duplicate)",
			input: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"},
					{Symbol: "NASDAQ:AAPL", Timeframe: "5"},
					{Symbol: "NASDAQ:AAPL", Timeframe: "60"},
				},
			},
			expectedCount:    3,
			expectedWarnings: []string{},
		},
		{
			name: "multiple duplicates",
			input: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"},
					{Symbol: "BINANCE:BTCUSDT", Timeframe: "5"},
					{Symbol: "NASDAQ:AAPL", Timeframe: "1"},     // Duplicate 1
					{Symbol: "BINANCE:BTCUSDT", Timeframe: "5"}, // Duplicate 2
					{Symbol: "OANDA:XAUUSD", Timeframe: "60"},
				},
			},
			expectedCount: 3,
			expectedWarnings: []string{
				"duplicate subscription removed",
			},
		},
		{
			name:             "empty subscriptions",
			input:            &Configuration{Subscriptions: []Subscription{}},
			expectedCount:    0,
			expectedWarnings: []string{},
		},
		{
			name:             "nil configuration",
			input:            nil,
			expectedCount:    0,
			expectedWarnings: []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Capture log output
			var logBuf bytes.Buffer
			logger := slog.New(slog.NewTextHandler(&logBuf, &slog.HandlerOptions{
				Level: slog.LevelDebug,
			}))

			// Run deduplication
			DeduplicateSubscriptions(tt.input, logger)

			// Check count
			if tt.input != nil {
				assert.Len(t, tt.input.Subscriptions, tt.expectedCount)
			}

			// Check log warnings
			logOutput := logBuf.String()
			for _, warning := range tt.expectedWarnings {
				assert.Contains(t, logOutput, warning, "Expected warning message not found in logs")
			}

			// If no warnings expected, verify no warning messages in logs
			if len(tt.expectedWarnings) == 0 && tt.input != nil && len(tt.input.Subscriptions) > 0 {
				assert.NotContains(t, logOutput, "duplicate subscription removed")
			}
		})
	}
}

func TestDeduplicateSubscriptions_PreservesOrder(t *testing.T) {
	input := &Configuration{
		Subscriptions: []Subscription{
			{Symbol: "NASDAQ:AAPL", Timeframe: "1"},
			{Symbol: "BINANCE:BTCUSDT", Timeframe: "5"},
			{Symbol: "OANDA:XAUUSD", Timeframe: "60"},
			{Symbol: "NASDAQ:AAPL", Timeframe: "1"}, // Duplicate - should be removed
		},
	}

	logger := slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil))
	DeduplicateSubscriptions(input, logger)

	require.Len(t, input.Subscriptions, 3)
	assert.Equal(t, "NASDAQ:AAPL", input.Subscriptions[0].Symbol)
	assert.Equal(t, "BINANCE:BTCUSDT", input.Subscriptions[1].Symbol)
	assert.Equal(t, "OANDA:XAUUSD", input.Subscriptions[2].Symbol)
}

func TestFormatValidationErrors(t *testing.T) {
	tests := []struct {
		name   string
		config *Configuration
		checks []string
	}{
		{
			name: "multiple validation errors",
			config: &Configuration{
				Subscriptions: []Subscription{
					{Symbol: "AAPL", Timeframe: "2"},
				},
			},
			checks: []string{
				"configuration validation failed",
				"symbol 'AAPL' must be in format 'EXCHANGE:TICKER'",
				"field 'timeframe' must be one of: 1 5 15 30 60 D W M",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateConfig(tt.config)
			require.Error(t, err)

			errorMsg := err.Error()
			for _, check := range tt.checks {
				assert.Contains(t, errorMsg, check)
			}
		})
	}
}

func TestValidateSymbolFormat(t *testing.T) {
	tests := []struct {
		symbol string
		valid  bool
	}{
		{"NASDAQ:AAPL", true},
		{"BINANCE:BTCUSDT", true},
		{"OANDA:XAUUSD", true},
		{"AAPL", false},              // Missing exchange
		{":AAPL", false},             // Empty exchange
		{"NASDAQ:", false},           // Empty ticker
		{"NASDAQ:AAPL:EXTRA", false}, // Multiple colons
		{"", false},                  // Empty string
		{"NOCOLON", false},           // No colon
	}

	for _, tt := range tests {
		t.Run(tt.symbol, func(t *testing.T) {
			config := &Configuration{
				Subscriptions: []Subscription{
					{Symbol: tt.symbol, Timeframe: "1"},
				},
			}

			err := ValidateConfig(config)

			if tt.valid {
				// If symbol is valid, we should not get symbol_format error
				if err != nil {
					assert.NotContains(t, err.Error(), "must be in format 'EXCHANGE:TICKER'")
				}
			} else {
				require.Error(t, err)
				// Check that error is about symbol format or required field
				errMsg := strings.ToLower(err.Error())
				assert.True(t,
					strings.Contains(errMsg, "exchange:ticker") || strings.Contains(errMsg, "required"),
					"Expected symbol format error, got: %s", err.Error())
			}
		})
	}
}
