package session

import (
	"encoding/json"
	"strings"
	"sync"
	"testing"

	"github.com/avvotinh/tv-api/internal/protocol"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// fakeClientBridge captures every Send call for protocol-shape assertions.
type fakeClientBridge struct {
	mu      sync.Mutex
	packets []protocol.Packet
	sendErr error
}

func (f *fakeClientBridge) Send(packet protocol.Packet) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.sendErr != nil {
		return f.sendErr
	}
	f.packets = append(f.packets, packet)
	return nil
}

func (f *fakeClientBridge) byType(typ string) []protocol.Packet {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]protocol.Packet, 0)
	for _, p := range f.packets {
		if p.Type == typ {
			out = append(out, p)
		}
	}
	return out
}

// TestCreateSeries_PlainRange verifies the existing payload shape is preserved.
func TestCreateSeries_PlainRange(t *testing.T) {
	bridge := &fakeClientBridge{}
	cs := NewChartSession(bridge)

	require.NoError(t, cs.ResolveSymbol("OANDA:XAUUSD", "splits", "", ""))
	require.NoError(t, cs.CreateSeries("5", 300))

	created := bridge.byType("create_series")
	require.Len(t, created, 1, "exactly one create_series packet expected")

	data := created[0].Data
	require.Len(t, data, 7)
	assert.Equal(t, "$prices", data[1])
	assert.Equal(t, "s1", data[2])
	assert.Equal(t, "5", data[4])
	assert.Equal(t, 300, data[5], "plain integer range when no reference")
	assert.Equal(t, "", data[6])
}

// TestCreateSeriesWithReference_BarCountTuple verifies the FakeReplay anchor encoding
// matches JS reference (TradingView-API/src/chart/session.js:310,396):
//
//	create_series payload Data[5] == ["bar_count", to_ts, range_count]
func TestCreateSeriesWithReference_BarCountTuple(t *testing.T) {
	bridge := &fakeClientBridge{}
	cs := NewChartSession(bridge)

	require.NoError(t, cs.ResolveSymbol("OANDA:XAUUSD", "splits", "", ""))

	const toTs int64 = 1700000000
	const rangeCount = -1000
	require.NoError(t, cs.CreateSeriesWithReference("5", rangeCount, toTs))

	created := bridge.byType("create_series")
	require.Len(t, created, 1)

	data := created[0].Data
	require.Len(t, data, 7)

	tuple, ok := data[5].([]interface{})
	require.True(t, ok, "Data[5] must be []interface{} bar_count tuple, got %T", data[5])
	require.Len(t, tuple, 3)
	assert.Equal(t, "bar_count", tuple[0])
	assert.Equal(t, toTs, tuple[1])
	assert.Equal(t, rangeCount, tuple[2])
}

// TestCreateSeriesWithReference_ZeroToTsFallsBackToPlain documents the contract:
// when toTs == 0, behaviour matches CreateSeries (plain integer range).
func TestCreateSeriesWithReference_ZeroToTsFallsBackToPlain(t *testing.T) {
	bridge := &fakeClientBridge{}
	cs := NewChartSession(bridge)

	require.NoError(t, cs.ResolveSymbol("OANDA:XAUUSD", "splits", "", ""))
	require.NoError(t, cs.CreateSeriesWithReference("5", 300, 0))

	created := bridge.byType("create_series")
	require.Len(t, created, 1)
	assert.Equal(t, 300, created[0].Data[5])
}

// TestCreateSeriesWithReference_SecondCallUsesModifySeries mirrors JS
// session.js:314 — `${seriesCreated ? 'modify' : 'create'}_series`.
func TestCreateSeriesWithReference_SecondCallUsesModifySeries(t *testing.T) {
	t.Skip("modify_series toggle is a future refinement; v1 always sends create_series")
}

// TestSetSubscriptionWithReference_RemembersToTsForReconnect ensures the
// reconnect path (chart.go:622) restores the FakeReplay anchor.
func TestSetSubscriptionWithReference_RemembersToTsForReconnect(t *testing.T) {
	bridge := &fakeClientBridge{}
	cs := NewChartSession(bridge)

	const toTs int64 = 1700000000
	cs.SetSubscriptionWithReference("OANDA:XAUUSD", "5", toTs)

	cs.mu.RLock()
	defer cs.mu.RUnlock()
	assert.Equal(t, "OANDA:XAUUSD", cs.symbol)
	assert.Equal(t, "5", cs.timeframe)
	assert.Equal(t, toTs, cs.referenceToTs)
}

