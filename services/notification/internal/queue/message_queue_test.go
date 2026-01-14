// Package queue provides tests for the message queue.
package queue

import (
	"context"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// mockSender is a test double that tracks send calls.
type mockSender struct {
	calls      []string
	mu         sync.Mutex
	failCount  int
	failsUntil int
}

func (m *mockSender) SendMessage(text string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.calls = append(m.calls, text)

	if m.failCount < m.failsUntil {
		m.failCount++
		return &testError{msg: "simulated failure"}
	}
	return nil
}

func (m *mockSender) callCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.calls)
}

type testError struct {
	msg string
}

func (e *testError) Error() string {
	return e.msg
}

func TestMessageQueue_Enqueue_NonBlocking(t *testing.T) {
	sender := &mockSender{}
	q := NewMessageQueue(sender, 3, time.Millisecond)

	// Enqueue should return immediately
	start := time.Now()
	for i := 0; i < 100; i++ {
		q.Enqueue("test message")
	}
	elapsed := time.Since(start)

	// Should complete in < 10ms for 100 enqueues
	if elapsed > 10*time.Millisecond {
		t.Errorf("Enqueue took too long: %v (expected < 10ms)", elapsed)
	}

	// Queue should have all messages
	if q.QueueLength() != 100 {
		t.Errorf("Expected 100 messages in queue, got %d", q.QueueLength())
	}
}

func TestMessageQueue_ProcessMessages_Success(t *testing.T) {
	sender := &mockSender{}
	q := NewMessageQueue(sender, 3, time.Millisecond)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	q.Start(ctx)
	defer q.Stop()

	// Enqueue a message
	q.Enqueue("test message")

	// Wait for processing
	time.Sleep(200 * time.Millisecond)

	// Message should be sent
	if sender.callCount() != 1 {
		t.Errorf("Expected 1 send call, got %d", sender.callCount())
	}

	// Queue should be empty
	if q.QueueLength() != 0 {
		t.Errorf("Expected empty queue, got %d messages", q.QueueLength())
	}
}

func TestMessageQueue_Retry_OnFailure(t *testing.T) {
	sender := &mockSender{failsUntil: 2} // Fail first 2 attempts, succeed on 3rd
	q := NewMessageQueue(sender, 3, time.Millisecond)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	q.Start(ctx)
	defer q.Stop()

	// Enqueue a message
	q.Enqueue("test message")

	// Wait for retries
	time.Sleep(500 * time.Millisecond)

	// Should have attempted 3 times (2 failures + 1 success)
	if sender.callCount() != 3 {
		t.Errorf("Expected 3 send attempts, got %d", sender.callCount())
	}

	// Queue should be empty after success
	if q.QueueLength() != 0 {
		t.Errorf("Expected empty queue after success, got %d messages", q.QueueLength())
	}
}

func TestMessageQueue_MaxRetries_Exceeded(t *testing.T) {
	sender := &mockSender{failsUntil: 10} // Always fail
	q := NewMessageQueue(sender, 3, time.Millisecond)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	q.Start(ctx)
	defer q.Stop()

	// Enqueue a message
	q.Enqueue("test message")

	// Wait for max retries
	time.Sleep(500 * time.Millisecond)

	// Should have attempted max times
	if sender.callCount() != 3 {
		t.Errorf("Expected 3 send attempts (max retries), got %d", sender.callCount())
	}

	// Queue should be empty (message dropped)
	if q.QueueLength() != 0 {
		t.Errorf("Expected empty queue after max retries, got %d messages", q.QueueLength())
	}
}

func TestMessageQueue_FireAndForget_NeverBlocks(t *testing.T) {
	// Create a slow sender that blocks
	var sendCount atomic.Int32
	slowSender := &blockingSender{
		delay:     100 * time.Millisecond,
		sendCount: &sendCount,
	}

	q := NewMessageQueue(slowSender, 3, time.Millisecond)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	q.Start(ctx)
	defer q.Stop()

	// Enqueue should return immediately even with slow sender
	start := time.Now()
	q.Enqueue("slow message")
	elapsed := time.Since(start)

	// Enqueue MUST complete immediately (< 1ms)
	if elapsed > time.Millisecond {
		t.Errorf("Enqueue blocked for %v (should be < 1ms)", elapsed)
	}
}

type blockingSender struct {
	delay     time.Duration
	sendCount *atomic.Int32
}

func (s *blockingSender) SendMessage(text string) error {
	time.Sleep(s.delay)
	s.sendCount.Add(1)
	return nil
}

func TestMessageQueue_Stop_GracefulShutdown(t *testing.T) {
	sender := &mockSender{}
	q := NewMessageQueue(sender, 3, time.Millisecond)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	q.Start(ctx)

	// Give processor time to start
	time.Sleep(50 * time.Millisecond)

	// Stop should complete without hanging
	done := make(chan struct{})
	go func() {
		q.Stop()
		close(done)
	}()

	select {
	case <-done:
		// Success
	case <-time.After(time.Second):
		t.Error("Stop() did not complete within 1 second")
	}
}

func TestNewMessageQueue(t *testing.T) {
	sender := &mockSender{}
	q := NewMessageQueue(sender, 5, time.Second)

	if q == nil {
		t.Error("Expected queue to be created, got nil")
	}
	if q.maxRetries != 5 {
		t.Errorf("Expected maxRetries=5, got %d", q.maxRetries)
	}
	if q.baseDelay != time.Second {
		t.Errorf("Expected baseDelay=1s, got %v", q.baseDelay)
	}
}

func TestMessageQueue_SendMessage_Interface(t *testing.T) {
	sender := &mockSender{}
	q := NewMessageQueue(sender, 3, time.Millisecond)

	// SendMessage should enqueue and return nil (fire-and-forget)
	err := q.SendMessage("test via interface")
	if err != nil {
		t.Errorf("SendMessage should always return nil, got: %v", err)
	}

	if q.QueueLength() != 1 {
		t.Errorf("Expected 1 message in queue, got %d", q.QueueLength())
	}
}
