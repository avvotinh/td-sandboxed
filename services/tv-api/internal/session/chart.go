package session

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"sort"
	"strings"
	"sync"

	"github.com/avvotinh/tv-api/internal/protocol"
)

// ChartSession represents a historical chart data session.
type ChartSession struct {
	id                string
	sessionID         string // For logging purposes
	client            ClientBridge
	periods           map[int64]*Period
	infos             *MarketInfo
	currentSeries     int
	symbolID          string
	symbol            string // Store symbol for reconnection
	timeframe         string // Store timeframe for reconnection
	referenceToTs     int64  // FakeReplay anchor; 0 means no reference (live)
	referenceRange    int    // FakeReplay initial range; 0 means use default 300
	// Replay-mode fields (premium ReplayMode, story 12.7.0e). All zero/nil
	// when running in live or FakeReplay mode. Snapshotted under cs.mu so
	// the reconnection path can restore the full replay handshake without
	// racing fresh SetMarket calls.
	replay            *ReplaySession // nil unless SetMarketWithReplay was called
	replayStartFromTs int64          // last replay_reset target (Unix seconds)
	replayAdjustment  string         // adjustment param for replay_add_series + resolve_symbol
	replaySessionStr  string         // session param (regular/extended) for resolve_symbol
	replayCurrency    string         // currency param for resolve_symbol
	replayInitRange   int            // create_series range to issue post-replay_reset
	studyListeners    map[string][]func(interface{})
	callbacks         map[string][]func(...interface{})
	mu                sync.RWMutex
	state             SessionState
	reconnectionState *ReconnectionState
	ctx               context.Context
	logger            *slog.Logger
}

// Period represents an OHLCV candle.
type Period struct {
	Time   int64   `json:"time"`
	Open   float64 `json:"open"`
	Close  float64 `json:"close"`
	High   float64 `json:"max"`
	Low    float64 `json:"min"`
	Volume float64 `json:"volume"`
}

// MarketInfo contains market symbol information.
type MarketInfo struct {
	Symbol      string
	Description string
	Exchange    string
	Type        string
	Currency    string
	Timezone    string
	Session     string
	PriceScale  int
	MinMove     int
	HasIntraday bool
	HasDaily    bool
	HasWeekly   bool
}

// NewChartSession creates a new chart session.
func NewChartSession(client ClientBridge) *ChartSession {
	sessionID := GenSessionID("cs")

	cs := &ChartSession{
		id:             sessionID,
		client:         client,
		periods:        make(map[int64]*Period),
		currentSeries:  0,
		studyListeners: make(map[string][]func(interface{})),
		callbacks:      make(map[string][]func(...interface{})),
	}

	// Send chart_create_session packet
	cs.createSession()

	return cs
}

// ID returns the session ID.
func (cs *ChartSession) ID() string {
	return cs.id
}

// Type returns the session type.
func (cs *ChartSession) Type() string {
	return "chart"
}

// OnData handles incoming packet data for this session.
func (cs *ChartSession) OnData(packet protocol.Packet) error {
	switch packet.Type {
	case "symbol_resolved":
		return cs.handleSymbolResolved(packet)
	case "timescale_update":
		return cs.handleTimescaleUpdate(packet)
	case "du":
		return cs.handleDataUpdate(packet)
	case "symbol_error":
		return cs.handleSymbolError(packet)
	case "series_error":
		return cs.handleSeriesError(packet)
	case "critical_error":
		return cs.handleCriticalError(packet)
	default:
		return nil
	}
}

