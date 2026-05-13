package tradingview

import "time"

// FetchOption configures a FetchUntil / FetchRange invocation.
type FetchOption func(*fetchConfig)

// fetchConfig holds the resolved FetchUntil parameters. Callers never see
// this type directly — the With* functions are the public surface.
type fetchConfig struct {
	batchSize       int
	throttle        time.Duration
	responseTimeout time.Duration
	maxBatches      int
}

func defaultFetchConfig() fetchConfig {
	return fetchConfig{
		batchSize:       1000,
		throttle:        150 * time.Millisecond,
		responseTimeout: 2 * time.Second,
		maxBatches:      1000,
	}
}

// WithBatchSize sets the number of older bars requested per
// request_more_data call. The TradingView server caps responses well below
// this; values 500–2000 are practical. Defaults to 1000.
func WithBatchSize(n int) FetchOption {
	return func(c *fetchConfig) {
		if n > 0 {
			c.batchSize = n
		}
	}
}

// WithThrottle sets the delay between consecutive request_more_data calls
// to keep the free-tier rate limiter happy. Defaults to 150ms.
func WithThrottle(d time.Duration) FetchOption {
	return func(c *fetchConfig) {
		if d >= 0 {
			c.throttle = d
		}
	}
}

// WithResponseTimeout sets the maximum time to wait for an "update" event
// after a request_more_data call before treating the request as silent
// (which counts toward the same-streak terminal-detection logic). Defaults
// to 2s.
func WithResponseTimeout(d time.Duration) FetchOption {
	return func(c *fetchConfig) {
		if d > 0 {
			c.responseTimeout = d
		}
	}
}

// WithMaxBatches caps the number of request_more_data iterations FetchUntil
// will issue before returning an error. Acts as a safety net against
// runaway loops on malformed servers. Defaults to 1000 (≈1M bars at the
// default batch size).
func WithMaxBatches(n int) FetchOption {
	return func(c *fetchConfig) {
		if n > 0 {
			c.maxBatches = n
		}
	}
}
