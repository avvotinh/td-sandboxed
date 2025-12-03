package transport

import (
	"context"
	"fmt"
	"sync"
	"time"
)

// HeartbeatHandler manages ping/pong heartbeat for WebSocket connections.
type HeartbeatHandler struct {
	conn        WebSocketConn
	interval    time.Duration
	timeout     time.Duration
	pingCounter int
	mu          sync.Mutex
	stopChan    chan struct{}
	onPing      func(int)
	onPong      func(int)
	onTimeout   func()
	running     bool
}

// HeartbeatConfig contains configuration for the heartbeat handler.
type HeartbeatConfig struct {
	// Interval is the time between ping messages.
	Interval time.Duration

	// Timeout is the maximum time to wait for a pong response.
	Timeout time.Duration

	// OnPing is called when a ping is sent.
	OnPing func(pingID int)

	// OnPong is called when a pong is received.
	OnPong func(pingID int)

	// OnTimeout is called when a pong response times out.
	OnTimeout func()
}

// NewHeartbeatHandler creates a new heartbeat handler.
func NewHeartbeatHandler(conn WebSocketConn, config HeartbeatConfig) *HeartbeatHandler {
	if config.Interval == 0 {
		config.Interval = 30 * time.Second
	}
	if config.Timeout == 0 {
		config.Timeout = 10 * time.Second
	}

	return &HeartbeatHandler{
		conn:        conn,
		interval:    config.Interval,
		timeout:     config.Timeout,
		pingCounter: 0,
		stopChan:    make(chan struct{}),
		onPing:      config.OnPing,
		onPong:      config.OnPong,
		onTimeout:   config.OnTimeout,
		running:     false,
	}
}

// Start begins the heartbeat process.
func (h *HeartbeatHandler) Start(ctx context.Context) error {
	h.mu.Lock()
	if h.running {
		h.mu.Unlock()
		return fmt.Errorf("heartbeat already running")
	}
	h.running = true
	h.mu.Unlock()

	go h.run(ctx)
	return nil
}

// Stop stops the heartbeat process.
func (h *HeartbeatHandler) Stop() {
	h.mu.Lock()
	defer h.mu.Unlock()

	if !h.running {
		return
	}

	h.running = false
	close(h.stopChan)
}

// run is the main heartbeat loop.
func (h *HeartbeatHandler) run(ctx context.Context) {
	ticker := time.NewTicker(h.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-h.stopChan:
			return
		case <-ticker.C:
			if err := h.sendPing(); err != nil {
				// Connection error, stop heartbeat
				return
			}
		}
	}
}

// sendPing sends a ping message.
func (h *HeartbeatHandler) sendPing() error {
	h.mu.Lock()
	h.pingCounter++
	pingID := h.pingCounter
	h.mu.Unlock()

	// Note: The actual ping message format is handled by the protocol layer
	// This handler just manages the timing

	if h.onPing != nil {
		h.onPing(pingID)
	}

	return nil
}

// HandlePong handles a pong response.
func (h *HeartbeatHandler) HandlePong(pingID int) {
	if h.onPong != nil {
		h.onPong(pingID)
	}
}

// IsRunning returns true if the heartbeat is currently running.
func (h *HeartbeatHandler) IsRunning() bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.running
}
