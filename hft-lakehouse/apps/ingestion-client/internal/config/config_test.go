package config

import (
	"os"
	"strconv"
	"testing"
)

func TestLoad(t *testing.T) {
	tests := []struct {
		name    string
		envVars map[string]string
		wantErr bool
	}{
		{
			name: "valid config",
			envVars: map[string]string{
				"TRADINGVIEW_WS_URL":  "wss://test.example.com",
				"TRADINGVIEW_USERNAME": "testuser",
				"TRADINGVIEW_PASSWORD": "testpass",
				"REDIS_HOST":          "localhost",
				"REDIS_PORT":          "6379",
				"REDIS_DB":            "0",
			},
			wantErr: false,
		},
		{
			name: "valid config with defaults",
			envVars: map[string]string{
				"TRADINGVIEW_WS_URL":  "wss://test.example.com",
				"TRADINGVIEW_USERNAME": "testuser",
				"TRADINGVIEW_PASSWORD": "testpass",
				"REDIS_HOST":          "localhost",
			},
			wantErr: false,
		},
		{
			name: "missing redis host",
			envVars: map[string]string{
				"TRADINGVIEW_WS_URL":  "wss://test.example.com",
				"TRADINGVIEW_USERNAME": "testuser",
				"TRADINGVIEW_PASSWORD": "testpass",
			},
			wantErr: true,
		},
		{
			name: "missing ws url",
			envVars: map[string]string{
				"TRADINGVIEW_USERNAME": "testuser",
				"TRADINGVIEW_PASSWORD": "testpass",
				"REDIS_HOST":          "localhost",
			},
			wantErr: true,
		},
		{
			name: "missing username",
			envVars: map[string]string{
				"TRADINGVIEW_WS_URL":  "wss://test.example.com",
				"TRADINGVIEW_PASSWORD": "testpass",
				"REDIS_HOST":          "localhost",
			},
			wantErr: true,
		},
		{
			name: "missing password",
			envVars: map[string]string{
				"TRADINGVIEW_WS_URL":  "wss://test.example.com",
				"TRADINGVIEW_USERNAME": "testuser",
				"REDIS_HOST":          "localhost",
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clear environment
			os.Clearenv()

			// Set test environment variables
			for k, v := range tt.envVars {
				os.Setenv(k, v)
			}

			cfg, err := Load()

			if tt.wantErr {
				if err == nil {
					t.Errorf("Load() expected error but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Load() unexpected error = %v", err)
				return
			}

			if cfg == nil {
				t.Error("Load() returned nil config")
				return
			}

			// Verify config values match environment
			if cfg.TradingViewWSURL != tt.envVars["TRADINGVIEW_WS_URL"] {
				t.Errorf("TradingViewWSURL = %v, want %v", cfg.TradingViewWSURL, tt.envVars["TRADINGVIEW_WS_URL"])
			}
			if cfg.TradingViewUsername != tt.envVars["TRADINGVIEW_USERNAME"] {
				t.Errorf("TradingViewUsername = %v, want %v", cfg.TradingViewUsername, tt.envVars["TRADINGVIEW_USERNAME"])
			}
			if cfg.TradingViewPassword != tt.envVars["TRADINGVIEW_PASSWORD"] {
				t.Errorf("TradingViewPassword = %v, want %v", cfg.TradingViewPassword, tt.envVars["TRADINGVIEW_PASSWORD"])
			}
			if cfg.RedisHost != tt.envVars["REDIS_HOST"] {
				t.Errorf("RedisHost = %v, want %v", cfg.RedisHost, tt.envVars["REDIS_HOST"])
			}
			// Redis port and DB have defaults, so only check if explicitly set
			if portStr, ok := tt.envVars["REDIS_PORT"]; ok {
				expectedPort := 6379
				if p, err := strconv.Atoi(portStr); err == nil {
					expectedPort = p
				}
				if cfg.RedisPort != expectedPort {
					t.Errorf("RedisPort = %v, want %v", cfg.RedisPort, expectedPort)
				}
			}
		})
	}
}

func TestValidate(t *testing.T) {
	tests := []struct {
		name    string
		config  *Config
		wantErr bool
	}{
		{
			name: "valid config",
			config: &Config{
				TradingViewWSURL:    "wss://test.example.com",
				TradingViewUsername: "testuser",
				TradingViewPassword: "testpass",
				RedisHost:           "localhost",
				RedisPort:           6379,
			},
			wantErr: false,
		},
		{
			name: "empty ws url",
			config: &Config{
				TradingViewWSURL:    "",
				TradingViewUsername: "testuser",
				TradingViewPassword: "testpass",
				RedisHost:           "localhost",
				RedisPort:           6379,
			},
			wantErr: true,
		},
		{
			name: "empty username",
			config: &Config{
				TradingViewWSURL:    "wss://test.example.com",
				TradingViewUsername: "",
				TradingViewPassword: "testpass",
				RedisHost:           "localhost",
				RedisPort:           6379,
			},
			wantErr: true,
		},
		{
			name: "empty password",
			config: &Config{
				TradingViewWSURL:    "wss://test.example.com",
				TradingViewUsername: "testuser",
				TradingViewPassword: "",
				RedisHost:           "localhost",
				RedisPort:           6379,
			},
			wantErr: true,
		},
		{
			name: "empty redis host",
			config: &Config{
				TradingViewWSURL:    "wss://test.example.com",
				TradingViewUsername: "testuser",
				TradingViewPassword: "testpass",
				RedisHost:           "",
				RedisPort:           6379,
			},
			wantErr: true,
		},
		{
			name: "invalid redis port",
			config: &Config{
				TradingViewWSURL:    "wss://test.example.com",
				TradingViewUsername: "testuser",
				TradingViewPassword: "testpass",
				RedisHost:           "localhost",
				RedisPort:           0,
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.config.Validate()
			if (err != nil) != tt.wantErr {
				t.Errorf("Validate() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
