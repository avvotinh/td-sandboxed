package tradingview

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// stubFetchSession is a hand-rolled mock of the fetchSession interface that
// gives tests fine-grained control over batch arrival timing. It mirrors
// what session.ChartSession does at runtime: each RequestMoreData call
// triggers an injected callback that produces the next batch's "minimum
// timestamp" plus an update signal.
type stubFetchSession struct {
	mu sync.Mutex

	currentMin int64
	updateCh   chan struct{}

	requests   int32
	requestErr error

	// onRequest is called synchronously inside RequestMoreData. Used to
	// schedule the "server response": typically reduces currentMin and
	// pushes to updateCh.
	onRequest func(seriesID string, count int)
}

func newStubFetchSession(initialMin int64, buf int) *stubFetchSession {
	return &stubFetchSession{
		currentMin: initialMin,
		updateCh:   make(chan struct{}, buf),
	}
}

func (s *stubFetchSession) MinPeriodTime() int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.currentMin
}

func (s *stubFetchSession) RequestMoreData(seriesID string, count int) error {
	atomic.AddInt32(&s.requests, 1)
	if s.requestErr != nil {
		return s.requestErr
	}
	if s.onRequest != nil {
		s.onRequest(seriesID, count)
	}
	return nil
}

func (s *stubFetchSession) SubscribeUpdate(buf int) (<-chan struct{}, func()) {
	return s.updateCh, func() {}
}

func (s *stubFetchSession) signal() {
	select {
	case s.updateCh <- struct{}{}:
	default:
	}
}

// TestFetchUntil_StopsWhenThresholdReached verifies the happy path: the
// loop walks backward, reduces min ts each batch, then exits when min <=
// untilTs.
func TestFetchUntil_StopsWhenThresholdReached(t *testing.T) {
	stub := newStubFetchSession(2_000, 16)

	// Each request reduces min by 500.
	stub.onRequest = func(_ string, _ int) {
		stub.mu.Lock()
		stub.currentMin -= 500
		stub.mu.Unlock()
		stub.signal()
	}

	// Seed the initial-batch wait: emit one update before FetchUntil starts
	// the loop. This mirrors the create_series response landing.
	stub.signal()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := fetchUntil(ctx, stub, 1_100,
		WithBatchSize(500),
		WithThrottle(1*time.Millisecond),
		WithResponseTimeout(200*time.Millisecond))
	require.NoError(t, err)

	// 2000 → 1500 (1) → 1000 (2) ⇒ two requests, then check passes.
	assert.GreaterOrEqual(t, atomic.LoadInt32(&stub.requests), int32(2))
}

// TestFetchUntil_TerminalWhenNoProgress documents the "server out of data"
// handling: if min stays the same across two batches, FetchUntil treats
// that as terminal-success rather than infinite looping.
func TestFetchUntil_TerminalWhenNoProgress(t *testing.T) {
	stub := newStubFetchSession(2_000, 16)

	// onRequest signals an update but never reduces currentMin — the
	// server pretends to respond but has no older bars.
	stub.onRequest = func(_ string, _ int) {
		stub.signal()
	}
	stub.signal() // initial batch

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := fetchUntil(ctx, stub, 1_000,
		WithBatchSize(500),
		WithThrottle(1*time.Millisecond),
		WithResponseTimeout(200*time.Millisecond))
	require.NoError(t, err, "no-progress streak ≥ 2 must return nil, not error")

	// Should have stopped after detecting the streak — well below maxBatches.
	assert.Less(t, atomic.LoadInt32(&stub.requests), int32(10))
}

// TestFetchUntil_ContextCancellation verifies the loop bails immediately
// when the caller's context is cancelled.
func TestFetchUntil_ContextCancellation(t *testing.T) {
	stub := newStubFetchSession(2_000, 16)
	// Slow server: response never reduces min.
	stub.onRequest = func(_ string, _ int) {
		time.Sleep(50 * time.Millisecond)
		stub.signal()
	}
	stub.signal()

	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(30 * time.Millisecond)
		cancel()
	}()

	err := fetchUntil(ctx, stub, 1_000,
		WithBatchSize(500),
		WithThrottle(10*time.Millisecond),
		WithResponseTimeout(200*time.Millisecond))
	require.Error(t, err)
	assert.ErrorIs(t, err, context.Canceled)
}

// TestFetchUntil_RequestErrorWrapped checks that a transport-level Send
// error from RequestMoreData propagates as a wrapped error with batch
// context for debugging.
func TestFetchUntil_RequestErrorWrapped(t *testing.T) {
	stub := newStubFetchSession(2_000, 16)
	stub.requestErr = errors.New("websocket closed")
	stub.signal() // initial batch

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	err := fetchUntil(ctx, stub, 1_000,
		WithBatchSize(500),
		WithThrottle(1*time.Millisecond),
		WithResponseTimeout(50*time.Millisecond))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "fetch_until request")
	assert.Contains(t, err.Error(), "websocket closed")
}

// TestFetchUntil_MaxBatchesCap protects against infinite loops when the
// server keeps reporting fresh data but never gets older than the target.
func TestFetchUntil_MaxBatchesCap(t *testing.T) {
	stub := newStubFetchSession(5_000, 16)
	// Each request shifts min by 1 — far slower than the threshold gap.
	stub.onRequest = func(_ string, _ int) {
		stub.mu.Lock()
		stub.currentMin -= 1
		stub.mu.Unlock()
		stub.signal()
	}
	stub.signal()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := fetchUntil(ctx, stub, 1_000,
		WithBatchSize(1),
		WithThrottle(1*time.Millisecond),
		WithResponseTimeout(50*time.Millisecond),
		WithMaxBatches(10))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "max_batches=10")
}

