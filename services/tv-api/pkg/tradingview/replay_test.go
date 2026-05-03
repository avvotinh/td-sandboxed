package tradingview

import (
	"context"
	"log/slog"
	"testing"

	"github.com/avvotinh/tv-api/internal/session"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// newTestClient builds a Client without performing the WebSocket connect
// — sufficient for exercising the public ChartSession surface that does
// not actually require a live socket (Send queues internally; the loops
// only fire after Connect). t.Setenv keeps creds out of the repo.
func newTestClient(t *testing.T) *Client {
	t.Helper()
	t.Setenv("SESSION_ID", "fake-session-id")
	t.Setenv("SESSION_SIGN", "fake-session-sign")
	c, err := NewClient(&ClientConfig{Logger: slog.Default()})
	require.NoError(t, err)
	return c
}

// TestFetchHistoricalReplay_RejectsCallBeforeSetMarket pins the symbol-
// empty guard. Without it, FetchUntil would walk forever because the
// session has no resolved series.
func TestFetchHistoricalReplay_RejectsCallBeforeSetMarket(t *testing.T) {
	client := newTestClient(t)
	cs := client.NewChartSession()

	_, err := cs.FetchHistoricalReplay(context.Background(), 1, 2)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "SetMarket must be called")
}

// TestFetchHistoricalReplay_RejectsInvertedWindow guards against the
// off-by-one footgun. The internal walk-backward loop assumes fromTs is
// the floor; an inverted pair would short-circuit on the first compare
// and yield zero bars without explanation.
func TestFetchHistoricalReplay_RejectsInvertedWindow(t *testing.T) {
	client := newTestClient(t)
	cs := client.NewChartSession()

	require.NoError(t, cs.SetMarket("OANDA:XAUUSD", &ChartSessionOptions{
		Timeframe:       "1D",
		ReplayStartFrom: 2_000,
	}))

	_, err := cs.FetchHistoricalReplay(context.Background(), 3_000, 2_000)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "must be strictly less than")
}

// TestFetchHistoricalReplay_FilterTrimsToWindow pre-populates the
// underlying chart session with a mix of in-window and out-of-window
// bars, then drives FetchHistoricalReplay through the early-return path
// (MinPeriodTime <= fromTs immediately). Verifies the [fromTs, toTs]
// inclusive window-filter slices off bars on either end.
func TestFetchHistoricalReplay_FilterTrimsToWindow(t *testing.T) {
	client := newTestClient(t)
	cs := client.NewChartSession()

	require.NoError(t, cs.SetMarket("OANDA:XAUUSD", &ChartSessionOptions{
		Timeframe:       "1D",
		ReplayStartFrom: 5_000,
	}))

	// Inject bars: two below window, three inside, two above.
	cs.session.SetPeriodsForTest(map[int64]*session.Period{
		1_000: {Time: 1_000, Close: 1.0},
		1_500: {Time: 1_500, Close: 1.5},
		2_000: {Time: 2_000, Close: 2.0}, // boundary (inclusive lower)
		3_000: {Time: 3_000, Close: 3.0},
		4_000: {Time: 4_000, Close: 4.0}, // boundary (inclusive upper)
		4_500: {Time: 4_500, Close: 4.5},
		5_000: {Time: 5_000, Close: 5.0},
	})

	periods, err := cs.FetchHistoricalReplay(context.Background(), 2_000, 4_000)
	require.NoError(t, err)

	gotTimes := make([]int64, len(periods))
	for i, p := range periods {
		gotTimes[i] = p.Time
	}
	assert.Equal(t, []int64{2_000, 3_000, 4_000}, gotTimes,
		"filter must keep boundary timestamps and ascend by Time")
}

// TestFetchHistoricalReplay_EmptyWindowYieldsEmptySlice covers the case
// where every bar falls outside [fromTs, toTs]. The function must
// return (nil-or-empty, nil-error) — silent zero bars is the contract
// the caller will assert against (CLI surfaces it as "zero bars in […]").
func TestFetchHistoricalReplay_EmptyWindowYieldsEmptySlice(t *testing.T) {
	client := newTestClient(t)
	cs := client.NewChartSession()

	require.NoError(t, cs.SetMarket("OANDA:XAUUSD", &ChartSessionOptions{
		Timeframe:       "1D",
		ReplayStartFrom: 5_000,
	}))

	cs.session.SetPeriodsForTest(map[int64]*session.Period{
		100: {Time: 100, Close: 1},
		200: {Time: 200, Close: 2},
	})

	periods, err := cs.FetchHistoricalReplay(context.Background(), 1_000, 2_000)
	require.NoError(t, err)
	assert.Empty(t, periods)
}

// TestSetMarket_ReplayAndToMutex pins the early-return guard that
// disallows feeding both the FakeReplay and ReplayMode anchors at once
// — they would resolve to incompatible chart-init payloads on the wire.
func TestSetMarket_ReplayAndToMutex(t *testing.T) {
	client := newTestClient(t)
	cs := client.NewChartSession()

	err := cs.SetMarket("OANDA:XAUUSD", &ChartSessionOptions{
		Timeframe:       "1D",
		To:              2_000,
		ReplayStartFrom: 2_000,
	})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "mutually exclusive")
}

// TestNewChartSession_AttachesReplayEagerly documents the eager-attach
// invariant the OnReplayLoaded / Step / Start / Stop public API relies
// on — callers must be able to subscribe before SetMarket fires.
func TestNewChartSession_AttachesReplayEagerly(t *testing.T) {
	client := newTestClient(t)
	cs := client.NewChartSession()
	assert.NotNil(t, cs.session.Replay(), "NewChartSession must attach a ReplaySession")
}
