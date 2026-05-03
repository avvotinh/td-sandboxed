package session

import (
	"encoding/json"
	"errors"
	"fmt"
	"sync"

	"github.com/avvotinh/tv-api/internal/protocol"
)

// ReplaySession is the control-plane peer of ChartSession when running in
// premium ReplayMode. It owns its own rs_* session ID, handles the five
// replay-only packet types, and exposes the bidirectional walk primitives
// (Step / Start / Stop) that operate on a server-side replay cursor.
//
// Premium-only: TradingView free-tier accounts cannot create a replay
// session — the server silently drops replay_create_session packets when
// the auth token does not include the replay entitlement. Tests in this
// package run against a fakeClientBridge so coverage is independent of an
// actual subscription.
//
// Mirrors TradingView-API/src/chart/session.js:120-290 (replaySessionID,
// replayMode, replayOKCB).
type ReplaySession struct {
	id        string
	client    ClientBridge
	callbacks map[string][]func(...interface{})

	// pendingAcks correlates a request ID we generated for a Step / Start
	// / Stop call with the channel the caller is waiting on. Closed when
	// the matching replay_ok packet arrives. Mirrors JS replayOKCB.
	pendingAcks map[string]chan struct{}

	mu sync.Mutex
}

// Replay event names emitted by the session. Public so callers in
// pkg/tradingview can subscribe with the same constants.
const (
	ReplayEventLoaded     = "replay_loaded"
	ReplayEventPoint      = "replay_point"
	ReplayEventResolution = "replay_resolution"
	ReplayEventEnd        = "replay_end"
	ReplayEventError      = "replay_error"
)

// NewReplaySession allocates a ReplaySession. The session ID is generated
// here; callers must register the session with the client before sending
// any control packets so the manager can route inbound replay_* packets
// back to OnData. Sending replay_create_session is the caller's job
// (typically ChartSession.SetMarketWithReplay) so the order with respect
// to chart-session setup is explicit.
func NewReplaySession(client ClientBridge) *ReplaySession {
	return &ReplaySession{
		id:          GenSessionID("rs"),
		client:      client,
		callbacks:   make(map[string][]func(...interface{})),
		pendingAcks: make(map[string]chan struct{}),
	}
}

// ID returns the session identifier (rs_<hex>).
func (rs *ReplaySession) ID() string { return rs.id }

// Type identifies the session kind for the manager.
func (rs *ReplaySession) Type() string { return "replay" }

// Close releases pending ack channels but does NOT send replay_delete_session
// — that is the chart session's responsibility because the chart owns the
// rs ID lifecycle (matches JS session.js:546-552 where delete() emits both
// chart_delete_session and replay_delete_session in order).
func (rs *ReplaySession) Close() error {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	for reqID, ch := range rs.pendingAcks {
		close(ch)
		delete(rs.pendingAcks, reqID)
	}
	return nil
}

// OnData routes a single inbound packet. Replay sessions never receive
// batched packets the way ChartSession does — bars flow through the chart
// session, replay packets are control-plane and arrive individually — so
// implementing OnData alone is sufficient.
func (rs *ReplaySession) OnData(packet protocol.Packet) error {
	switch packet.Type {
	case "replay_ok":
		return rs.handleReplayOK(packet)
	case "replay_instance_id":
		return rs.handleReplayInstanceID(packet)
	case "replay_point":
		return rs.handleReplayPoint(packet)
	case "replay_resolutions":
		return rs.handleReplayResolution(packet)
	case "replay_data_end":
		rs.emit(ReplayEventEnd)
		return nil
	case "critical_error":
		return rs.handleCriticalError(packet)
	default:
		return nil
	}
}

func (rs *ReplaySession) handleReplayOK(packet protocol.Packet) error {
	if len(packet.Data) < 2 {
		return nil
	}
	reqID, ok := packet.Data[1].(string)
	if !ok {
		return nil
	}

	rs.mu.Lock()
	ch, exists := rs.pendingAcks[reqID]
	if exists {
		delete(rs.pendingAcks, reqID)
	}
	rs.mu.Unlock()

	if exists {
		close(ch)
	}
	return nil
}