// OnDataBatch handles a batch of packets from the same WebSocket message.
// This is crucial for detecting "du" + "timescale_update" sequences which
// indicate a confirmed closed candle in TradingView protocol.
func (cs *ChartSession) OnDataBatch(packets []protocol.Packet) error {
	// Track if we have "timescale_update" or "du" in this batch
	hasTimescaleUpdate := false
	hasDataUpdate := false

	// DEBUG: Log packet types in this batch
	packetTypes := make([]string, len(packets))
	for i, p := range packets {
		packetTypes[i] = p.Type
	}

	// Log incoming batch for debugging
	if cs.logger != nil {
		cs.logger.Debug("processing packet batch",
			slog.String("session_id", cs.id),
			slog.Any("packet_types", packetTypes),
			slog.Int("count", len(packets)))
	}

	// Process all packets first to update internal state
	for _, packet := range packets {
		switch packet.Type {
		case "symbol_resolved":
			cs.handleSymbolResolved(packet)
		case "du":
			hasDataUpdate = true
			cs.handleDataUpdate(packet)
		case "timescale_update":
			hasTimescaleUpdate = true
			cs.handleTimescaleUpdate(packet)
		case "symbol_error":
			cs.handleSymbolError(packet)
		case "series_error":
			cs.handleSeriesError(packet)
		case "critical_error":
			cs.handleCriticalError(packet)
		}
	}

	// Emit logic:
	// 1. If we have "timescale_update" with "du" → CONFIRMED CLOSED candle
	// 2. If we have "timescale_update" without "du" → Initial data load
	// 3. If we have "du" without "timescale_update" → Open candle, NO emit
	if hasTimescaleUpdate {
		periods := cs.GetPeriods()
		if cs.logger != nil {
			cs.logger.Debug("emitting update event",
				slog.String("session_id", cs.id),
				slog.Int("periods_count", len(periods)),
				slog.Bool("has_du", hasDataUpdate))
		}
		cs.emit("update", periods)
	} else if hasDataUpdate {
		// No emit for open candles
		if cs.logger != nil {
			cs.logger.Debug("received du without timescale_update - skipping emit (open candle)",
				slog.String("session_id", cs.id))
		}
	}

	return nil
}

// Close closes the session.
func (cs *ChartSession) Close() error {
	return cs.Delete()
}

// createSession sends the chart_create_session packet.
func (cs *ChartSession) createSession() error {
	packet := protocol.Packet{
		Type: "chart_create_session",
		Data: []interface{}{cs.id, ""},
	}
	return cs.client.Send(packet)
}

// ResolveSymbol sends the resolve_symbol packet.
func (cs *ChartSession) ResolveSymbol(symbol string, adjustment string, sessionStr string, currency string) error {
	cs.mu.Lock()
	cs.symbolID = fmt.Sprintf("symbol_%d", cs.currentSeries)
	cs.mu.Unlock()

	symbolJSON := map[string]interface{}{
		"symbol":     symbol,
		"adjustment": adjustment,
	}
	if sessionStr != "" {
		symbolJSON["session"] = sessionStr
	}
	if currency != "" {
		symbolJSON["currency"] = currency
	}

	jsonStr, err := json.Marshal(symbolJSON)
	if err != nil {
		return err
	}

	packet := protocol.Packet{
		Type: "resolve_symbol",
		Data: []interface{}{cs.id, cs.symbolID, "=" + string(jsonStr)},
	}
	return cs.client.Send(packet)
}

// CreateSeries sends the create_series packet.
func (cs *ChartSession) CreateSeries(timeframe string, rangeCount int) error {
	cs.mu.Lock()
	cs.currentSeries++
	seriesID := fmt.Sprintf("s%d", cs.currentSeries)
	cs.mu.Unlock()

	packet := protocol.Packet{
		Type: "create_series",
		Data: []interface{}{cs.id, "$prices", seriesID, cs.symbolID, timeframe, rangeCount, ""},
	}
	return cs.client.Send(packet)
}

// ModifySeries sends the modify_series packet to change timeframe.
func (cs *ChartSession) ModifySeries(seriesID string, timeframe string, rangeCount int) error {
	packet := protocol.Packet{
		Type: "modify_series",
		Data: []interface{}{cs.id, seriesID, "$prices", cs.symbolID, timeframe, rangeCount, ""},
	}
	return cs.client.Send(packet)
}