// TestMinPeriodTime exercises the helper FetchUntil relies on to detect when
// the walk-backward walk has crossed the requested floor. Empty map must
// return the 0 sentinel; populated maps must return the smallest timestamp.
func TestMinPeriodTime(t *testing.T) {
	cases := []struct {
		name string
		bars []int64
		want int64
	}{
		{name: "empty", bars: nil, want: 0},
		{name: "single", bars: []int64{1700000000}, want: 1700000000},
		{name: "multiple_descending", bars: []int64{1900, 1800, 1700, 1600}, want: 1600},
		{name: "multiple_unordered", bars: []int64{1750, 1600, 1900, 1700}, want: 1600},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			cs := NewChartSession(&fakeClientBridge{})
			cs.mu.Lock()
			for _, ts := range tc.bars {
				cs.periods[ts] = &Period{Time: ts}
			}
			cs.mu.Unlock()

			assert.Equal(t, tc.want, cs.MinPeriodTime())
		})
	}
}

// TestSetSubscriptionWithReference_ResetsRangeAfterPlainSubscription pins down
// the regression go-reviewer flagged: a plain SetSubscription must not leak
// referenceRange state into a subsequent FakeReplay subscription on the
// same session.
func TestSetSubscriptionWithReference_ResetsRangeAfterPlainSubscription(t *testing.T) {
	cs := NewChartSession(&fakeClientBridge{})

	// Simulate a stale referenceRange from an earlier (hypothetical) caller
	// that pre-populated the field.
	cs.mu.Lock()
	cs.referenceRange = -5000
	cs.mu.Unlock()

	cs.SetSubscriptionWithReference("OANDA:XAUUSD", "5", 1700000000)

	cs.mu.RLock()
	defer cs.mu.RUnlock()
	assert.Zero(t, cs.referenceRange, "stale referenceRange must be cleared")
	assert.Equal(t, int64(1700000000), cs.referenceToTs)
}

// TestRequestMoreData_NegativeBatchSize covers the FakeReplay walk-backward call.
// Existing RequestMoreData accepts negative count (JS session.js:412 fetchMore(-N)).
func TestRequestMoreData_NegativeBatchSize(t *testing.T) {
	bridge := &fakeClientBridge{}
	cs := NewChartSession(bridge)

	require.NoError(t, cs.RequestMoreData("s1", -1000))

	pkts := bridge.byType("request_more_data")
	require.Len(t, pkts, 1)
	assert.Equal(t, "s1", pkts[0].Data[1])
	assert.Equal(t, -1000, pkts[0].Data[2])
}

// ----------------------------------------------------------------------
// Premium ReplayMode tests (story 12.7.0e)
// ----------------------------------------------------------------------

// chartReplayFixture builds a chart session paired with a replay session,
// both bound to the same fakeClientBridge so packet order across the two
// can be asserted.
func chartReplayFixture(t *testing.T) (*fakeClientBridge, *ChartSession) {
	t.Helper()
	bridge := &fakeClientBridge{}
	cs := NewChartSession(bridge)
	rs := NewReplaySession(bridge)
	cs.AttachReplay(rs)
	return bridge, cs
}

// TestSetMarketWithReplay_FullPacketOrder pins the wire-order JS upstream
// emits in setMarket when options.replay is set (session.js:341-397):
//
//	1. chart_create_session   (NewChartSession constructor)
//	2. replay_create_session
//	3. replay_add_series
//	4. replay_reset
//	5. resolve_symbol         (with chartInit.replay = rsID)
//	6. create_series          (plain integer range, NO bar_count tuple)
func TestSetMarketWithReplay_FullPacketOrder(t *testing.T) {
	bridge, cs := chartReplayFixture(t)

	require.NoError(t, cs.SetMarketWithReplay(
		"OANDA:XAUUSD", "1D", 300, 1_700_000_000, "splits", "", "",
	))

	bridge.mu.Lock()
	defer bridge.mu.Unlock()

	types := make([]string, len(bridge.packets))
	for i, p := range bridge.packets {
		types[i] = p.Type
	}

	expected := []string{
		"chart_create_session",
		"replay_create_session",
		"replay_add_series",
		"replay_reset",
		"resolve_symbol",
		"create_series",
	}
	require.Equal(t, expected, types,
		"replay handshake must emit packets in JS upstream order")
}

