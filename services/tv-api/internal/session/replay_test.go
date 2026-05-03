package session

import (
	"encoding/json"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/avvotinh/tv-api/internal/protocol"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// recvAck waits up to 100ms for the ack channel to close, returning true
// when it does. Keeps tests fast even when the ack never arrives.
func recvAck(t *testing.T, ch <-chan struct{}) bool {
	t.Helper()
	select {
	case <-ch:
		return true
	case <-time.After(100 * time.Millisecond):
		return false
	}
}

func TestReplaySession_IDPrefixAndType(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})
	assert.True(t, strings.HasPrefix(rs.ID(), "rs_"), "session ID must use rs_ prefix")
	assert.Equal(t, "replay", rs.Type())
}

// TestReplay_Create_PacketShape mirrors JS session.js:361.
//
//	send('replay_create_session', [replaySessionID])
func TestReplay_Create_PacketShape(t *testing.T) {
	bridge := &fakeClientBridge{}
	rs := NewReplaySession(bridge)

	require.NoError(t, rs.Create())

	pkts := bridge.byType("replay_create_session")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 1)
	assert.Equal(t, rs.ID(), pkts[0].Data[0])
}

// TestReplay_AddSeries_PacketShape mirrors JS session.js:364-369.
//
//	send('replay_add_series', [rsID, 'req_replay_addseries', '=' + JSON, timeframe])
func TestReplay_AddSeries_PacketShape(t *testing.T) {
	bridge := &fakeClientBridge{}
	rs := NewReplaySession(bridge)

	symJSON, err := BuildSymbolJSON("OANDA:XAUUSD", "splits", "", "")
	require.NoError(t, err)

	require.NoError(t, rs.AddSeries(symJSON, "1D"))

	pkts := bridge.byType("replay_add_series")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 4)
	assert.Equal(t, rs.ID(), pkts[0].Data[0])
	assert.Equal(t, "req_replay_addseries", pkts[0].Data[1])

	payload, ok := pkts[0].Data[2].(string)
	require.True(t, ok, "Data[2] must be string")
	require.True(t, strings.HasPrefix(payload, "="), "Data[2] must start with '=' marker")

	var decoded map[string]interface{}
	require.NoError(t, json.Unmarshal([]byte(strings.TrimPrefix(payload, "=")), &decoded))
	assert.Equal(t, "OANDA:XAUUSD", decoded["symbol"])
	assert.Equal(t, "splits", decoded["adjustment"])

	assert.Equal(t, "1D", pkts[0].Data[3])
}

// TestReplay_Reset_PacketShape mirrors JS session.js:371-375.
//
//	send('replay_reset', [rsID, 'req_replay_reset', timestamp])
func TestReplay_Reset_PacketShape(t *testing.T) {
	bridge := &fakeClientBridge{}
	rs := NewReplaySession(bridge)

	const ts int64 = 1_700_000_000
	require.NoError(t, rs.Reset(ts))

	pkts := bridge.byType("replay_reset")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 3)
	assert.Equal(t, rs.ID(), pkts[0].Data[0])
	assert.Equal(t, "req_replay_reset", pkts[0].Data[1])
	assert.Equal(t, ts, pkts[0].Data[2])
}

// TestReplay_Delete_PacketShape mirrors JS delete() in session.js:547.
func TestReplay_Delete_PacketShape(t *testing.T) {
	bridge := &fakeClientBridge{}
	rs := NewReplaySession(bridge)

	require.NoError(t, rs.Delete())

	pkts := bridge.byType("replay_delete_session")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 1)
	assert.Equal(t, rs.ID(), pkts[0].Data[0])
}