// ResolveSymbolWithReplay sends resolve_symbol with the chartInit envelope
// the upstream JS port uses for premium ReplayMode (session.js:378-394):
//
//	{ "replay": "<rs_id>", "symbol": { "symbol": "...", "adjustment": "..." } }
//
// Pre-condition: a ReplaySession with id == replaySessionID must already be
// registered with the manager and a replay_create_session packet sent —
// otherwise the server reports "unknown replay session". The
// `currentSeries` counter is *not* bumped here, mirroring the non-replay
// ResolveSymbol — the bump happens once in CreateSeries so both modes
// keep the same monotonic counter behaviour and the symbolID stays
// bound to the most recent resolve.
func (cs *ChartSession) ResolveSymbolWithReplay(symbol, adjustment, sessionStr, currency, replaySessionID string) error {
	cs.mu.Lock()
	cs.symbolID = fmt.Sprintf("symbol_%d", cs.currentSeries)
	cs.mu.Unlock()

	symbolJSON := map[string]interface{}{
		"symbol":     symbol,
		"adjustment": adjustment,
	}
	if sessionStr != "" {
		symbolJSON["session"] = sessionStr
	}
	if currency != "" {
		symbolJSON["currency"] = currency
	}

	chartInit := map[string]interface{}{
		"replay": replaySessionID,
		"symbol": symbolJSON,
	}

	jsonStr, err := json.Marshal(chartInit)
	if err != nil {
		return fmt.Errorf("ResolveSymbolWithReplay: marshal chartInit: %w", err)
	}

	packet := protocol.Packet{
		Type: "resolve_symbol",
		Data: []interface{}{cs.id, cs.symbolID, "=" + string(jsonStr)},
	}
	return cs.client.Send(packet)
}

// AttachReplay binds a ReplaySession to this chart so the lifecycle helpers
// (Delete, reconnect) can drive replay_create_session / replay_delete_session
// without the public-API package mediating each call. The replay session
// must already be registered with the same Client.Manager.
func (cs *ChartSession) AttachReplay(rs *ReplaySession) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.replay = rs
}

// Replay returns the attached ReplaySession, or nil when this chart is
// running in live / FakeReplay mode. Public so the tradingview package
// can wire OnReplayLoaded / Step / Start / Stop / replay_point listeners.
func (cs *ChartSession) Replay() *ReplaySession {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	return cs.replay
}

// SetMarketWithReplay performs the full premium ReplayMode handshake in
// the order JS session.js:341-397 dictates. Mutates cs state so a
// subsequent reconnect can restore the cursor.
//
//	1. replay_create_session   (control plane: anchor)
//	2. replay_add_series       (server-side cursor track)
//	3. replay_reset(startFrom) (server-side cursor seek)
//	4. resolve_symbol          (chart side, complex chartInit with replay field)
//	5. create_series           (chart side, plain integer range)
//
// The caller must have wired a ReplaySession via AttachReplay first; we
// don't auto-create here because the ReplaySession also needs to be
// registered with the client's session manager so its rs_* packets route
// correctly — that registration lives in the public API package.
//
// startFromTs is interpreted in Unix seconds. rangeBars is the initial
// create_series range; pass a positive number (the server interprets the
// integer as the number of *most recent* bars relative to the cursor).
func (cs *ChartSession) SetMarketWithReplay(symbol, timeframe string, rangeBars int, startFromTs int64, adjustment, sessionStr, currency string) error {
	if startFromTs <= 0 {
		return fmt.Errorf("SetMarketWithReplay: startFromTs must be > 0 (got %d)", startFromTs)
	}
	if rangeBars <= 0 {
		rangeBars = 300
	}
	if adjustment == "" {
		adjustment = "splits"
	}

	cs.mu.RLock()
	rs := cs.replay
	cs.mu.RUnlock()
	if rs == nil {
		return fmt.Errorf("SetMarketWithReplay: AttachReplay must be called before SetMarketWithReplay")
	}

	cs.SetSubscriptionForReplay(symbol, timeframe, startFromTs, adjustment, sessionStr, currency, rangeBars)

	if err := rs.Create(); err != nil {
		return fmt.Errorf("SetMarketWithReplay: replay_create_session: %w", err)
	}

	symbolJSON, err := BuildSymbolJSON(symbol, adjustment, sessionStr, currency)
	if err != nil {
		return fmt.Errorf("SetMarketWithReplay: build symbol JSON: %w", err)
	}
	if err := rs.AddSeries(symbolJSON, timeframe); err != nil {
		return fmt.Errorf("SetMarketWithReplay: replay_add_series: %w", err)
	}
	if err := rs.Reset(startFromTs); err != nil {
		return fmt.Errorf("SetMarketWithReplay: replay_reset: %w", err)
	}

	if err := cs.ResolveSymbolWithReplay(symbol, adjustment, sessionStr, currency, rs.ID()); err != nil {
		return fmt.Errorf("SetMarketWithReplay: resolve_symbol: %w", err)
	}

	if err := cs.CreateSeries(timeframe, rangeBars); err != nil {
		return fmt.Errorf("SetMarketWithReplay: create_series: %w", err)
	}

	return nil
}