func (rs *ReplaySession) handleReplayInstanceID(packet protocol.Packet) error {
	if len(packet.Data) < 2 {
		return nil
	}
	instanceID, _ := packet.Data[1].(string)
	rs.emit(ReplayEventLoaded, instanceID)
	return nil
}

func (rs *ReplaySession) handleReplayPoint(packet protocol.Packet) error {
	if len(packet.Data) < 2 {
		return nil
	}
	idx := getInt64FromInterface(packet.Data[1])
	rs.emit(ReplayEventPoint, idx)
	return nil
}

func (rs *ReplaySession) handleReplayResolution(packet protocol.Packet) error {
	if len(packet.Data) < 3 {
		return nil
	}
	tf, _ := packet.Data[1].(string)
	idx := getInt64FromInterface(packet.Data[2])
	rs.emit(ReplayEventResolution, tf, idx)
	return nil
}

func (rs *ReplaySession) handleCriticalError(packet protocol.Packet) error {
	msg := "replay critical error"
	if len(packet.Data) > 0 {
		msg = fmt.Sprintf("%v", packet.Data)
	}
	// errors.New rather than fmt.Errorf("%s", …) so callers can wrap
	// with %w cleanly; the latter idiom drops unwrap support without
	// any benefit when no wrapping is happening at this layer.
	rs.emit(ReplayEventError, errors.New(msg))
	return nil
}

// Create sends replay_create_session. Must be called after the session is
// registered with the client manager; the server will reject control
// packets that arrive before registration (the manager won't route the
// reply). Mirrors JS session.js:361.
func (rs *ReplaySession) Create() error {
	return rs.client.Send(protocol.Packet{
		Type: "replay_create_session",
		Data: []interface{}{rs.id},
	})
}

// AddSeries sends replay_add_series with a fixed reqID matching upstream
// (req_replay_addseries). The matching response is a replay_instance_id
// packet which OnData converts to a ReplayEventLoaded emission, so callers
// chain on OnLoaded rather than waiting on AddSeries directly.
//
// symbolJSON is the JSON-encoded `{"symbol": "...", "adjustment": "..."}`
// blob the chart session built — duplicating the encoding here would be a
// drift risk, so the caller passes it in pre-formatted.
func (rs *ReplaySession) AddSeries(symbolJSON, timeframe string) error {
	return rs.client.Send(protocol.Packet{
		Type: "replay_add_series",
		Data: []interface{}{
			rs.id,
			"req_replay_addseries",
			"=" + symbolJSON,
			timeframe,
		},
	})
}

// Reset moves the replay cursor to toTs (Unix seconds). Mirrors
// JS session.js:371 — fixed reqID, no ack wait (subsequent bars on the
// chart series are the observable signal that the reset took effect).
func (rs *ReplaySession) Reset(toTs int64) error {
	return rs.client.Send(protocol.Packet{
		Type: "replay_reset",
		Data: []interface{}{
			rs.id,
			"req_replay_reset",
			toTs,
		},
	})
}

// Step advances the replay cursor by `count` bars. The returned channel
// closes when the server emits a matching replay_ok packet — wait on it
// before issuing the next step to preserve causal ordering. Step does NOT
// time out internally; pair with a context-aware select if needed.
func (rs *ReplaySession) Step(count int) (<-chan struct{}, error) {
	return rs.sendCorrelated("rsq_step", "replay_step", []interface{}{count})
}

// Start asks the server to push a fresh bar every intervalMs ms. The
// returned channel closes once the server acks the start command. Pair
// with Stop / Step / OnReplayPoint to drive a tick-by-tick simulator.
func (rs *ReplaySession) Start(intervalMs int) (<-chan struct{}, error) {
	return rs.sendCorrelated("rsq_start", "replay_start", []interface{}{intervalMs})
}

