package auth

import (
	"fmt"
	"os"

	"github.com/joho/godotenv"
)

// Credentials holds TradingView session authentication credentials.
type Credentials struct {
	SessionID   string
	SessionSign string
}

// LoadFromEnv loads credentials from environment variables.
// It first tries to load from a .env file if it exists, then reads the environment variables.
// Required environment variables:
// - SESSION_ID: The sessionid cookie value from tradingview.com
// - SESSION_SIGN: The sessionid_sign cookie value from tradingview.com
func LoadFromEnv() (*Credentials, error) {
	// Try to load .env file (ignore error if it doesn't exist)
	_ = godotenv.Load()

	sessionID := os.Getenv("SESSION_ID")
	sessionSign := os.Getenv("SESSION_SIGN")

	// Validate credentials
	if sessionID == "" {
		return nil, fmt.Errorf("SESSION_ID environment variable is required")
	}

	if sessionSign == "" {
		return nil, fmt.Errorf("SESSION_SIGN environment variable is required")
	}

	return &Credentials{
		SessionID:   sessionID,
		SessionSign: sessionSign,
	}, nil
}

// Validate checks if the credentials are valid (non-empty).
func (c *Credentials) Validate() error {
	if c.SessionID == "" {
		return fmt.Errorf("session ID is empty")
	}

	if c.SessionSign == "" {
		return fmt.Errorf("session sign is empty")
	}

	return nil
}