// SetSubscriptionForReplay caches the parameters needed to redo the full
// replay handshake on reconnection. Mirrors SetSubscriptionWithReference
// but for the replay path. Clears FakeReplay state to make the modes
// mutually exclusive (the JS port treats them the same way: setMarket
// resets #periods and either #replayMode or the bar_count anchor).
func (cs *ChartSession) SetSubscriptionForReplay(symbol, timeframe string, startFromTs int64, adjustment, sessionStr, currency string, rangeBars int) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.symbol = symbol
	cs.timeframe = timeframe
	cs.referenceToTs = 0
	cs.referenceRange = 0
	cs.replayStartFromTs = startFromTs
	cs.replayAdjustment = adjustment
	cs.replaySessionStr = sessionStr
	cs.replayCurrency = currency
	cs.replayInitRange = rangeBars
}

// CreateSeriesWithReference sends create_series with the FakeReplay anchor
// encoding from JS session.js:310:
//
//	calcRange = ["bar_count", reference, range]
//
// When toTs > 0, the server walks backward from that timestamp returning the
// most recent rangeCount bars at-or-before it. A negative rangeCount asks the
// server for that many older bars from the reference. When toTs == 0, the
// payload falls back to a plain integer range (matches CreateSeries).
//
// Free-tier TradingView accounts can issue this packet without an auth token
// because no replay_create_session is involved (only premium ReplayMode needs
// that). See examples/FakeReplayMode.js for the upstream pattern.
func (cs *ChartSession) CreateSeriesWithReference(timeframe string, rangeCount int, toTs int64) error {
	cs.mu.Lock()
	cs.currentSeries++
	seriesID := fmt.Sprintf("s%d", cs.currentSeries)
	cs.mu.Unlock()

	var rangeData interface{}
	if toTs > 0 {
		rangeData = []interface{}{"bar_count", toTs, rangeCount}
	} else {
		rangeData = rangeCount
	}

	packet := protocol.Packet{
		Type: "create_series",
		Data: []interface{}{cs.id, "$prices", seriesID, cs.symbolID, timeframe, rangeData, ""},
	}
	return cs.client.Send(packet)
}

// RequestMoreData sends the request_more_data packet.
func (cs *ChartSession) RequestMoreData(seriesID string, count int) error {
	packet := protocol.Packet{
		Type: "request_more_data",
		Data: []interface{}{cs.id, seriesID, count},
	}
	return cs.client.Send(packet)
}

// SwitchTimezone sends the switch_timezone packet.
func (cs *ChartSession) SwitchTimezone(timezone string) error {
	packet := protocol.Packet{
		Type: "switch_timezone",
		Data: []interface{}{cs.id, timezone},
	}
	return cs.client.Send(packet)
}

// Delete deletes the session. Mirrors JS session.js:546-552: when a replay
// handshake was performed (replayStartFromTs > 0) the rs_* session is
// torn down first so the server releases the cursor slot before the
// chart_delete_session removes the chart series. The gate on
// replayStartFromTs avoids emitting a delete for an rs ID the server
// never saw — replay sessions are attached eagerly at construction time
// so AttachReplay alone is not a sufficient signal that a control-plane
// session exists server-side.
func (cs *ChartSession) Delete() error {
	cs.mu.RLock()
	rs := cs.replay
	replayActive := cs.replayStartFromTs > 0
	cs.mu.RUnlock()

	if rs != nil && replayActive {
		if err := rs.Delete(); err != nil {
			return fmt.Errorf("chart Delete: replay_delete_session: %w", err)
		}
	}

	packet := protocol.Packet{
		Type: "chart_delete_session",
		Data: []interface{}{cs.id},
	}
	return cs.client.Send(packet)
}