// Stop halts the auto-stepping started by Start. Returns a channel that
// closes on the corresponding replay_ok ack.
func (rs *ReplaySession) Stop() (<-chan struct{}, error) {
	return rs.sendCorrelated("rsq_stop", "replay_stop", nil)
}

// Delete sends replay_delete_session and drains any pending Step / Start
// / Stop ack channels — once the server tears down the rs_* session no
// matching replay_ok will ever arrive, so callers select-ing on the ack
// channel must unblock or they leak. Idempotent at the wire level: the
// server treats a delete on an unknown ID as a no-op, so a deferred
// invocation is safe even after a Close() drain.
//
// Channel-close semantics: receivers see the channel close. They cannot
// distinguish "ack arrived" from "session deleted" on the same channel
// — pair the receive with ctx.Done() (or rely on Step's documented
// no-internal-timeout contract) when that distinction matters.
func (rs *ReplaySession) Delete() error {
	err := rs.client.Send(protocol.Packet{
		Type: "replay_delete_session",
		Data: []interface{}{rs.id},
	})

	rs.mu.Lock()
	for reqID, ch := range rs.pendingAcks {
		close(ch)
		delete(rs.pendingAcks, reqID)
	}
	rs.mu.Unlock()

	return err
}

// On registers an event callback. Same shape as ChartSession.On so the
// public API package can wire the two with a single helper.
func (rs *ReplaySession) On(event string, callback func(...interface{})) {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	rs.callbacks[event] = append(rs.callbacks[event], callback)
}

// emit fires every callback registered for `event`. Snapshot the slice
// under the lock then call outside it so callbacks that re-enter On()
// don't deadlock.
func (rs *ReplaySession) emit(event string, args ...interface{}) {
	rs.mu.Lock()
	cbs := append([]func(...interface{}){}, rs.callbacks[event]...)
	rs.mu.Unlock()
	for _, cb := range cbs {
		cb(args...)
	}
}

// sendCorrelated generates a unique reqID, registers a one-shot ack
// channel, and sends a control packet whose Data layout is
// [rs.id, reqID, ...extra]. The returned channel closes when a
// replay_ok packet with that reqID arrives.
func (rs *ReplaySession) sendCorrelated(reqIDPrefix, packetType string, extra []interface{}) (<-chan struct{}, error) {
	reqID := GenSessionID(reqIDPrefix)

	ackCh := make(chan struct{})

	rs.mu.Lock()
	rs.pendingAcks[reqID] = ackCh
	rs.mu.Unlock()

	data := make([]interface{}, 0, 2+len(extra))
	data = append(data, rs.id, reqID)
	data = append(data, extra...)

	if err := rs.client.Send(protocol.Packet{Type: packetType, Data: data}); err != nil {
		rs.mu.Lock()
		delete(rs.pendingAcks, reqID)
		rs.mu.Unlock()
		return nil, fmt.Errorf("replay %s: send: %w", packetType, err)
	}

	return ackCh, nil
}

// BuildSymbolJSON returns the canonical JSON payload AddSeries expects —
// the shape replay_add_series's symbolInit blob has carried since the
// upstream JS port. Exposed on package level so ChartSession can build
// it without duplicating the keys.
func BuildSymbolJSON(symbol, adjustment, sessionStr, currency string) (string, error) {
	payload := map[string]interface{}{
		"symbol":     symbol,
		"adjustment": adjustment,
	}
	if sessionStr != "" {
		payload["session"] = sessionStr
	}
	if currency != "" {
		payload["currency"] = currency
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("BuildSymbolJSON: %w", err)
	}
	return string(b), nil
}

// getInt64FromInterface coerces the numeric types the WebSocket JSON
// decoder might hand us into a single int64 representation. Mirrors the
// chart-session helper but isolated here so replay.go has no dependency
// on chart.go internals.
func getInt64FromInterface(v interface{}) int64 {
	switch n := v.(type) {
	case int64:
		return n
	case int:
		return int64(n)
	case int32:
		return int64(n)
	case float64:
		return int64(n)
	case float32:
		return int64(n)
	default:
		return 0
	}
}
