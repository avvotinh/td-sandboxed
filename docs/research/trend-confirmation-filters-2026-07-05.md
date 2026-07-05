# Research: Multi-Indicator Confirmation Filters for Trend-Following Entries (XAUUSD / FX, M5/M15)

**Date:** 2026-07-05
**Requested for:** Strategy redesign plan — Track 3 (confirmation filters), feeds Track 5.1 decision
**Status:** partial (gh CLI unauthenticated in this sandbox — GitHub code search done via WebSearch instead of `gh search`; flagged in Open Questions)

## Question

For `supertrend` and `donchian_breakout` (active trend-following strategies on XAUUSD/FX M5/M15), which confirmation filter — ADX gate, Supertrend/Donchian confluence, or session-VWAP bias — has the strongest evidence and lowest implementation cost to cut low-quality breakout/flip signals, without doing parameter sweeps (default, literature-backed parameters only)?

## TL;DR — Recommendation

Implement the **ADX gate first** (`ADX(14) >= 25`, project already has a Wilder-correct `src/indicators/adx.py` used by the regime classifier with the same threshold — zero new indicator code, ~10-line change per strategy). Implement **session-VWAP bias second** (`src/indicators/session_vwap.py` also already exists and is unused — same low cost), anchored to the FTMO broker-server midnight session for both XAUUSD and FX majors for v1 consistency. **Defer Supertrend↔Donchian confluence** — it is directionally the same underlying signal family (both ATR/HL-band trend detectors), so confluence mostly reduces trade count without adding an independent information source, and it structurally conflicts with `donchian_breakout.py`'s existing internal `Supertrend` instance (used for trailing, not entry-gating) — reusing it for entry-confluence needs a design decision, not just a wire-up.

## Existing project code

- `services/trading-engine/src/indicators/adx.py` — hand-rolled Wilder ADX (+DI/-DI/ADX), **already used** by the regime classifier (`src/regime/features.py:24,75`), **not used by any strategy's `generate_signal`**.
- `services/trading-engine/src/indicators/session_vwap.py` — session-anchored VWAP (configurable IANA tz, resets on `SessionFilterMixin.session_id`), **not used by any strategy**.
- `services/trading-engine/src/indicators/supertrend.py` — Supertrend indicator, used by `supertrend.py` (entry signal) and by `donchian_breakout.py` (`self._supertrend_trail`, **trailing only**, not entry confluence).
- `configs/firms/ftmo.yaml:108-113` — regime classifier already uses `adx_trend_min: 25.0`, `adx_strong_trend: 40.0`, `ema_slope_trend_threshold: 0.0005` to route strategies by `RegimeState` (`TRENDING_UP/DOWN` for supertrend/donchian_breakout, `RANGING` for mean_reversion). This is a **different gating mechanism** (pre-trade regime router, not per-bar signal filter) — an ADX entry filter inside the strategy would be a second, tighter gate on top of the regime router, not a duplicate.
- `services/trading-engine/src/strategies/base_strategy.py:200-201` — `generate_signal(self, bar: Bar) -> SignalType` is the single abstract hook both strategies implement; adding a filter is an `and`-condition inside this method plus registering one more indicator in `on_start`/`on_reset` — confirmed low integration cost by reading `donchian_breakout.py` (173 lines) and `supertrend.py` (196 lines), both well under the 800-line file ceiling.
- `services/trading-engine/src/strategies/mixins/session_filter_mixin.py` — DST-safe session/window predicates already used by `SessionVWAP`'s reset logic; no new session-boundary code needed for the VWAP filter.
- `docs/research/strategy-tactics-quant-review.md` (2026-05-05, prior research) — covers exit/trailing tactics (Chandelier/Supertrend trailing, scale-out), **not entry confirmation filters** — this research is complementary, not overlapping.

## NautilusTrader 1.x native indicators (verified from installed package, not training data)

Checked `services/trading-engine/.venv/Lib/site-packages/nautilus_trader/indicators/` directly (Context7 MCP not available in this environment — see Open Questions):