// TestReplay_Step_AckRoundTrip exercises the reqID correlation logic:
// Step → packet sent with generated reqID → inject replay_ok with that
// same reqID → ack channel must close.
func TestReplay_Step_AckRoundTrip(t *testing.T) {
	bridge := &fakeClientBridge{}
	rs := NewReplaySession(bridge)

	ack, err := rs.Step(5)
	require.NoError(t, err)
	require.NotNil(t, ack)

	pkts := bridge.byType("replay_step")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 3)
	assert.Equal(t, rs.ID(), pkts[0].Data[0])
	reqID, ok := pkts[0].Data[1].(string)
	require.True(t, ok)
	require.True(t, strings.HasPrefix(reqID, "rsq_step_"), "expected rsq_step_ reqID, got %q", reqID)
	assert.Equal(t, 5, pkts[0].Data[2])

	// Inject replay_ok with the SAME reqID — channel must close.
	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_ok",
		Data: []interface{}{rs.ID(), reqID},
	}))
	assert.True(t, recvAck(t, ack), "ack channel should close after matching replay_ok")
}

// TestReplay_Step_AckMismatchDoesNotClose pins the regression that a
// replay_ok with a DIFFERENT reqID must not close the channel.
func TestReplay_Step_AckMismatchDoesNotClose(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})

	ack, err := rs.Step(1)
	require.NoError(t, err)

	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_ok",
		Data: []interface{}{rs.ID(), "rsq_step_unknown"},
	}))

	assert.False(t, recvAck(t, ack), "ack must remain open for mismatched reqID")
}

func TestReplay_Start_AckRoundTrip(t *testing.T) {
	bridge := &fakeClientBridge{}
	rs := NewReplaySession(bridge)

	ack, err := rs.Start(1000)
	require.NoError(t, err)

	pkts := bridge.byType("replay_start")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 3)
	reqID := pkts[0].Data[1].(string)
	require.True(t, strings.HasPrefix(reqID, "rsq_start_"))
	assert.Equal(t, 1000, pkts[0].Data[2])

	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_ok",
		Data: []interface{}{rs.ID(), reqID},
	}))
	assert.True(t, recvAck(t, ack))
}

func TestReplay_Stop_AckRoundTrip(t *testing.T) {
	bridge := &fakeClientBridge{}
	rs := NewReplaySession(bridge)

	ack, err := rs.Stop()
	require.NoError(t, err)

	pkts := bridge.byType("replay_stop")
	require.Len(t, pkts, 1)
	// Stop carries no extra payload — JS session.js:464.
	require.Len(t, pkts[0].Data, 2)
	reqID := pkts[0].Data[1].(string)
	require.True(t, strings.HasPrefix(reqID, "rsq_stop_"))

	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_ok",
		Data: []interface{}{rs.ID(), reqID},
	}))
	assert.True(t, recvAck(t, ack))
}

// TestReplay_OnData_InstanceID_EmitsLoaded covers the upstream contract
// in session.js:265-267 — replay_instance_id triggers replayLoaded.
func TestReplay_OnData_InstanceID_EmitsLoaded(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})

	var got string
	var mu sync.Mutex
	rs.On(ReplayEventLoaded, func(args ...interface{}) {
		mu.Lock()
		defer mu.Unlock()
		if len(args) > 0 {
			got, _ = args[0].(string)
		}
	})

	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_instance_id",
		Data: []interface{}{rs.ID(), "instance_abc"},
	}))

	mu.Lock()
	defer mu.Unlock()
	assert.Equal(t, "instance_abc", got)
}

func TestReplay_OnData_DataEnd_EmitsEnd(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})

	called := false
	rs.On(ReplayEventEnd, func(_ ...interface{}) {
		called = true
	})

	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_data_end",
		Data: []interface{}{rs.ID()},
	}))
	assert.True(t, called)
}

func TestReplay_OnData_Point_EmitsPoint(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})

	var got int64
	rs.On(ReplayEventPoint, func(args ...interface{}) {
		if len(args) > 0 {
			if v, ok := args[0].(int64); ok {
				got = v
			}
		}
	})

	// JSON decode of WebSocket payload yields float64 by default —
	// exercise that path because production traffic looks like that.
	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_point",
		Data: []interface{}{rs.ID(), float64(42)},
	}))
	assert.Equal(t, int64(42), got)
}

