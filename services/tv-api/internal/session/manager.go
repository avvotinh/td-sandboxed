package session

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/avvotinh/tv-api/internal/protocol"
)

// Session represents a TradingView session (quote or chart).
type Session interface {
	// ID returns the unique session identifier.
	ID() string

	// Type returns the session type (quote or chart).
	Type() string

	// OnData handles incoming packet data for this session.
	OnData(packet protocol.Packet) error

	// Close closes the session and cleans up resources.
	Close() error
}

// Manager manages multiple sessions with thread-safe operations.
type Manager struct {
	sessions map[string]Session
	mu       sync.RWMutex
	ctx      context.Context
	wg       sync.WaitGroup
	logger   *slog.Logger
}

// NewManager creates a new session manager.
// Deprecated: Use NewManagerWithContext instead.
func NewManager() *Manager {
	return NewManagerWithContext(context.Background(), slog.Default())
}

// NewManagerWithContext creates a new session manager with context and logger support.
func NewManagerWithContext(ctx context.Context, logger *slog.Logger) *Manager {
	if logger == nil {
		logger = slog.Default()
	}
	return &Manager{
		sessions: make(map[string]Session),
		ctx:      ctx,
		logger:   logger,
	}
}

// Register adds a session to the manager.
func (m *Manager) Register(session Session) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	id := session.ID()
	if _, exists := m.sessions[id]; exists {
		m.logger.Warn("attempted to register duplicate session",
			slog.String("session_id", id))
		return fmt.Errorf("session with ID %s already exists", id)
	}

	m.sessions[id] = session
	m.logger.Debug("session registered",
		slog.String("session_id", id),
		slog.String("type", session.Type()))
	return nil
}

// Unregister removes a session from the manager.
func (m *Manager) Unregister(sessionID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	session, exists := m.sessions[sessionID]
	if !exists {
		m.logger.Warn("attempted to unregister non-existent session",
			slog.String("session_id", sessionID))
		return fmt.Errorf("session with ID %s not found", sessionID)
	}

	delete(m.sessions, sessionID)
	m.logger.Debug("session unregistered",
		slog.String("session_id", sessionID),
		slog.String("type", session.Type()))
	return nil
}

// Get retrieves a session by ID.
func (m *Manager) Get(sessionID string) (Session, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	session, exists := m.sessions[sessionID]
	return session, exists
}

// RoutePacket routes a packet to the appropriate session.
// Returns an error if the session is not found or packet handling fails.
func (m *Manager) RoutePacket(sessionID string, packet protocol.Packet) error {
	session, exists := m.Get(sessionID)
	if !exists {
		return fmt.Errorf("session %s not found", sessionID)
	}

	return session.OnData(packet)
}

// RoutePacketBatch routes a batch of packets to the appropriate session.
// This allows sessions to detect packet sequences like "du" + "timescale_update"
// which indicates a confirmed closed candle in TradingView protocol.
func (m *Manager) RoutePacketBatch(sessionID string, packets []protocol.Packet) error {
	session, exists := m.Get(sessionID)
	if !exists {
		return fmt.Errorf("session %s not found", sessionID)
	}

	// Check if session supports batch processing
	type BatchProcessor interface {
		OnDataBatch(packets []protocol.Packet) error
	}

	if batchSession, ok := session.(BatchProcessor); ok {
		// Use batch processing if supported
		return batchSession.OnDataBatch(packets)
	}

	// Fallback: process packets individually
	for _, packet := range packets {
		if err := session.OnData(packet); err != nil {
			return err
		}
	}

	return nil
}

// Count returns the number of registered sessions.
func (m *Manager) Count() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.sessions)
}

// CloseAll closes all registered sessions.
func (m *Manager) CloseAll() error {
	m.mu.Lock()
	sessions := make([]Session, 0, len(m.sessions))
	for _, session := range m.sessions {
		sessions = append(sessions, session)
	}
	m.sessions = make(map[string]Session)
	m.mu.Unlock()

	m.logger.Info("closing all sessions",
		slog.Int("count", len(sessions)),
		slog.String("event_type", "shutdown"))

	var firstErr error
	for _, session := range sessions {
		if err := session.Close(); err != nil && firstErr == nil {
			m.logger.Error("failed to close session",
				slog.String("session_id", session.ID()),
				slog.String("event_type", "error"),
				slog.Any("error", err))
			firstErr = err
		} else {
			m.logger.Debug("session closed successfully",
				slog.String("session_id", session.ID()),
				slog.String("event_type", "disconnected"))
		}
	}

	return firstErr
}

// Shutdown gracefully shuts down the session manager with a timeout.
// It cancels the context, closes all sessions, and waits for goroutines to complete.
func (m *Manager) Shutdown(timeout time.Duration) error {
	m.logger.Info("initiating shutdown",
		slog.Duration("timeout", timeout),
		slog.String("event_type", "shutdown"))

	// Close all sessions first
	if err := m.CloseAll(); err != nil {
		m.logger.Warn("errors occurred during session closure",
			slog.String("event_type", "error"),
			slog.Any("error", err))
	}

	// Wait for all goroutines to complete with timeout
	done := make(chan struct{})
	go func() {
		m.wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		m.logger.Info("shutdown completed successfully",
			slog.String("event_type", "shutdown"))
		return nil
	case <-time.After(timeout):
		m.logger.Error("shutdown timed out waiting for goroutines",
			slog.Duration("timeout", timeout),
			slog.String("event_type", "error"))
		return fmt.Errorf("shutdown timed out after %s", timeout)
	}
}

// AddGoroutine increments the WaitGroup counter for a new goroutine.
// The caller must ensure Done() is called when the goroutine completes.
func (m *Manager) AddGoroutine() {
	m.wg.Add(1)
}

// DoneGoroutine decrements the WaitGroup counter when a goroutine completes.
func (m *Manager) DoneGoroutine() {
	m.wg.Done()
}

// Wait blocks until all goroutines tracked by the WaitGroup have completed.
func (m *Manager) Wait() {
	m.wg.Wait()
}

// Context returns the manager's context for cancellation propagation.
func (m *Manager) Context() context.Context {
	return m.ctx
}

// GenSessionID generates a unique session ID with the specified prefix.
// Format: <prefix>_<random_12_chars>
// Examples: qs_a1b2c3d4e5f6, cs_9z8y7x6w5v4u
func GenSessionID(prefix string) string {
	// Generate 6 random bytes (will be 12 hex characters)
	randomBytes := make([]byte, 6)
	if _, err := rand.Read(randomBytes); err != nil {
		// Fallback to a simpler random generation if crypto/rand fails
		// This should never happen in practice
		return fmt.Sprintf("%s_%d", prefix, randomInt63())
	}

	randomStr := hex.EncodeToString(randomBytes)
	return fmt.Sprintf("%s_%s", prefix, randomStr)
}

// randomInt63 is a fallback for session ID generation.
// This is only used if crypto/rand fails (which should never happen).
func randomInt63() int64 {
	b := make([]byte, 8)
	rand.Read(b)
	return int64(b[0]) | int64(b[1])<<8 | int64(b[2])<<16 | int64(b[3])<<24 |
		int64(b[4])<<32 | int64(b[5])<<40 | int64(b[6])<<48 | int64(b[7])<<56
}