// GetPeriods returns all periods sorted by time descending.
func (cs *ChartSession) GetPeriods() []*Period {
	cs.mu.RLock()
	defer cs.mu.RUnlock()

	periods := make([]*Period, 0, len(cs.periods))
	for _, p := range cs.periods {
		periods = append(periods, p)
	}

	sort.Slice(periods, func(i, j int) bool {
		return periods[i].Time > periods[j].Time
	})

	return periods
}

// GetMarketInfo returns the market information.
func (cs *ChartSession) GetMarketInfo() *MarketInfo {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	return cs.infos
}

// MinPeriodTime returns the smallest period timestamp seen by the session.
// Returns 0 when no periods have been received yet. Used by FetchUntil to
// detect when the walk-backward batch has reached the requested floor.
func (cs *ChartSession) MinPeriodTime() int64 {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	var min int64
	for ts := range cs.periods {
		if min == 0 || ts < min {
			min = ts
		}
	}
	return min
}

// EmitForTest exposes the internal emit() helper for unit tests that need
// to drive callbacks directly without going through OnDataBatch. It is a
// test-only seam — production code paths must not call this.
func (cs *ChartSession) EmitForTest(event string, args ...interface{}) {
	cs.emit(event, args...)
}

// SetPeriodsForTest replaces the periods map atomically; used in tests that
// need a known cursor without round-tripping packets.
func (cs *ChartSession) SetPeriodsForTest(periods map[int64]*Period) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.periods = periods
}

// SubscribeUpdate returns a buffered signal channel that receives a value
// each time the session emits an "update" event (one batch of confirmed bars).
// The buffer prevents slow consumers from blocking the WebSocket reader; once
// full, additional signals are dropped — callers should treat the channel as
// "at least one update arrived since last drain". The returned release fn is
// retained for future symmetry with deregistration; today it is a no-op
// because On() is append-only and the listener closure is GC'd with the
// session.
func (cs *ChartSession) SubscribeUpdate(buf int) (<-chan struct{}, func()) {
	if buf <= 0 {
		buf = 1
	}
	ch := make(chan struct{}, buf)
	cs.On("update", func(_ ...interface{}) {
		select {
		case ch <- struct{}{}:
		default:
		}
	})
	return ch, func() {}
}

// On registers an event callback.
func (cs *ChartSession) On(event string, callback func(...interface{})) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.callbacks[event] = append(cs.callbacks[event], callback)
}

// emit triggers event callbacks. The slice is *deep-copied* under the
// lock before iteration: a bare `cs.callbacks[event]` only copies the
// slice header, leaving the iterator on the same backing array that a
// concurrent On() may grow via append. The reconnect path emits "error"
// from background goroutines while the WebSocket reader registers more
// callbacks, so the race is reachable in production even if test
// suites drive emit synchronously.
func (cs *ChartSession) emit(event string, args ...interface{}) {
	cs.mu.RLock()
	callbacks := append([]func(...interface{}){}, cs.callbacks[event]...)
	cs.mu.RUnlock()

	for _, callback := range callbacks {
		callback(args...)
	}
}

// handleSymbolResolved processes symbol_resolved packets.
func (cs *ChartSession) handleSymbolResolved(packet protocol.Packet) error {
	if len(packet.Data) < 2 {
		return fmt.Errorf("invalid symbol_resolved packet")
	}

	// Extract market info from packet data
	if dataMap, ok := packet.Data[1].(map[string]interface{}); ok {
		cs.mu.Lock()
		cs.infos = &MarketInfo{
			Symbol:      getString(dataMap, "symbol"),
			Description: getString(dataMap, "description"),
			Exchange:    getString(dataMap, "exchange"),
			Type:        getString(dataMap, "type"),
			Currency:    getString(dataMap, "currency"),
			Timezone:    getString(dataMap, "timezone"),
			Session:     getString(dataMap, "session"),
			PriceScale:  getInt(dataMap, "pricescale"),
			MinMove:     getInt(dataMap, "minmov"),
			HasIntraday: getBool(dataMap, "has_intraday"),
			HasDaily:    getBool(dataMap, "has_daily"),
			HasWeekly:   getBool(dataMap, "has_weekly_and_monthly"),
		}
		cs.mu.Unlock()

		cs.emit("symbol_loaded", cs.infos)
	}

	return nil
}