// TestSetMarketWithReplay_ResolveSymbolContainsReplayField verifies the
// resolve_symbol payload's chartInit envelope carries the `replay` and
// `symbol` keys (JS session.js:381-385). Without this the server runs
// the chart series in live mode and ignores the replay cursor.
func TestSetMarketWithReplay_ResolveSymbolContainsReplayField(t *testing.T) {
	bridge, cs := chartReplayFixture(t)

	require.NoError(t, cs.SetMarketWithReplay(
		"OANDA:XAUUSD", "1D", 300, 1_700_000_000, "splits", "regular", "USD",
	))

	pkts := bridge.byType("resolve_symbol")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 3)

	payload, ok := pkts[0].Data[2].(string)
	require.True(t, ok)
	require.True(t, strings.HasPrefix(payload, "="))

	var chartInit map[string]interface{}
	require.NoError(t, json.Unmarshal([]byte(strings.TrimPrefix(payload, "=")), &chartInit))

	rsID, ok := chartInit["replay"].(string)
	require.True(t, ok, "chartInit.replay must be a string")
	assert.True(t, strings.HasPrefix(rsID, "rs_"), "chartInit.replay must reference an rs_ ID")

	symBlob, ok := chartInit["symbol"].(map[string]interface{})
	require.True(t, ok, "chartInit.symbol must be an object")
	assert.Equal(t, "OANDA:XAUUSD", symBlob["symbol"])
	assert.Equal(t, "splits", symBlob["adjustment"])
	assert.Equal(t, "regular", symBlob["session"])
	assert.Equal(t, "USD", symBlob["currency"])
}

// TestSetMarketWithReplay_CreateSeriesUsesPlainInteger documents that
// premium ReplayMode does NOT use the bar_count tuple — the server uses
// the replay cursor as the anchor, so create_series's range field is a
// plain int (JS session.js:396 → setSeries(timeframe, range) with no
// reference). Regression guard against confusing the two anchored modes.
func TestSetMarketWithReplay_CreateSeriesUsesPlainInteger(t *testing.T) {
	bridge, cs := chartReplayFixture(t)

	require.NoError(t, cs.SetMarketWithReplay(
		"OANDA:XAUUSD", "1D", 500, 1_700_000_000, "splits", "", "",
	))

	pkts := bridge.byType("create_series")
	require.Len(t, pkts, 1)
	require.Len(t, pkts[0].Data, 7)
	assert.Equal(t, "1D", pkts[0].Data[4])
	assert.Equal(t, 500, pkts[0].Data[5], "Replay create_series must use plain integer, not bar_count tuple")
}

// TestSetMarketWithReplay_RequiresAttachedReplay rejects calls that skip
// AttachReplay — otherwise SetMarketWithReplay would silently drop the
// control packets and the chart would resolve to live mode.
func TestSetMarketWithReplay_RequiresAttachedReplay(t *testing.T) {
	bridge := &fakeClientBridge{}
	cs := NewChartSession(bridge)

	err := cs.SetMarketWithReplay("OANDA:XAUUSD", "1D", 300, 1_700_000_000, "splits", "", "")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "AttachReplay")
}

// TestSetMarketWithReplay_RejectsNonPositiveStartFrom guards the
// pre-condition that the replay cursor needs an actual timestamp.
func TestSetMarketWithReplay_RejectsNonPositiveStartFrom(t *testing.T) {
	_, cs := chartReplayFixture(t)
	err := cs.SetMarketWithReplay("OANDA:XAUUSD", "1D", 300, 0, "splits", "", "")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "startFromTs")
}

// TestSetMarketWithReplay_StoresReconnectState exercises the cache that
// the reconnection path depends on (replayStartFromTs, replayAdjustment,
// etc.). Without the cache, a WebSocket flap would re-resolve to live
// mode and the running fetch would silently change semantics.
func TestSetMarketWithReplay_StoresReconnectState(t *testing.T) {
	_, cs := chartReplayFixture(t)

	require.NoError(t, cs.SetMarketWithReplay(
		"OANDA:XAUUSD", "1D", 250, 1_700_000_000, "splits", "regular", "USD",
	))

	cs.mu.RLock()
	defer cs.mu.RUnlock()
	assert.Equal(t, "OANDA:XAUUSD", cs.symbol)
	assert.Equal(t, "1D", cs.timeframe)
	assert.Equal(t, int64(1_700_000_000), cs.replayStartFromTs)
	assert.Equal(t, "splits", cs.replayAdjustment)
	assert.Equal(t, "regular", cs.replaySessionStr)
	assert.Equal(t, "USD", cs.replayCurrency)
	assert.Equal(t, 250, cs.replayInitRange)

	// Replay mode must clear FakeReplay state — the two anchors are
	// mutually exclusive at the protocol level (replay cursor vs.
	// bar_count tuple).
	assert.Zero(t, cs.referenceToTs)
	assert.Zero(t, cs.referenceRange)
}