- **No native `ADX` class.** `nautilus_trader/indicators/trend.pyx:251` ships `DirectionalMovement` — smoothed +DM/-DM oscillators via a configurable `MovingAverageType` (default EMA), but it does **not** compute the DX→ADX final smoothing step. It is not a drop-in ADX. The project's hand-rolled `ADX` (Wilder DI + DX + ADX, `src/indicators/adx.py`) fills a genuine gap — correctly kept as custom code.
- **Native `VolumeWeightedAveragePrice` exists** (`nautilus_trader/indicators/volume.pyx:133`) but resets on `timestamp.day != self._day` using `pd.Timestamp(bar.ts_init, tz="UTC")` — i.e. it resets at **UTC midnight only**, not a configurable session/timezone boundary. This contradicts the docstring comment in `session_vwap.py:3-4` ("cumulates from the start of the stream and never resets") — the native indicator does reset daily, just not at a broker/session-relevant boundary. The project's `SessionVWAP` (configurable `tz`) is still the correct choice for FTMO's broker-server session or a specific FX/XAUUSD session anchor; the existing docstring should be corrected to "resets at UTC midnight, not at a configurable session boundary" in a future doc pass (flagged for doc-updater, not fixed here — out of scope for research).

## Options evaluated

### Filter A: Donchian breakout + ADX gate
- **Source:** Pattern documented across multiple independent sources — freqtrade community strategy `hlhb.py` (ADX>25 combined with RSI/EMA cross), Nikhil-Adithyan `Algorithmic-Trading-with-ADX-in-python` (ADX>25 threshold in pandas), FXNX and CrossTrade educational writeups on ADX as a strength filter.
- **License:** freqtrade-strategies repo is GPL-3.0 (pattern/threshold only should be ported, not literal code, given project ships proprietary). Nikhil-Adithyan repo: no explicit license file found in search — treat as reference-only, do not copy code.
- **Stars/activity:** freqtrade (main repo) is a large, actively maintained project (tens of thousands of stars); freqtrade-strategies is a community strategy dump, lower individual-file provenance — treat as pattern evidence, not a maintained dependency.
- **Fit:** Direct fit — same "gate a directional/crossover signal behind ADX>threshold" pattern the project needs for `donchian_breakout.py` and `supertrend.py`.
- **Pros:** Widely repeated default (20 as loose threshold, 25 as stricter, consistent across sources); project already computes ADX(14)/25.0 for regime routing — same indicator, same threshold, zero new code; cuts trades specifically in the chop regime where breakout strategies bleed.
- **Cons:** ADX is a lagging, smoothed indicator (Wilder period 14 needs ~2×14=28 bars to fully initialize) — on M5 this is lag of ~2.3 hours before a fresh trend is "confirmed," so early-trend entries get filtered out along with late-chop breakouts. Gold-specific caveat: XAUUSD's volatility clustering around news (NFP/FOMC/CPI) can spike ADX briefly without genuine sustained trend, producing gate false-positives around news windows — no source-specific gold backtest was found confirming or refuting this, it is inferred from ADX's general lag behavior plus the project's own prior research on gold's news-driven volatility (`strategy-tactics-quant-review.md` news-spike section).
- **Integration cost:** **Low.** Instantiate `ADX(period=14)` in `__init__`, register in `on_start`/`on_reset` (mirrors the two-line pattern already used for `_atr` and `_supertrend_trail` in both strategy files), add `if not self._adx.initialized or self._adx.value < 25.0: return SignalType.NONE` guard at the top of `generate_signal`.

