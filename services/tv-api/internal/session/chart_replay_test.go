package session

import (
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
