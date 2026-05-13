package tradingview

import (
	"context"
	"fmt"

	"github.com/avvotinh/tv-api/internal/session"
)

// OnReplayLoaded registers a callback fired when the server emits
// replay_instance_id (i.e., the rs_* session is ready to receive
// step/start/stop). The instanceID argument is the opaque server-side
// handle returned by replay_add_series; useful for diagnostics, not
// required for control flow.
func (cs *ChartSession) OnReplayLoaded(callback func(instanceID string)) {
	rs := cs.session.Replay()
	if rs == nil {
		return
	}
	rs.On(session.ReplayEventLoaded, func(args ...interface{}) {
		var id string
		if len(args) > 0 {
			id, _ = args[0].(string)
		}
		callback(id)
	})
}

// OnReplayPoint fires every time the replay cursor moves (replay_point
// packet). The argument is the cursor index — typically the bar index in
// the resolved series, monotonically increasing as the cursor advances.
func (cs *ChartSession) OnReplayPoint(callback func(index int64)) {
	rs := cs.session.Replay()
	if rs == nil {
		return
	}
	rs.On(session.ReplayEventPoint, func(args ...interface{}) {
		var idx int64
		if len(args) > 0 {
			if v, ok := args[0].(int64); ok {
				idx = v
			}
		}
		callback(idx)
	})
}

// OnReplayResolution fires when the server confirms a new resolution is
// available (replay_resolutions packet). Useful when adding multiple
// timeframes against the same replay session.
func (cs *ChartSession) OnReplayResolution(callback func(timeframe string, index int64)) {
	rs := cs.session.Replay()
	if rs == nil {
		return
	}
	rs.On(session.ReplayEventResolution, func(args ...interface{}) {
		var tf string
		var idx int64
		if len(args) > 0 {
			tf, _ = args[0].(string)
		}
		if len(args) > 1 {
			if v, ok := args[1].(int64); ok {
				idx = v
			}
		}
		callback(tf, idx)
	})
}

// OnReplayEnd fires once when the server emits replay_data_end — the
// cursor reached the end of available history. Subsequent step/start
// calls become no-ops at the wire level.
func (cs *ChartSession) OnReplayEnd(callback func()) {
	rs := cs.session.Replay()
	if rs == nil {
		return
	}
	rs.On(session.ReplayEventEnd, func(_ ...interface{}) {
		callback()
	})
}

// ReplayStep advances the replay cursor by `count` bars and returns a
// channel that closes when the server's matching replay_ok ack lands.
// Returns an error only when no replay session has been activated
// (i.e., SetMarket was called without ReplayStartFrom). The channel
// itself does not error out — couple with ctx.Done() at the call site
// when bounded waiting is needed.
func (cs *ChartSession) ReplayStep(count int) (<-chan struct{}, error) {
	rs := cs.session.Replay()
	if rs == nil {
		return nil, fmt.Errorf("ReplayStep: replay session not initialised — call SetMarket with ReplayStartFrom > 0 first")
	}
	return rs.Step(count)
}

// ReplayStart asks the server to push a fresh bar every intervalMs ms.
// Returned channel closes when the server acks the start. Pair with
// OnReplayPoint to drive a tick-by-tick simulator. Stop the auto-step
// with ReplayStop before deleting the chart session.
func (cs *ChartSession) ReplayStart(intervalMs int) (<-chan struct{}, error) {
	rs := cs.session.Replay()
	if rs == nil {
		return nil, fmt.Errorf("ReplayStart: replay session not initialised")
	}
	return rs.Start(intervalMs)
}

// ReplayStop halts the auto-stepping started by ReplayStart.
func (cs *ChartSession) ReplayStop() (<-chan struct{}, error) {
	rs := cs.session.Replay()
	if rs == nil {
		return nil, fmt.Errorf("ReplayStop: replay session not initialised")
	}
	return rs.Stop()
}

// FetchHistoricalReplay walks backward through history one batch at a
// time until the chart session's smallest period timestamp is at-or-
// before fromTs, then returns every bar in [fromTs, toTs] sorted
// ascending by Time. Premium ReplayMode equivalent of FetchRange.
//
// Pre-condition: SetMarket must have been called with
//
//	ChartSessionOptions{
//	    Timeframe: "1D" | "1W" | etc,
//	    ReplayStartFrom: toTs,
//	}
//
// before invoking FetchHistoricalReplay. Without the replay handshake
// the server treats request_more_data as a live tail and the walk
// never terminates.
//
// FetchHistoricalReplay does NOT use replay_step / replay_start — that
// API moves the cursor *forward* and is wrong for backfill. It calls
// request_more_data(-batchSize) on the underlying chart series, which
// works in replay mode because the chart series exists and is anchored
// at the replay cursor.
func (cs *ChartSession) FetchHistoricalReplay(ctx context.Context, fromTs, toTs int64, opts ...FetchOption) ([]*Period, error) {
	if cs.symbol == "" {
		return nil, fmt.Errorf("FetchHistoricalReplay: SetMarket must be called first")
	}
	if cs.session.Replay() == nil {
		return nil, fmt.Errorf("FetchHistoricalReplay: replay session not initialised — set ChartSessionOptions.ReplayStartFrom")
	}
	if fromTs >= toTs {
		return nil, fmt.Errorf("FetchHistoricalReplay: fromTs (%d) must be strictly less than toTs (%d)", fromTs, toTs)
	}

	if err := cs.FetchUntil(ctx, fromTs, opts...); err != nil {
		return nil, err
	}

	all := cs.Periods() // newest-first
	out := make([]*Period, 0, len(all))
	for i := len(all) - 1; i >= 0; i-- {
		p := all[i]
		if p.Time >= fromTs && p.Time <= toTs {
			out = append(out, p)
		}
	}
	return out, nil
}