// TestFetchUntil_NoInitialBatchTimesOut covers the early-fail when create_series
// never lands (e.g. invalid symbol, network drop before resolve).
func TestFetchUntil_NoInitialBatchTimesOut(t *testing.T) {
	stub := newStubFetchSession(0, 16)
	// No initial signal, no onRequest behaviour — silent server.

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	err := fetchUntil(ctx, stub, 1_000,
		WithThrottle(1*time.Millisecond),
		WithResponseTimeout(50*time.Millisecond))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "no initial batch")
}

// TestChartSession_FetchUntil_DelegatesToCore is a smoke test ensuring the
// public ChartSession.FetchUntil wrapper threads through to fetchUntil with
// the real session.ChartSession satisfying fetchSession. Uses the test-only
// EmitForTest / SetPeriodsForTest seams to avoid spinning a WebSocket.
func TestChartSession_FetchUntil_DelegatesToCore(t *testing.T) {
	bridge := &fakeBridge{}
	client := &Client{}
	innerSess := newTestChartSession(client, bridge)

	cs := &ChartSession{
		client:  client,
		session: innerSess,
		options: &ChartSessionOptions{Timeframe: "5"},
	}

	// Prime initial periods so the initial-batch wait succeeds immediately
	// after we emit the first signal.
	seedInitialPeriods(innerSess, []int64{2000, 1900, 1800})

	go func() {
		// Initial batch update — wakes the wait-for-initial branch.
		emitTestUpdate(innerSess)
		// After first request_more_data lands, drop the cursor below the
		// threshold and emit again so the loop exits cleanly.
		time.Sleep(20 * time.Millisecond)
		seedInitialPeriods(innerSess, []int64{2000, 1900, 1800, 500})
		emitTestUpdate(innerSess)
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err := cs.FetchUntil(ctx, 1000,
		WithBatchSize(100),
		WithThrottle(1*time.Millisecond),
		WithResponseTimeout(500*time.Millisecond))
	require.NoError(t, err)
}

// TestChartSession_FetchRange_GuardsAndFiltering exercises the convenience
// wrapper's input validation and ascending-sort filter logic.
func TestChartSession_FetchRange_GuardsAndFiltering(t *testing.T) {
	bridge := &fakeBridge{}
	client := &Client{}
	innerSess := newTestChartSession(client, bridge)

	cs := &ChartSession{
		client:  client,
		session: innerSess,
		options: &ChartSessionOptions{Timeframe: "5"},
		symbol:  "OANDA:XAUUSD",
	}

	// Guard 1: missing SetMarket leaves cs.symbol blank ⇒ should error.
	bare := &ChartSession{client: client, session: innerSess, options: &ChartSessionOptions{}}
	_, err := bare.FetchRange(context.Background(), 1000, 2000)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "SetMarket must be called")

	// Guard 2: fromTs >= toTs.
	_, err = cs.FetchRange(context.Background(), 2000, 2000)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "must be strictly less than")

	// Filter logic: seed bars across the boundary, run a fast fetch.
	seedInitialPeriods(innerSess, []int64{500, 1000, 1500, 1800, 2000, 2200})
	go func() {
		emitTestUpdate(innerSess) // initial
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	out, err := cs.FetchRange(ctx, 1000, 2000,
		WithBatchSize(10),
		WithThrottle(1*time.Millisecond),
		WithResponseTimeout(100*time.Millisecond))
	require.NoError(t, err)

	// Want: only [1000, 1500, 1800, 2000], ascending order.
	require.Len(t, out, 4)
	assert.Equal(t, int64(1000), out[0].Time)
	assert.Equal(t, int64(1500), out[1].Time)
	assert.Equal(t, int64(1800), out[2].Time)
	assert.Equal(t, int64(2000), out[3].Time)
}

// TestFetchOptions_DefaultsAndOverrides exercises the functional options
// surface — important because chained callers rely on the defaults staying
// stable.
func TestFetchOptions_DefaultsAndOverrides(t *testing.T) {
	cfg := defaultFetchConfig()
	assert.Equal(t, 1000, cfg.batchSize)
	assert.Equal(t, 150*time.Millisecond, cfg.throttle)
	assert.Equal(t, 2*time.Second, cfg.responseTimeout)
	assert.Equal(t, 1000, cfg.maxBatches)

	WithBatchSize(500)(&cfg)
	WithThrottle(50 * time.Millisecond)(&cfg)
	WithResponseTimeout(1 * time.Second)(&cfg)
	WithMaxBatches(10)(&cfg)
	assert.Equal(t, 500, cfg.batchSize)
	assert.Equal(t, 50*time.Millisecond, cfg.throttle)
	assert.Equal(t, 1*time.Second, cfg.responseTimeout)
	assert.Equal(t, 10, cfg.maxBatches)

	// Negative / zero inputs are no-ops to keep the API forgiving.
	WithBatchSize(-5)(&cfg)
	WithMaxBatches(0)(&cfg)
	assert.Equal(t, 500, cfg.batchSize, "negative batch size must be ignored")
	assert.Equal(t, 10, cfg.maxBatches, "zero max batches must be ignored")
}