### Filter B: Supertrend↔Donchian confluence
- **Source:** FMZ Quant community strategy ("Donchian Channel with SuperTrend and Volume Filter Entry System"), Medium/FMZQuant "Dual Donchian Channel Breakout Strategy," general "combine breakout with a trend/volume filter to reduce false-breakout risk" guidance repeated across TrendSpider/Tradeciety educational content.
- **License:** FMZ marketplace strategies are typically proprietary/unclear license; treat as directional evidence only, not a code source.
- **Stars/activity:** No single canonical high-star open-source repo found implementing exactly Supertrend+Donchian confluence as a paired filter (as opposed to Supertrend-as-trailing, which is common and already used in this codebase). Evidence here is weaker and more anecdotal than Filter A or C.
- **Fit:** Partial — most examples found combine Donchian **entry** with a trend indicator used for **exit/trailing** (which the project already does via `_supertrend_trail` in `donchian_breakout.py`), not as a second independent entry-confirmation vote. True dual-confirmation (require both a Donchian breakout AND a fresh/aligned Supertrend flip on the same bar) reduces trade count sharply because the two indicators are correlated (both HL/ATR-band trend detectors) — expect large signal-count reduction with uncertain win-rate gain, since they are not independent information sources.
- **Pros:** Conceptually simple to reason about; both indicators already exist in the codebase (`src/indicators/supertrend.py`, `src/indicators/donchian.py` used via `src/indicators.Donchian`).
- **Cons:** (1) Weakest evidence base of the three filters — no strong literature/backtest citation found for "require Supertrend direction === Donchian breakout direction" specifically as an entry gate (as opposed to trailing use, which is already implemented). (2) Design ambiguity: `donchian_breakout.py` already owns a `Supertrend` instance for trailing (`config.trailing_atr_period`/`trailing_atr_multiplier`) — adding a *second* Supertrend instance with *entry* semantics (likely different period/multiplier) risks confusing config surface and needs an explicit naming/config decision before implementation, not just a wire-up. (3) Two correlated trend detectors gating each other mostly shrinks trade count (fewer signals) without a clear independent-evidence argument for why win rate specifically improves, unlike ADX (measures a different property — trend *strength*, not trend *direction*) or VWAP (measures *institutional positioning bias*, an orthogonal signal).
- **Integration cost:** **Medium** — needs a config decision (separate Supertrend params for entry-confluence vs. trailing) before code, plus care to avoid the two Supertrend instances stepping on each other's warmup/reset lifecycle.