// handleTimescaleUpdate processes timescale_update packets.
// This indicates that a candle has been CLOSED/CONFIRMED when combined with "du" in the same message batch.
func (cs *ChartSession) handleTimescaleUpdate(packet protocol.Packet) error {
	if len(packet.Data) < 2 {
		return nil
	}

	// Extract period data (usually empty {} in timescale_update)
	if dataMap, ok := packet.Data[1].(map[string]interface{}); ok {
		cs.parsePeriodData(dataMap)
		// NOTE: DO NOT emit here! Emission is handled by OnDataBatch
		// when both "du" + "timescale_update" are detected in the same batch
	}

	return nil
}

// handleDataUpdate processes du (data update) packets.
// This is a REAL-TIME update. The candle is only confirmed closed when
// "du" + "timescale_update" appear together in the same message batch.
func (cs *ChartSession) handleDataUpdate(packet protocol.Packet) error {
	if len(packet.Data) < 2 {
		return nil
	}

	// Extract period data and store it
	if dataMap, ok := packet.Data[1].(map[string]interface{}); ok {
		cs.parsePeriodData(dataMap)
		// NOTE: DO NOT emit here! Emission is handled by OnDataBatch
		// when both "du" + "timescale_update" are detected in the same batch
		// This ensures we only emit for CONFIRMED CLOSED candles
	}

	return nil
}

// parsePeriodData extracts OHLCV data from packet data.
func (cs *ChartSession) parsePeriodData(dataMap map[string]interface{}) {
	// Loop through all keys to find series data
	// TradingView uses different keys:
	// - "$prices" for initial/historical data (timescale_update)
	// - "sds_1", "sds_2", etc. for real-time updates (du)
	for key, value := range dataMap {
		// Check if this key contains series data
		if key == "$prices" || strings.HasPrefix(key, "sds_") {
			if pricesData, ok := value.(map[string]interface{}); ok {
				if s, ok := pricesData["s"].([]interface{}); ok && len(s) > 0 {
					// TradingView sends data in format: {s: [{i: index, v: [time, open, high, low, close, volume]}, ...]}
					cs.extractPeriodsFromArray(s)
				}
			}
		}
	}
}

// extractPeriodsFromArray extracts periods from TradingView's data structure.
// TradingView format: [{i: index, v: [time, open, high, low, close, volume]}, ...]
func (cs *ChartSession) extractPeriodsFromArray(data []interface{}) {
	cs.mu.Lock()
	defer cs.mu.Unlock()

	for _, item := range data {
		itemMap, ok := item.(map[string]interface{})
		if !ok {
			continue
		}

		// Get the 'v' array: [time, open, high, low, close, volume]
		vArray, ok := itemMap["v"].([]interface{})
		if !ok || len(vArray) < 6 {
			continue
		}

		// Extract values from array
		timestamp := getFloat64FromInterface(vArray[0])
		open := getFloat64FromInterface(vArray[1])
		high := getFloat64FromInterface(vArray[2])
		low := getFloat64FromInterface(vArray[3])
		close := getFloat64FromInterface(vArray[4])
		volume := getFloat64FromInterface(vArray[5])

		period := &Period{
			Time:   int64(timestamp),
			Open:   open,
			High:   high,
			Low:    low,
			Close:  close,
			Volume: volume,
		}
		cs.periods[int64(timestamp)] = period
	}
}

// handleSymbolError processes symbol_error packets.
func (cs *ChartSession) handleSymbolError(packet protocol.Packet) error {
	var errorMsg string
	if len(packet.Data) > 1 {
		errorMsg = fmt.Sprintf("%v", packet.Data[1])
	} else {
		errorMsg = fmt.Sprintf("%v", packet.Data)
	}

	cs.mu.RLock()
	symbol := cs.symbolID
	logger := cs.logger
	ctx := cs.ctx
	cs.mu.RUnlock()

	var err error
	if symbol != "" {
		err = fmt.Errorf("invalid symbol '%s': %s", symbol, errorMsg)
	} else {
		err = fmt.Errorf("symbol error: %s", errorMsg)
	}

	cs.emit("error", err)

	// Trigger reconnection if context and logger are available
	if ctx != nil && logger != nil {
		cs.setState(SessionStateReconnecting)
		go func() {
			if reconnectErr := cs.reconnectWithBackoff(ctx, logger); reconnectErr != nil {
				logger.Error("reconnection failed",
					slog.String("session_id", cs.sessionID),
					slog.String("error", reconnectErr.Error()))
			}
		}()
	}

	return nil
}

