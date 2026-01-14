// Package queue provides message queueing with retry logic for notifications.
package queue

import (
	"context"
	"log"
	"sync"
	"time"
)

// Sender defines the interface for sending messages.
type Sender interface {
	SendMessage(text string) error
}

// Message represents a queued message with retry metadata.
type Message struct {
	Text      string
	Attempts  int
	NextRetry time.Time
}

// MessageQueue provides in-memory message queueing with retry for failed sends.
// Ensures fire-and-forget behavior: Enqueue returns immediately, never blocking trading.
type MessageQueue struct {
	sender         Sender
	queue          []Message
	mu             sync.Mutex
	maxRetries     int
	baseDelay      time.Duration
	stopCh         chan struct{}
	wg             sync.WaitGroup
	processingDone chan struct{}
}

// NewMessageQueue creates a new message queue with the given sender.
func NewMessageQueue(sender Sender, maxRetries int, baseDelay time.Duration) *MessageQueue {
	return &MessageQueue{
		sender:         sender,
		queue:          make([]Message, 0),
		maxRetries:     maxRetries,
		baseDelay:      baseDelay,
		stopCh:         make(chan struct{}),
		processingDone: make(chan struct{}),
	}
}

// Start begins the background queue processor.
func (q *MessageQueue) Start(ctx context.Context) {
	q.wg.Add(1)
	go q.processLoop(ctx)
}

// Stop signals the queue processor to stop and waits for it to finish.
func (q *MessageQueue) Stop() {
	close(q.stopCh)
	q.wg.Wait()
}

// Enqueue adds a message to the queue for sending. Returns immediately (fire-and-forget).
// This method NEVER blocks, ensuring trading operations are not affected.
func (q *MessageQueue) Enqueue(text string) {
	q.mu.Lock()
	defer q.mu.Unlock()

	q.queue = append(q.queue, Message{
		Text:      text,
		Attempts:  0,
		NextRetry: time.Now(),
	})
}

// QueueLength returns the current number of messages in the queue.
func (q *MessageQueue) QueueLength() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.queue)
}

// processLoop processes messages in the queue with retry logic.
func (q *MessageQueue) processLoop(ctx context.Context) {
	defer q.wg.Done()
	defer close(q.processingDone)

	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("Message queue stopping due to context cancellation")
			return
		case <-q.stopCh:
			log.Println("Message queue stopping")
			return
		case <-ticker.C:
			q.processMessages()
		}
	}
}

// processMessages attempts to send messages that are ready for retry.
func (q *MessageQueue) processMessages() {
	q.mu.Lock()
	if len(q.queue) == 0 {
		q.mu.Unlock()
		return
	}

	// Process messages ready for retry
	now := time.Now()
	remaining := make([]Message, 0, len(q.queue))

	for _, msg := range q.queue {
		if msg.NextRetry.After(now) {
			// Not ready for retry yet
			remaining = append(remaining, msg)
			continue
		}

		// Attempt to send
		msg.Attempts++
		err := q.sender.SendMessage(msg.Text)

		if err == nil {
			// Success - don't re-add to queue
			continue
		}

		// Failed - check if we should retry
		if msg.Attempts >= q.maxRetries {
			log.Printf("Message dropped after %d failed attempts: %v", msg.Attempts, err)
			continue
		}

		// Calculate next retry with exponential backoff
		delay := q.baseDelay * time.Duration(1<<(msg.Attempts-1)) // 1x, 2x, 4x...
		msg.NextRetry = now.Add(delay)
		remaining = append(remaining, msg)

		log.Printf("Message send failed (attempt %d/%d), retry in %v: %v",
			msg.Attempts, q.maxRetries, delay, err)
	}

	q.queue = remaining
	q.mu.Unlock()
}

// SendMessage implements the Sender interface for direct pass-through.
// This allows MessageQueue to be used where a Sender is expected.
func (q *MessageQueue) SendMessage(text string) error {
	q.Enqueue(text)
	return nil // Always returns nil (fire-and-forget)
}
