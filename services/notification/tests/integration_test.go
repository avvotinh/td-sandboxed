// Package tests provides integration tests for the notification service.
package tests

import (
	"testing"

	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/subscriber"
)

func TestSubscriberChannels(t *testing.T) {
	// Verify subscriber returns expected channel list
	cfg := &config.Config{
		RedisURL: "localhost:6379",
	}

	sub := subscriber.New(cfg)
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
		RedisURL:      "localhost:6379",
		RedisPassword: "",
	}

	sub := subscriber.New(cfg)
	if sub == nil {
		t.Error("Expected subscriber to be created, got nil")
	}
}