// TestChartSession_Delete_WithActiveReplay_SendsBothPackets verifies the
// JS contract: replay_delete_session emitted before chart_delete_session.
// Order matters because the server frees the cursor slot before the
// chart series is torn down — reverse order would leave the cursor
// dangling for a tick.
func TestChartSession_Delete_WithActiveReplay_SendsBothPackets(t *testing.T) {
	bridge, cs := chartReplayFixture(t)

	require.NoError(t, cs.SetMarketWithReplay(
		"OANDA:XAUUSD", "1D", 300, 1_700_000_000, "splits", "", "",
	))

	bridge.mu.Lock()
	startLen := len(bridge.packets)
	bridge.mu.Unlock()

	require.NoError(t, cs.Delete())

	bridge.mu.Lock()
	defer bridge.mu.Unlock()
	tail := bridge.packets[startLen:]
	require.Len(t, tail, 2)
	assert.Equal(t, "replay_delete_session", tail[0].Type)
	assert.Equal(t, "chart_delete_session", tail[1].Type)
}

// TestChartSession_Delete_WithoutReplayHandshake_OnlyChart documents the
// gate on replayStartFromTs > 0: a chart with an attached-but-never-used
// replay session must NOT emit replay_delete_session. The server has no
// rs_* registration to clean up.
func TestChartSession_Delete_WithoutReplayHandshake_OnlyChart(t *testing.T) {
	bridge, cs := chartReplayFixture(t)

	require.NoError(t, cs.Delete())

	pkts := bridge.byType("replay_delete_session")
	assert.Len(t, pkts, 0, "replay_delete_session must not fire without a prior handshake")

	chartDeletes := bridge.byType("chart_delete_session")
	require.Len(t, chartDeletes, 1)
}

// TestChartSession_Reconnect_RestoresReplayHandshake exercises the
// connect() path's replay branch: cache the SetMarketWithReplay state,
// invoke connect() (simulating a reconnection), assert the full
// handshake re-runs in order. The chart_create_session counter goes up
// because a new session is created on rejoin (matches client.connect()).
func TestChartSession_Reconnect_RestoresReplayHandshake(t *testing.T) {
	bridge, cs := chartReplayFixture(t)

	require.NoError(t, cs.SetMarketWithReplay(
		"OANDA:XAUUSD", "1D", 300, 1_700_000_000, "splits", "", "",
	))

	bridge.mu.Lock()
	startLen := len(bridge.packets)
	bridge.mu.Unlock()

	require.NoError(t, cs.connect(t.Context()))

	bridge.mu.Lock()
	defer bridge.mu.Unlock()
	tail := bridge.packets[startLen:]
	types := make([]string, len(tail))
	for i, p := range tail {
		types[i] = p.Type
	}
	expected := []string{
		"chart_create_session",
		"replay_create_session",
		"replay_add_series",
		"replay_reset",
		"resolve_symbol",
		"create_series",
	}
	assert.Equal(t, expected, types)
}

// TestReplay_AddSeries_UsesAttachedSymbolJSON pins that the symbol JSON
// the chart session wires through SetMarketWithReplay matches the JSON
// emitted by replay_add_series — they must agree, otherwise the server
// would resolve two different symbol envelopes.
func TestReplay_AddSeries_UsesAttachedSymbolJSON(t *testing.T) {
	bridge, cs := chartReplayFixture(t)

	require.NoError(t, cs.SetMarketWithReplay(
		"BINANCE:BTCUSDT", "60", 300, 1_700_000_000, "splits", "", "",
	))

	addPkts := bridge.byType("replay_add_series")
	resolvePkts := bridge.byType("resolve_symbol")
	require.Len(t, addPkts, 1)
	require.Len(t, resolvePkts, 1)

	addPayload := strings.TrimPrefix(addPkts[0].Data[2].(string), "=")
	var addJSON map[string]interface{}
	require.NoError(t, json.Unmarshal([]byte(addPayload), &addJSON))
	assert.Equal(t, "BINANCE:BTCUSDT", addJSON["symbol"])

	resolvePayload := strings.TrimPrefix(resolvePkts[0].Data[2].(string), "=")
	var chartInit map[string]interface{}
	require.NoError(t, json.Unmarshal([]byte(resolvePayload), &chartInit))
	symBlob := chartInit["symbol"].(map[string]interface{})
	assert.Equal(t, "BINANCE:BTCUSDT", symBlob["symbol"])
}
