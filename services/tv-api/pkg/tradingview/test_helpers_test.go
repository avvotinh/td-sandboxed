package tradingview

import (
	"sync"

	"github.com/avvotinh/tv-api/internal/protocol"
	"github.com/avvotinh/tv-api/internal/session"
)

// fakeBridge is the pkg/tradingview-side counterpart to the internal-package
// fakeClientBridge: it satisfies session.ClientBridge so we can stand up a
// real session.ChartSession without a live WebSocket. Recording packets is
// optional — the wrapper smoke tests focus on behaviour, not protocol.
type fakeBridge struct {
	mu      sync.Mutex
	packets []protocol.Packet
}

func (f *fakeBridge) Send(packet protocol.Packet) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.packets = append(f.packets, packet)
	return nil
}

// newTestChartSession constructs a session.ChartSession backed by the given
// fake bridge. The bridge must outlive the returned session.
func newTestChartSession(_ *Client, bridge *fakeBridge) *session.ChartSession {
	return session.NewChartSession(bridge)
}

// seedInitialPeriods replaces the session's period map with a deterministic
// set keyed by Time, used to skip the create_series → timescale_update
// dance in unit tests.
func seedInitialPeriods(s *session.ChartSession, timestamps []int64) {
	periods := make(map[int64]*session.Period, len(timestamps))
	for _, ts := range timestamps {
		periods[ts] = &session.Period{Time: ts}
	}
	s.SetPeriodsForTest(periods)
}

// emitTestUpdate fires the "update" event on a session as if a batch of
// confirmed bars arrived from the server. SubscribeUpdate listeners receive
// a signal on their channels.
func emitTestUpdate(s *session.ChartSession) {
	s.EmitForTest("update")
}