// handleSeriesError processes series_error packets.
func (cs *ChartSession) handleSeriesError(packet protocol.Packet) error {
	var errorMsg string
	if len(packet.Data) > 1 {
		errorMsg = fmt.Sprintf("%v", packet.Data[1])
	} else {
		errorMsg = fmt.Sprintf("%v", packet.Data)
	}

	err := fmt.Errorf("series error (timeframe may be invalid): %s", errorMsg)
	cs.emit("error", err)

	// Trigger reconnection if context and logger are available
	cs.mu.RLock()
	logger := cs.logger
	ctx := cs.ctx
	cs.mu.RUnlock()

	if ctx != nil && logger != nil {
		cs.setState(SessionStateReconnecting)
		go func() {
			if reconnectErr := cs.reconnectWithBackoff(ctx, logger); reconnectErr != nil {
				logger.Error("reconnection failed",
					slog.String("session_id", cs.sessionID),
					slog.String("error", reconnectErr.Error()))
			}
		}()
	}

	return nil
}

// handleCriticalError processes critical_error packets.
func (cs *ChartSession) handleCriticalError(packet protocol.Packet) error {
	var errorMsg string
	if len(packet.Data) > 0 {
		errorMsg = fmt.Sprintf("%v", packet.Data[0])
	} else {
		errorMsg = "unknown critical error"
	}

	err := fmt.Errorf("critical error: %s", errorMsg)
	cs.emit("error", err)

	// Trigger reconnection if context and logger are available
	cs.mu.RLock()
	logger := cs.logger
	ctx := cs.ctx
	cs.mu.RUnlock()

	if ctx != nil && logger != nil {
		cs.setState(SessionStateReconnecting)
		go func() {
			if reconnectErr := cs.reconnectWithBackoff(ctx, logger); reconnectErr != nil {
				logger.Error("reconnection failed",
					slog.String("session_id", cs.sessionID),
					slog.String("error", reconnectErr.Error()))
			}
		}()
	}

	return nil
}

// Helper functions
func getString(m map[string]interface{}, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getInt(m map[string]interface{}, key string) int {
	if v, ok := m[key].(float64); ok {
		return int(v)
	}
	return 0
}

func getBool(m map[string]interface{}, key string) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}

func getFloatArray(m map[string]interface{}, key string) []float64 {
	if arr, ok := m[key].([]interface{}); ok {
		result := make([]float64, len(arr))
		for i, v := range arr {
			if f, ok := v.(float64); ok {
				result[i] = f
			}
		}
		return result
	}
	return []float64{}
}

func getAtIndex(arr []float64, idx int) float64 {
	if idx < len(arr) {
		return arr[idx]
	}
	return 0
}

// getFloat64FromInterface safely extracts a float64 from an interface{} value
func getFloat64FromInterface(v interface{}) float64 {
	switch val := v.(type) {
	case float64:
		return val
	case float32:
		return float64(val)
	case int:
		return float64(val)
	case int64:
		return float64(val)
	case int32:
		return float64(val)
	default:
		return 0
	}
}

// GetState returns the current session state.
func (cs *ChartSession) GetState() string {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	return string(cs.state)
}

// setState updates the session state.
func (cs *ChartSession) setState(state SessionState) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.state = state
}

// GetRetryCount returns the current retry count.
func (cs *ChartSession) GetRetryCount() int {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	if cs.reconnectionState != nil {
		return cs.reconnectionState.RetryCount
	}
	return 0
}

