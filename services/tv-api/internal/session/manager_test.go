package session

import (
	"context"
	"log/slog"
	"testing"

	"github.com/avvotinh/tv-api/internal/protocol"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// mockSession is a mock implementation of the Session interface for testing.
type mockSession struct {
	id   string
	typ  string
	data []protocol.Packet
}

func (m *mockSession) ID() string {
	return m.id
}

func (m *mockSession) Type() string {
	return m.typ
}

func (m *mockSession) OnData(packet protocol.Packet) error {
	m.data = append(m.data, packet)
	return nil
}

func (m *mockSession) Close() error {
	return nil
}

// TestRegisterSession tests registering a session with the manager.
func TestRegisterSession(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Create mock session
	sess := &mockSession{
		id:  "test_session_1",
		typ: "chart",
	}

	// Register session
	err := manager.Register(sess)
	require.NoError(t, err, "failed to register session")

	// Verify session count
	assert.Equal(t, 1, manager.Count(), "expected 1 session after registration")

	// Verify session can be retrieved
	retrieved, exists := manager.Get("test_session_1")
	assert.True(t, exists, "registered session should exist")
	assert.NotNil(t, retrieved, "retrieved session should not be nil")
	assert.Equal(t, "test_session_1", retrieved.ID(), "session IDs should match")
	assert.Equal(t, "chart", retrieved.Type(), "session types should match")
}

// TestRegisterDuplicateSession tests that registering a duplicate session ID fails.
func TestRegisterDuplicateSession(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Create and register first session
	sess1 := &mockSession{
		id:  "duplicate_id",
		typ: "chart",
	}
	err := manager.Register(sess1)
	require.NoError(t, err, "failed to register first session")

	// Attempt to register second session with same ID
	sess2 := &mockSession{
		id:  "duplicate_id",
		typ: "quote",
	}
	err = manager.Register(sess2)
	assert.Error(t, err, "registering duplicate session ID should fail")
	assert.Contains(t, err.Error(), "already exists", "error message should mention duplicate")

	// Verify only one session is registered
	assert.Equal(t, 1, manager.Count(), "expected only 1 session after duplicate registration attempt")

	// Verify the first session is still registered
	retrieved, exists := manager.Get("duplicate_id")
	assert.True(t, exists, "first session should still exist")
	assert.Equal(t, "chart", retrieved.Type(), "first session type should be preserved")
}

// TestUnregisterSession tests unregistering a session from the manager.
func TestUnregisterSession(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Create and register session
	sess := &mockSession{
		id:  "test_session_2",
		typ: "chart",
	}
	err := manager.Register(sess)
	require.NoError(t, err, "failed to register session")

	// Verify session is registered
	assert.Equal(t, 1, manager.Count(), "expected 1 session after registration")

	// Unregister session
	err = manager.Unregister("test_session_2")
	require.NoError(t, err, "failed to unregister session")

	// Verify session is removed
	assert.Equal(t, 0, manager.Count(), "expected 0 sessions after unregistration")

	// Verify session cannot be retrieved
	_, exists := manager.Get("test_session_2")
	assert.False(t, exists, "unregistered session should not exist")
}

// TestUnregisterNonExistentSession tests unregistering a session that doesn't exist.
func TestUnregisterNonExistentSession(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Attempt to unregister non-existent session
	err := manager.Unregister("non_existent_id")
	assert.Error(t, err, "unregistering non-existent session should fail")
	assert.Contains(t, err.Error(), "not found", "error message should mention session not found")
}

// TestRegisterMultipleSessions tests registering multiple sessions concurrently.
func TestRegisterMultipleSessions(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Register 5 different sessions
	sessions := []*mockSession{
		{id: "session_1", typ: "chart"},
		{id: "session_2", typ: "chart"},
		{id: "session_3", typ: "quote"},
		{id: "session_4", typ: "chart"},
		{id: "session_5", typ: "quote"},
	}

	for _, sess := range sessions {
		err := manager.Register(sess)
		require.NoError(t, err, "failed to register session %s", sess.ID())
	}

	// Verify all sessions are registered
	assert.Equal(t, 5, manager.Count(), "expected 5 sessions after registration")

	// Verify each session can be retrieved
	for _, sess := range sessions {
		retrieved, exists := manager.Get(sess.ID())
		assert.True(t, exists, "session %s should exist", sess.ID())
		assert.Equal(t, sess.ID(), retrieved.ID(), "session IDs should match")
		assert.Equal(t, sess.Type(), retrieved.Type(), "session types should match")
	}
}

// TestCloseAllSessions tests closing all registered sessions.
func TestCloseAllSessions(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Register multiple sessions
	sessions := []*mockSession{
		{id: "session_1", typ: "chart"},
		{id: "session_2", typ: "chart"},
		{id: "session_3", typ: "quote"},
	}

	for _, sess := range sessions {
		err := manager.Register(sess)
		require.NoError(t, err, "failed to register session %s", sess.ID())
	}

	// Verify sessions are registered
	assert.Equal(t, 3, manager.Count(), "expected 3 sessions after registration")

	// Close all sessions
	err := manager.CloseAll()
	assert.NoError(t, err, "failed to close all sessions")

	// Verify all sessions are unregistered
	assert.Equal(t, 0, manager.Count(), "expected 0 sessions after CloseAll")

	// Verify sessions cannot be retrieved
	for _, sess := range sessions {
		_, exists := manager.Get(sess.ID())
		assert.False(t, exists, "session %s should not exist after CloseAll", sess.ID())
	}
}

// TestRoutePacket tests routing a packet to the appropriate session.
func TestRoutePacket(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Create and register mock session
	sess := &mockSession{
		id:   "test_session",
		typ:  "chart",
		data: []protocol.Packet{},
	}
	err := manager.Register(sess)
	require.NoError(t, err, "failed to register session")

	// Create test packet
	packet := protocol.Packet{
		Type: "du",
		Data: []interface{}{"test_session", map[string]interface{}{"key": "value"}},
	}

	// Route packet to session
	err = manager.RoutePacket("test_session", packet)
	assert.NoError(t, err, "failed to route packet to session")

	// Verify session received the packet
	assert.Len(t, sess.data, 1, "session should have received 1 packet")
	assert.Equal(t, "du", sess.data[0].Type, "packet type should match")
}

// TestRoutePacketToNonExistentSession tests routing a packet to a non-existent session.
func TestRoutePacketToNonExistentSession(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Create test packet
	packet := protocol.Packet{
		Type: "du",
		Data: []interface{}{"non_existent_session", map[string]interface{}{"key": "value"}},
	}

	// Attempt to route packet to non-existent session
	err := manager.RoutePacket("non_existent_session", packet)
	assert.Error(t, err, "routing packet to non-existent session should fail")
	assert.Contains(t, err.Error(), "not found", "error message should mention session not found")
}

// TestConcurrentSessionOperations tests concurrent Register/Unregister operations.
func TestConcurrentSessionOperations(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Number of concurrent goroutines
	numGoroutines := 10

	// Channel to signal completion
	done := make(chan bool, numGoroutines)

	// Concurrent registration
	for i := 0; i < numGoroutines; i++ {
		go func(index int) {
			sess := &mockSession{
				id:  GenSessionID("concurrent"),
				typ: "chart",
			}
			err := manager.Register(sess)
			assert.NoError(t, err, "concurrent registration should succeed")
			done <- true
		}(i)
	}

	// Wait for all goroutines to complete
	for i := 0; i < numGoroutines; i++ {
		<-done
	}

	// Verify all sessions are registered
	assert.Equal(t, numGoroutines, manager.Count(),
		"expected %d sessions after concurrent registration", numGoroutines)
}

// TestWaitGroupTracking tests that the WaitGroup properly tracks goroutines.
func TestWaitGroupTracking(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Track 3 goroutines
	for i := 0; i < 3; i++ {
		manager.AddGoroutine()
	}

	// Simulate goroutines completing
	done := make(chan bool)
	go func() {
		manager.Wait()
		done <- true
	}()

	// Mark goroutines as done
	for i := 0; i < 3; i++ {
		manager.DoneGoroutine()
	}

	// Verify Wait() unblocks
	select {
	case <-done:
		// Success - Wait() unblocked
	case <-ctx.Done():
		t.Fatal("Wait() did not unblock after all goroutines completed")
	}
}

// TestMultipleSessionsSameSymbolDifferentTimeframes tests that the same symbol
// can have multiple independent sessions with different timeframes.
// This verifies User Story 3: Multi-Timeframe Data Collection per Symbol.
func TestMultipleSessionsSameSymbolDifferentTimeframes(t *testing.T) {
	ctx := context.Background()
	logger := slog.Default()
	manager := NewManagerWithContext(ctx, logger)

	// Create 3 sessions for the same "symbol" (using mock sessions with different IDs)
	// In real implementation, these would be chart sessions with different timeframes
	sessions := []*mockSession{
		{id: GenSessionID("cs"), typ: "chart"}, // Simulates NASDAQ:AAPL [1]
		{id: GenSessionID("cs"), typ: "chart"}, // Simulates NASDAQ:AAPL [5]
		{id: GenSessionID("cs"), typ: "chart"}, // Simulates NASDAQ:AAPL [60]
	}

	// Register all sessions
	for i, sess := range sessions {
		err := manager.Register(sess)
		require.NoError(t, err, "failed to register session %d", i)
	}

	// Verify all 3 sessions are registered
	assert.Equal(t, 3, manager.Count(), "expected 3 sessions to be registered")

	// Verify each session has a unique ID (this proves independence)
	sessionIDs := make(map[string]bool)
	for _, sess := range sessions {
		retrieved, exists := manager.Get(sess.ID())
		assert.True(t, exists, "session %s should exist", sess.ID())
		assert.Equal(t, sess.ID(), retrieved.ID(), "session IDs should match")

		// Track unique IDs
		assert.False(t, sessionIDs[sess.ID()], "session ID %s should be unique", sess.ID())
		sessionIDs[sess.ID()] = true
	}

	// Verify we have 3 unique session IDs
	assert.Equal(t, 3, len(sessionIDs), "expected 3 unique session IDs for same symbol different timeframes")

	// Verify removing one session doesn't affect others
	err := manager.Unregister(sessions[0].ID())
	require.NoError(t, err, "failed to unregister first session")

	assert.Equal(t, 2, manager.Count(), "expected 2 sessions after removing one")

	// Verify other sessions still exist
	_, exists := manager.Get(sessions[1].ID())
	assert.True(t, exists, "second session should still exist after first is removed")
	_, exists = manager.Get(sessions[2].ID())
	assert.True(t, exists, "third session should still exist after first is removed")
}