### Filter C: Session VWAP bias filter
- **Source:** Forextester/Scanz/TradingView/Metrotrade/HumbledTrader — consistent, repeated description of the "long only above VWAP / short only below VWAP" institutional-benchmark heuristic across futures/FX/equities day-trading literature.
- **License:** N/A — descriptive trading heuristic, not code; project's own `SessionVWAP` implementation is original.
- **Stars/activity:** N/A (methodology, not a repo) — but the underlying rationale (VWAP as an institutional execution benchmark that large desks trade against) is one of the most consistently repeated intraday concepts across the sources found, stronger *conceptual* consensus than Filter B, though still not a peer-reviewed backtest.
- **Fit:** Direct fit for a directional bias gate on trend-flip/breakout entries: only take BUY signals when `close > session_vwap`, only take SELL when `close < session_vwap`.
- **Pros:** Project already has a correctly-built, tz-configurable `SessionVWAP` (fixes the native indicator's UTC-midnight-only reset limitation, see NautilusTrader section above) sitting unused; the filter itself is a single comparison, no new math. Orthogonal signal source (order-flow/institutional positioning) vs. ADX (volatility/trend-strength) and Supertrend/Donchian (price-band trend), so combining it with Filter A is complementary rather than redundant.
- **Cons:** Session-boundary choice is a real open design question for a multi-instrument, multi-timezone system — XAUUSD intraday convention in the literature found is typically anchored to a session open (e.g. NY futures session or exchange midnight), while 24-hour FX majors have no single "correct" session start; the sources found describe the concept generically ("day" or "session") without prescribing a specific boundary per instrument class. This needs a project-specific decision (see Open Questions), not something the literature resolves for us.
- **Integration cost:** **Low** — same shape as Filter A: instantiate `SessionVWAP(tz=...)`, register in `on_start`/`on_reset`, add a directional guard in `generate_signal`. The only non-trivial decision is picking `tz` per instrument class.

## Comparison table

| Filter | Evidence strength | Implementation cost | Expected effect on trade count | Expected effect on win rate |
|---|---|---|---|---|
| A. ADX gate (≥25) | Strong — repeated across independent sources (freqtrade community, ADX-specific python repos, educational sites), and the project already uses the same threshold for regime routing | Low — indicator exists, unused; ~10-line guard | Moderate reduction — filters chop-regime bars specifically | Likely up — targets the failure mode (breakout/flip in ranging market) most cited in the redesign hypothesis |
| B. Supertrend↔Donchian confluence | Weak — mostly anecdotal community strategies, no independent-evidence argument found; two correlated band-based trend detectors | Medium — config/design decision needed (second Supertrend instance with different semantics than existing trailing one) | Large reduction — correlated filters compound restrictiveness | Uncertain — evidence doesn't clearly separate "fewer trades" from "better trades" |
| C. Session VWAP bias | Moderate — strong conceptual consensus in intraday literature, but no backtest-specific numbers found; session-boundary choice for XAUUSD/FX is an open design question | Low — indicator exists, unused; single comparison guard | Moderate reduction — cuts counter-VWAP entries | Likely up, and orthogonal to A — combinable without redundancy |

## Key API / code references

ADX indicator already in codebase and wired into the regime classifier at the same threshold recommended here:

```python
# services/trading-engine/src/regime/classifier.py (existing usage)
if features.adx >= t.adx_trend_min:   # ftmo.yaml: adx_trend_min: 25.0
    ...
```
Source: `services/trading-engine/src/regime/classifier.py:59`, `configs/firms/ftmo.yaml:108`.

freqtrade community pattern for ADX-as-gate (threshold convention, not to be copied verbatim — GPL-3.0):
```python
(qtpylib.crossed_above(dataframe['rsi'], 50)) &
(qtpylib.crossed_above(dataframe['ema5'], dataframe['ema10'])) &
(dataframe['adx'] > 25) &
(dataframe['volume'] > 0)
```
Source: [freqtrade/freqtrade-strategies hlhb.py](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/hlhb.py)

Native NautilusTrader VWAP reset condition (verified from installed package, not docs):
```python
# nautilus_trader/indicators/volume.pyx:187-191
if timestamp.day != self._day:
    self.reset()
    self._day = timestamp.day
    self.value = price
```
Source: `services/trading-engine/.venv/Lib/site-packages/nautilus_trader/indicators/volume.pyx:188` (local install, version pinned by project's `pyproject.toml`/`uv.lock` — not re-verified against upstream changelog).

## Recommendation for Track 5.1 (ranked)

1. **ADX gate (Filter A)** — implement first. Strongest evidence, lowest cost, reuses an existing indicator already validated at the same threshold in the regime classifier, and directly targets the stated hypothesis (raw breakout/flip entries are noisy in ranging conditions).
2. **Session VWAP bias (Filter C)** — implement second, same sprint if time allows. Low cost, orthogonal signal to ADX (institutional positioning vs. trend strength), so stacking both is not redundant. Requires one design decision (session boundary per instrument, see below) before coding.
3. **Supertrend↔Donchian confluence (Filter B)** — defer. Weakest evidence, medium cost, and a config-design question (second Supertrend instance) that should not be resolved inside a filter-implementation story. Revisit only if Filters A/C under-deliver in walk-forward and a genuinely independent third filter is still wanted.

Per the project's no-parameter-sweep constraint: use `ADX(14) >= 25.0` (project's existing default) and a single project-standard session tz for `SessionVWAP` (see Open Questions) as literature-backed defaults; validate both via walk-forward per the redesign plan, not via sweep.

## Open questions

1. **gh CLI was unauthenticated in this sandbox** (`gh auth status` → not logged in, `GH_TOKEN` unset), so GitHub code/repo search was done via `WebSearch` rather than `gh search repos`/`gh search code` as the standard research order prescribes. Star counts and recency for the specific strategy files cited (e.g. `hlhb.py`, Nikhil-Adithyan's ADX repo) were not independently re-verified via the GitHub API — only via search-result summaries. If precise recency/star data is needed before committing to Filter A, re-run with `gh auth login` or `GH_TOKEN` set.
2. **Context7 MCP tool was not available in this environment** (not present in the tool list for this session) — the NautilusTrader indicator survey was done by reading the installed `nautilus_trader` package source directly under `services/trading-engine/.venv/Lib/site-packages/nautilus_trader/indicators/` instead. This is arguably more authoritative (exact pinned version, not generic docs) but does not confirm whether newer/older NautilusTrader releases changed `VolumeWeightedAveragePrice` or added a native ADX — re-check via Context7 or CHANGELOG.md if upgrading the pin.
3. **Session-VWAP boundary choice is unresolved** — no source found prescribing a specific session anchor for XAUUSD vs. 24h FX majors; this needs a project decision (candidates: FTMO/broker-server midnight — simplest, matches `SessionFilterMixin.session_id` default; or NY futures session open ~13:30 UTC for gold specifically, mirroring COMEX/CME session conventions mentioned generically in the VWAP literature). Recommend picking broker-server midnight for v1 consistency across both instrument classes and revisiting only if walk-forward shows a session-boundary-sensitive result.
4. **No quantitative backtest numbers** (win-rate delta, trade-count delta) were found for any of the three filters specifically on XAUUSD/FX M5/M15 — all evidence is qualitative/heuristic consensus across sources, consistent with the project's own constraint to validate via walk-forward rather than trust sweep-fitted numbers from unrelated markets/timeframes.
5. **ADX behavior around gold news spikes** (NFP/FOMC/CPI false-positive gate opens) is inferred from ADX's general lag properties plus the project's own prior research (`strategy-tactics-quant-review.md`), not from a gold-specific backtest citation — worth flagging as a specific walk-forward check (does the ADX gate open right before/during scheduled news and let through a bad trade) rather than assuming the generic ADX>25 heuristic is news-safe.

## Sources

- [freqtrade/freqtrade-strategies — hlhb.py](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/hlhb.py)
- [freqtrade/freqtrade-strategies — ADXMomentum.py](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/ADXMomentum.py)
- [Nikhil-Adithyan/Algorithmic-Trading-with-ADX-in-python — adx_strategy_code.py](https://github.com/Nikhil-Adithyan/Algorithmic-Trading-with-ADX-in-python/blob/master/adx_strategy_code.py)
- [ADX 25+: The One Filter That Kills Bad Trades — FXNX](https://fxnx.com/en/blog/adx-strategy-efficiency-filter-measure-trend-strength-like)
- [ADX — CrossTrade learning center](https://crosstrade.io/learn/technical-indicators/adx)
- [Momentum Multi-Indicator Trend Following Strategy: Donchian + SuperTrend + Volume Filter — FMZ Quant](https://www.fmz.com/lang/en/strategy/483076)
- [Dual Donchian Channel Breakout Strategy — FMZQuant (Medium)](https://medium.com/@FMZQuant/dual-donchian-channel-breakout-strategy-b316bcb10fb0)
- [Donchian Channel Trading Strategies — TrendSpider](https://trendspider.com/learning-center/donchian-channel-trading-strategies/)
- [VWAP Indicator Guide — Forextester](https://forextester.com/blog/vwap/)
- [VWAP Trading Strategy — Scanz](https://scanz.com/vwap-trading-strategy/)
- [Understanding VWAP for Futures Trading — Metrotrade](https://www.metrotrade.com/understanding-vwap-for-futures-trading/)
- [VWAP Strategy Secrets — HumbledTrader](https://www.humbledtrader.com/blog/vwap-strategy-secrets-boosting-your-trading-skills-to-the-next-level/)
- Local: `services/trading-engine/src/indicators/adx.py`, `session_vwap.py`, `supertrend.py`
- Local: `services/trading-engine/src/regime/features.py`, `classifier.py`, `configs/firms/ftmo.yaml`
- Local: `services/trading-engine/.venv/Lib/site-packages/nautilus_trader/indicators/trend.pyx`, `volume.pyx` (installed package, pinned version — verified directly, Context7 unavailable this session)
- Prior research: `docs/research/strategy-tactics-quant-review.md` (2026-05-05)