// connect establishes connection for this session (used by reconnection logic).
// Three modes are restored here, in priority order:
//
//  1. Replay mode (replayStartFromTs > 0): re-issue the full premium
//     ReplayMode handshake — replay_create_session → replay_add_series →
//     replay_reset → resolve_symbol(complex) → create_series. The chart
//     periods buffer is preserved across the flap because the map is
//     keyed by timestamp and bars dedupe on rejoin.
//  2. FakeReplay mode (referenceToTs > 0): restore the bar_count anchor
//     so a long backtest fetch survives WebSocket flaps.
//  3. Live mode: plain ResolveSymbol + CreateSeries.
func (cs *ChartSession) connect(ctx context.Context) error {
	// Create the session
	if err := cs.createSession(); err != nil {
		return fmt.Errorf("failed to create session: %w", err)
	}

	cs.mu.RLock()
	symbol := cs.symbol
	timeframe := cs.timeframe
	toTs := cs.referenceToTs
	refRange := cs.referenceRange
	replay := cs.replay
	replayStartFrom := cs.replayStartFromTs
	replayAdjustment := cs.replayAdjustment
	replaySessionStr := cs.replaySessionStr
	replayCurrency := cs.replayCurrency
	replayRange := cs.replayInitRange
	cs.mu.RUnlock()

	if symbol == "" {
		return nil
	}

	// Replay mode — full handshake.
	if replay != nil && replayStartFrom > 0 {
		if err := replay.Create(); err != nil {
			return fmt.Errorf("replay reconnect: replay_create_session: %w", err)
		}
		symbolJSON, err := BuildSymbolJSON(symbol, replayAdjustment, replaySessionStr, replayCurrency)
		if err != nil {
			return fmt.Errorf("replay reconnect: build symbol JSON: %w", err)
		}
		if err := replay.AddSeries(symbolJSON, timeframe); err != nil {
			return fmt.Errorf("replay reconnect: replay_add_series: %w", err)
		}
		if err := replay.Reset(replayStartFrom); err != nil {
			return fmt.Errorf("replay reconnect: replay_reset: %w", err)
		}
		if err := cs.ResolveSymbolWithReplay(symbol, replayAdjustment, replaySessionStr, replayCurrency, replay.ID()); err != nil {
			return fmt.Errorf("replay reconnect: resolve_symbol: %w", err)
		}
		if replayRange <= 0 {
			replayRange = 300
		}
		if err := cs.CreateSeries(timeframe, replayRange); err != nil {
			return fmt.Errorf("replay reconnect: create_series: %w", err)
		}
		return nil
	}

	// Resolve symbol if we have it stored (FakeReplay or live).
	if err := cs.ResolveSymbol(symbol, "splits", "", ""); err != nil {
		return fmt.Errorf("failed to resolve symbol: %w", err)
	}

	// Create series if we have timeframe stored.
	if timeframe == "" {
		return nil
	}
	if toTs > 0 {
		if refRange == 0 {
			refRange = -300
		}
		if err := cs.CreateSeriesWithReference(timeframe, refRange, toTs); err != nil {
			return fmt.Errorf("failed to create series with reference: %w", err)
		}
		return nil
	}
	if err := cs.CreateSeries(timeframe, 300); err != nil {
		return fmt.Errorf("failed to create series: %w", err)
	}
	return nil
}

// ForceDisconnect simulates a disconnection for testing purposes.
func (cs *ChartSession) ForceDisconnect() error {
	cs.setState(SessionStateReconnecting)
	return fmt.Errorf("simulated disconnection")
}

// SetContext sets the context and logger for the session (for reconnection support).
func (cs *ChartSession) SetContext(ctx context.Context, logger *slog.Logger) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.ctx = ctx
	cs.logger = logger
	cs.sessionID = cs.id
}

// SetSubscription stores the symbol and timeframe for reconnection.
func (cs *ChartSession) SetSubscription(symbol, timeframe string) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.symbol = symbol
	cs.timeframe = timeframe
	cs.referenceToTs = 0
	cs.referenceRange = 0
}

// SetSubscriptionWithReference is the FakeReplay variant of SetSubscription.
// The reconnection path (see connect) uses the stored toTs/range to restore
// the bar_count anchor instead of falling back to a live range=300 query.
// referenceRange is reset to 0 here (so connect picks the default -300
// initial batch) — callers who need a different initial range should set it
// directly on the session, not via this helper.
func (cs *ChartSession) SetSubscriptionWithReference(symbol, timeframe string, toTs int64) {
	cs.mu.Lock()
	defer cs.mu.Unlock()
	cs.symbol = symbol
	cs.timeframe = timeframe
	cs.referenceToTs = toTs
	cs.referenceRange = 0
}
