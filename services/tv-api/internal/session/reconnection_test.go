package session

import (
	"testing"
	"time"

	"github.com/cenkalti/backoff/v4"
	"github.com/stretchr/testify/assert"
)

func TestCreateBackoff(t *testing.T) {
	tests := []struct {
		name                    string
		wantInitialInterval     time.Duration
		wantMaxInterval         time.Duration
		wantMultiplier          float64
		wantRandomizationFactor float64
		wantMaxElapsedTime      time.Duration
	}{
		{
			name:                    "default configuration",
			wantInitialInterval:     1 * time.Second,
			wantMaxInterval:         60 * time.Second,
			wantMultiplier:          2.0,
			wantRandomizationFactor: 0.5,
			wantMaxElapsedTime:      0, // unlimited retries
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := createBackoff()

			// Type assertion to access configuration
			eb, ok := b.(*backoff.ExponentialBackOff)
			assert.True(t, ok, "backoff should be *backoff.ExponentialBackOff")

			assert.Equal(t, tt.wantInitialInterval, eb.InitialInterval, "InitialInterval should be 1s")
			assert.Equal(t, tt.wantMaxInterval, eb.MaxInterval, "MaxInterval should be 60s")
			assert.Equal(t, tt.wantMultiplier, eb.Multiplier, "Multiplier should be 2.0")
			assert.Equal(t, tt.wantRandomizationFactor, eb.RandomizationFactor, "RandomizationFactor should be 0.5")
			assert.Equal(t, tt.wantMaxElapsedTime, eb.MaxElapsedTime, "MaxElapsedTime should be 0 (unlimited)")
		})
	}
}

func TestBackoffSequence(t *testing.T) {
	b := createBackoff()
	eb := b.(*backoff.ExponentialBackOff)
	eb.RandomizationFactor = 0 // Disable jitter for predictable testing

	expectedIntervals := []time.Duration{
		1 * time.Second,
		2 * time.Second,
		4 * time.Second,
		8 * time.Second,
		16 * time.Second,
		32 * time.Second,
		60 * time.Second, // capped at MaxInterval
		60 * time.Second, // stays at MaxInterval
	}

	for i, expected := range expectedIntervals {
		interval := b.NextBackOff()
		assert.Equal(t, expected, interval, "retry %d should have interval %s", i+1, expected)
	}
}

func TestBackoffReset(t *testing.T) {
	b := createBackoff()
	eb := b.(*backoff.ExponentialBackOff)
	eb.RandomizationFactor = 0 // Disable jitter

	// Advance backoff several times
	b.NextBackOff()
	b.NextBackOff()
	interval := b.NextBackOff()
	assert.Equal(t, 4*time.Second, interval, "third interval should be 4s")

	// Reset backoff
	b.Reset()

	// Should start from initial interval again
	interval = b.NextBackOff()
	assert.Equal(t, 1*time.Second, interval, "after reset, should start at 1s")
}