func TestReplay_OnData_Resolutions_EmitsResolution(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})

	var gotTF string
	var gotIdx int64
	rs.On(ReplayEventResolution, func(args ...interface{}) {
		if len(args) > 0 {
			gotTF, _ = args[0].(string)
		}
		if len(args) > 1 {
			if v, ok := args[1].(int64); ok {
				gotIdx = v
			}
		}
	})

	require.NoError(t, rs.OnData(protocol.Packet{
		Type: "replay_resolutions",
		Data: []interface{}{rs.ID(), "1D", float64(7)},
	}))
	assert.Equal(t, "1D", gotTF)
	assert.Equal(t, int64(7), gotIdx)
}

// TestReplay_Close_DrainsPendingAcks documents the drain semantics:
// Close on a session with in-flight Step/Start/Stop calls closes their
// channels so callers waiting via select don't leak.
func TestReplay_Close_DrainsPendingAcks(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})

	ack, err := rs.Step(1)
	require.NoError(t, err)

	require.NoError(t, rs.Close())
	assert.True(t, recvAck(t, ack), "Close must drain pending ack channels")
}

// TestReplay_OnData_UnknownPacketIsHarmless guards against the
// "default: return nil" arm regressing into a panic on unrecognised
// packet types — important because the WebSocket can send anything.
func TestReplay_OnData_UnknownPacketIsHarmless(t *testing.T) {
	rs := NewReplaySession(&fakeClientBridge{})
	assert.NoError(t, rs.OnData(protocol.Packet{
		Type: "qsd",
		Data: []interface{}{"some", "unrelated", "data"},
	}))
}

// TestBuildSymbolJSON_BareForm pins the canonical key set when no
// session / currency override is requested.
func TestBuildSymbolJSON_BareForm(t *testing.T) {
	out, err := BuildSymbolJSON("OANDA:XAUUSD", "splits", "", "")
	require.NoError(t, err)

	var decoded map[string]interface{}
	require.NoError(t, json.Unmarshal([]byte(out), &decoded))
	assert.Equal(t, "OANDA:XAUUSD", decoded["symbol"])
	assert.Equal(t, "splits", decoded["adjustment"])
	_, hasSession := decoded["session"]
	_, hasCurrency := decoded["currency"]
	assert.False(t, hasSession, "no session key when sessionStr empty")
	assert.False(t, hasCurrency, "no currency key when currency empty")
}

func TestBuildSymbolJSON_WithSessionAndCurrency(t *testing.T) {
	out, err := BuildSymbolJSON("NASDAQ:AAPL", "dividends", "regular", "USD")
	require.NoError(t, err)

	var decoded map[string]interface{}
	require.NoError(t, json.Unmarshal([]byte(out), &decoded))
	assert.Equal(t, "regular", decoded["session"])
	assert.Equal(t, "USD", decoded["currency"])
}

// TestReplay_AckOnSendError_ReleasesPendingSlot covers the error path:
// when the bridge.Send fails, the pending ack slot must be released so
// a subsequent retry doesn't leak. Without the cleanup the map would
// pin the failed reqID forever.
func TestReplay_AckOnSendError_ReleasesPendingSlot(t *testing.T) {
	bridge := &fakeClientBridge{sendErr: assertErr("forced send error")}
	rs := NewReplaySession(bridge)

	_, err := rs.Step(1)
	require.Error(t, err)

	rs.mu.Lock()
	defer rs.mu.Unlock()
	assert.Empty(t, rs.pendingAcks, "pending ack must be cleared on send failure")
}

// assertErr is a tiny helper to build a sentinel error without pulling
// errors.New into every test stanza.
type assertErr string

func (e assertErr) Error() string { return string(e) }
