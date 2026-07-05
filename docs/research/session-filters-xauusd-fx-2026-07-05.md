# Research: Trading-Session Time Filters for XAUUSD and FX Majors (M5/M15, FTMO)

**Date:** 2026-07-05
**Requested for:** ad-hoc (roster hardening — supertrend / donchian_breakout / mean_reversion)
**Status:** partial (gh CLI unauthenticated in this environment — GitHub survey done via web search / raw-content fetch instead of `gh search`; academic literature summarized from search snippets, not full-text verified)

## Question

Should the active strategy roster (`supertrend`, `donchian_breakout` — trend; `mean_reversion` — Bollinger×RSI) apply trading-session time filters on XAUUSD and FX majors (M5/M15, FTMO), which windows have credible prior evidence rather than being sweep-optimized, and what (if anything) does the existing `SessionFilterMixin` need to support that?

## TL;DR — Recommendation

Restrict trend strategies (`supertrend`, `donchian_breakout`) to the London+NY window — roughly **07:00–16:00 America/New_York** (covers London open through the London/NY overlap and NY morning), and skip Asian hours for XAUUSD and EUR/GBP pairs; this matches the consistent (if mostly practitioner-grade, not peer-reviewed) evidence that gold and EUR/GBP directional moves concentrate in the London–NY overlap ([NordFX](https://nordfx.com/en/traders-guide/best-time-to-trade-gold-xauusd-sessions-volatility-news), [Quantpedia — daily volatility of FX and time of day](https://quantpedia.com/the-daily-volatility-of-foreign-exchange-rates-and-the-time-of-day/)). Let `mean_reversion` run in the Asian/low-vol window (roughly 00:00–06:00 America/New_York, i.e. Tokyo session) where range-bound behavior is best documented, and optionally allow it through London pre-overlap too — do NOT sweep-optimize the boundary, use the session structure as-is. `SessionFilterMixin` already has everything needed (DST-safe `in_session`/`session_id` via `zoneinfo`, overnight-wrap support); it only needs a thin per-strategy wiring layer (config fields + `generate_signal` gate), analogous to what `orb.py` already does — no core mixin changes required. Status is partial because gh CLI is unauthenticated in this sandbox (no `gh search` results) and the seasonality claims rest on aggregator/blog sources rather than a peer-reviewed paper actually read in full.

## Existing project code

- `services/trading-engine/src/strategies/mixins/session_filter_mixin.py:1` — `SessionFilterMixin.in_session(ts, session_start, session_end, tz)` and `.session_id(ts, tz)`. Uses `zoneinfo.ZoneInfo` (stdlib, DST-safe against the IANA tz database), rejects naive timestamps, supports overnight wrap (`session_start > session_end`). Fully covered by `services/trading-engine/tests/unit/test_session_filter_mixin.py` including explicit spring-forward/winter DST cases for `Europe/London`.
- `services/trading-engine/src/strategies/orb.py:1` — the only strategy currently consuming `SessionFilterMixin`. Pattern: config carries `session_open_hour/minute`, `session_close_hour/minute`, `session_tz` (IANA string, e.g. `Europe/London`) as plain ints/str (validated in `__post_init__`, no tz math at config time); `generate_signal` computes `session_open`/`session_close` as `datetime.time` per bar and calls `self.in_session(...)`; out-of-session bars force-flatten (`SignalType.CLOSE`) and reset per-session state via `self.session_id`. `ORBStrategy` is registered with `regimes=[]` (opted out of regime routing) — it is currently in the codebase but not part of the "active roster" per project memory (supertrend/donchian/mean_reversion).
- `services/trading-engine/src/strategies/supertrend.py`, `donchian_breakout.py`, `mean_reversion.py` — **no session filtering today** (grep for `Session|tz=` returns no matches in supertrend/donchian; `mean_reversion.py` has no session import either). All three trade every bar in the backtest/live feed regardless of time of day.
- `configs/firms/ftmo.yaml:18-23` — FTMO's daily-reset session is configured as `timezone: "CET"`, `reset_time: "00:00"`, handled by the engine "automatically via zoneinfo." This is a different concern (daily-loss reset anchor) from intraday session filtering, but establishes the project's existing convention of expressing broker-relevant times as IANA-safe tz strings rather than fixed UTC offsets — the same convention `SessionFilterMixin` already follows.
- No prior `docs/research/*.md` on session filters found (`docs/research/README.md` index checked; closest existing docs are `regime-classifier*.md`, which classify volatility/trend regime but do not gate on time-of-day).

## Options evaluated

### Option A: Extend `SessionFilterMixin` usage into `supertrend`/`donchian_breakout`/`mean_reversion` (in-house, already proven)
- **Source:** internal — `services/trading-engine/src/strategies/mixins/session_filter_mixin.py`
- **License:** n/a (internal code)
- **Stars / activity:** actively used by `orb.py`, unit-tested with DST cases as of this branch's history
- **Fit:** direct fit — same bar-timestamp shape (`Bar.ts_init` → UTC `datetime`), same `BracketStrategyConfig` base every roster strategy already extends.
- **Pros:** zero new dependency; DST handling already solved and tested; overnight-wrap already solved (needed for Asian-session MR window that may cross into next UTC day depending on server tz); consistent with `orb.py` precedent so reviewers already know the pattern.
- **Cons:** currently a *predicate*, not a policy — each strategy must wire its own config fields and decide flatten-vs-skip behavior on out-of-session bars (as `orb.py` does). No shared "SessionAwareMixin" that auto-applies to `generate_signal`.
- **Integration cost:** low — add 2-4 config fields per strategy + one `if not self.in_session(...): return SignalType.NONE` (or `CLOSE`, decision below) guard at the top of `generate_signal`.

### Option B: freqtrade-style hour-of-day `IntParameter` filter (adapt pattern, not code)
- **Source:** [freqtrade/freqtrade-strategies — `HourBasedStrategy.py`](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/HourBasedStrategy.py)
- **License:** GPL-3.0 (freqtrade-strategies repo) — **not adoptable verbatim** into this proprietary codebase; pattern-only reference.
- **Stars / activity:** part of the official `freqtrade` org, actively maintained.
- **Fit:** conceptually simple (`dataframe['hour'].between(min, max)`) but built for crypto (24/7 markets, pandas-vectorized backtest, `IntParameter` for hyperopt). Project constraint explicitly rejects parameter-sweep-style hour optimization, so the hyperopt-friendly `IntParameter` shape is actively the wrong pattern here — it invites exactly the sweep the design constraint forbids.
- **Pros:** confirms hour-window filtering is a well-trodden pattern in retail bot frameworks; simple to reason about.
- **Cons:** GPL license (contamination risk if code, not just pattern, is reused), UTC-naive (assumes `dataframe['date']` is already in a fixed tz — no DST handling shown), and hyperopt-oriented (violates the "no parameter sweeps" constraint if adopted as-is).
- **Integration cost:** low if only the *concept* is borrowed (which is what Option A already does); high/inadvisable if code or its hyperopt idiom were copied.

## Key API / code references

`SessionFilterMixin.in_session` — DST-safe predicate already in the codebase (`services/trading-engine/src/strategies/mixins/session_filter_mixin.py:20-36`):

```python
@staticmethod
def in_session(ts, session_start, session_end, tz="UTC") -> bool:
    local_time = SessionFilterMixin._to_local_time(ts, tz)
    if session_start <= session_end:
        return session_start <= local_time <= session_end
    return local_time >= session_start or local_time <= session_end
```

`orb.py`'s wiring pattern to replicate for the other roster strategies (`services/trading-engine/src/strategies/orb.py:150-163`):

```python
in_session = self.in_session(
    ts, session_start=session_open, session_end=session_close,
    tz=self.config.session_tz,
)
if not in_session:
    if not self.is_flat:
        return SignalType.CLOSE
    ...
```

freqtrade's hour-filter idiom (pattern only, GPL source, do not copy verbatim) — [`HourBasedStrategy.py`](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/HourBasedStrategy.py):

```python
dataframe.loc[
    (dataframe['hour'].between(self.buy_hour_min.value, self.buy_hour_max.value)),
    'enter_long'
] = 1
```

## Recommended session windows (evidence-based, no sweep)

All windows expressed as IANA tz strings for `SessionFilterMixin`'s `tz=` parameter (DST resolved automatically via `zoneinfo`); UTC-equivalent given for winter (standard time) as a sanity check only — do not hardcode UTC offsets in config.

| Instrument class | Strategy type | Window (recommended tz) | Rationale / evidence |
|---|---|---|---|
| XAUUSD | Trend (`supertrend`, `donchian_breakout`) | `07:00`–`16:00` **America/New_York** (≈ London open through NY afternoon) | London+NY and their overlap carry gold's largest directional moves and tightest spreads; Asian session is comparatively range-bound. Practitioner-grade but consistent sources: [NordFX](https://nordfx.com/en/traders-guide/best-time-to-trade-gold-xauusd-sessions-volatility-news), [QuantVPS](https://www.quantvps.com/blog/when-to-trade-gold). No peer-reviewed gold-specific study found in this pass — flagged as open question below. |
| XAUUSD | Mean-reversion | `19:00`–`03:00` **America/New_York** (Tokyo/early-Asian range) or simply the *complement* of the trend window | Asian-session gold range-trading is the commonly cited MR regime; low liquidity favors range/reversion over breakout. Same caveat: retail-source evidence, not academic. |
| EURUSD / GBPUSD | Trend | `03:00`–`11:00` **America/New_York** (≈ 08:00–16:00 London local, covering London session + London/NY overlap) | EURUSD volume/volatility share is highest during London hours (>30%); GBPUSD's best average historic volatility window is cited as 08:00–15:00 GMT. [Medium/Power BI analysis](https://medium.com/@jushijun/unveiling-forex-volatility-a-power-bi-analysis-of-eurusd-usdjpy-and-gbpusd-04fc4d5d5917), [Quantpedia](https://quantpedia.com/the-daily-volatility-of-foreign-exchange-rates-and-the-time-of-day/). |
| EURUSD / GBPUSD | Mean-reversion | `20:00`–`02:00` **America/New_York** (Asian/Tokyo overnight) | Same low-vol-session-favors-MR logic as gold; EUR/USD is cited as consolidating in the 23:00–07:00 GMT window. [newyorkcityservers.com Asian-session guide](https://newyorkcityservers.com/blog/asian-session-forex-strategy) (retail source — treat as directional, not definitive). |
| USDJPY | Trend | `19:00`–`04:00` **America/New_York** (Tokyo open through London handoff, ≈ 00:00–09:00 JST+London overlap) | USDJPY volume concentrates in Asian hours (~30% during 12:00–16:00 "Far Eastern" reference in one source) *and* the Tokyo→London handoff; treat USDJPY as the one pair where the Asian session is NOT the low-vol regime. |
| USDJPY | Mean-reversion | US afternoon lull, `12:00`–`17:00` **America/New_York** | Inverse of the trend window — lowest JPY-specific liquidity is the US afternoon before Tokyo reopens. Weakest-evidence row in this table; treat as a hypothesis to validate empirically before shipping, not a settled recommendation. |

**Per-strategy-type summary:** trend strategies (`supertrend`, `donchian_breakout`) → gate to the high-volatility session(s) per instrument above, force-flatten (not just block new entries) outside the window, mirroring `orb.py`'s `SignalType.CLOSE` behavior, since carrying a trend position into a session with no volatility edge is unrewarded risk. Mean-reversion (`mean_reversion`) → gate to the low-volatility/range session; do NOT force-flatten on session exit (a reversion trade may still need time-in-trade to reach its SMA target) — instead simply block *new entries* outside the window and let existing SL/TP/exit logic manage open positions. This is a behavioral difference from `orb.py` and should be an explicit config flag (e.g. `on_session_exit: "flatten" | "block_entries_only"`), not assumed.

## Practical pitfalls (from research + project config)

- **Broker/server tz vs. IANA session tz.** FTMO's MT5 server clock runs GMT+2/GMT+3 (EET/EEST), while FTMO's *daily-loss reset* is expressed/reported in CET/CEST — a 1-hour offset that already required care in `configs/firms/ftmo.yaml:18-23` ("Daily reset at 00:00 CET — engine handles DST automatically via zoneinfo"). If any bar timestamps entering the strategy layer are still in raw MT5 server time (not yet normalized to UTC by `mt5-bridge`) rather than UTC, `session_tz="Europe/London"` etc. would be silently wrong by 1-2 hours. Confirm the `mt5-bridge`→`trading-engine` boundary normalizes to UTC before this ships (grep in this pass did not find explicit UTC-normalization code in `services/mt5-bridge/src/handlers/order_handler.rs` — flagged as open question, not confirmed either way).
- **DST asymmetry between US and EU.** US DST (second Sunday March → first Sunday November) and EU/UK DST (last Sunday March → last Sunday October) do not always shift on the same calendar day, producing 1-week windows per year where "London 08:00" and "NY 08:00" are not a fixed number of hours apart. `SessionFilterMixin`'s `zoneinfo`-based approach handles this correctly per-instrument (each strategy's `session_tz` is resolved independently), but if a strategy ever needs "London AND NY simultaneously" logic (e.g. overlap-only windows), it must not hardcode a UTC delta — express both boundaries via their own IANA tz and combine with `in_session` calls per side, not by adding/subtracting hours.
- **Rollover / spread widening near 22:00 UTC (5pm ET).** Practitioner sources note broker rollover and thin Asia liquidity increase slippage risk for scalps opened right at rollover; no FTMO-specific spread-widening data was found (flagged as open question). A defensive practice would be a short blackout (e.g. ±15 min around 22:00 UTC) even within an otherwise-active session window — not currently modeled by `SessionFilterMixin` (it has no sub-window "exclude" concept, only single start/end).
- **Friday close / Sunday open.** Not addressed by `SessionFilterMixin` or any roster strategy today — weekend gap risk (esp. relevant to FTMO's max-drawdown rule) is a separate concern from intraday session filtering and likely belongs in the FTMO rule engine (`configs/firms/ftmo.yaml`), not the strategy mixin.
- **News blackout (NFP/FOMC).** Web sources note NFP/CPI/FOMC releases land 12:30-18:00 GMT and dominate gold's short-term action — i.e., inside the recommended trend-trading window, not outside it. This is a separate filter dimension (event calendar, not time-of-day) and is out of scope for `SessionFilterMixin`; no open-source implementation of an integrated news-blackout + session filter was found in this pass (freqtrade has no built-in economic calendar).

## What `SessionFilterMixin` needs to change

**Conclusion: no core mixin changes required.** `in_session`/`session_id` already handle DST and overnight wrap correctly (per its existing test suite). What's missing is *policy*, not *mechanism*, and that belongs in each strategy's config/`generate_signal`, following the `orb.py` precedent:

1. Add `session_open_hour/minute`, `session_close_hour/minute`, `session_tz` config fields (same shape as `ORBConfig`) to `supertrend`, `donchian_breakout`, `mean_reversion` configs — likely as an optional/nullable block so session filtering can be toggled off for instruments/timeframes where it's not wanted (e.g. keep 24h trading for a non-FX/gold instrument if the roster ever expands).
2. Decide and implement the flatten-vs-block-entries divergence between trend and MR strategies noted above (`orb.py`'s unconditional `CLOSE` on session-exit is trend-appropriate but wrong for MR).
3. Optional (not required for MVP): a lightweight sub-window "exclude" helper (e.g. `SessionFilterMixin.in_blackout(ts, blackout_start, blackout_end, tz)`) if the team wants the rollover/NFP blackout addressed at the same layer rather than in the rule engine.

## Open questions

- Is bar-timestamp UTC-normalization already guaranteed at the `mt5-bridge` → `trading-engine` boundary, or does `session_tz` risk a silent 1-2h offset bug against FTMO's EET/EEST MT5 server clock? Needs confirmation from whoever owns `mt5-bridge` before shipping session filters live (not resolvable from this pass — `mt5-bridge/src` did not surface explicit UTC conversion code).
- No peer-reviewed academic paper was actually read in full for XAUUSD-specific intraday seasonality (only aggregator/blog summaries); the FX-majors seasonality claims lean on a Quantpedia summary and a Medium Power-BI post rather than the underlying ScienceDirect papers themselves (e.g. "Intraday seasonality in activities of the foreign exchange markets" — abstract-only, not fetched). If this filter materially changes FTMO pass-rate expectations, worth a follow-up pass that actually pulls the ScienceDirect/academia.edu PDFs.
- `gh` CLI is unauthenticated in this sandbox (`gh search` returns "please run gh auth login"), so no GitHub *code* search (only web search of GitHub content) was performed — a proper `gh search code "session_filter" language:python` / `gh search repos "ftmo session filter"` pass once `gh auth login` is available may surface a more directly comparable prop-firm-oriented implementation than freqtrade (which is crypto-first and license-incompatible).
- No FTMO-specific data was found confirming actual spread-widening magnitude around 22:00 UTC rollover — only generic broker-rollover commentary. If this matters for the blackout decision, would need FTMO's own tick-spread data (not publicly documented) rather than web research.

## Sources

- [NordFX — Best Time to Trade Gold (XAUUSD)](https://nordfx.com/en/traders-guide/best-time-to-trade-gold-xauusd-sessions-volatility-news)
- [QuantVPS — When to Trade Gold](https://www.quantvps.com/blog/when-to-trade-gold)
- [Quantpedia — The Daily Volatility of Foreign Exchange Rates and The Time of Day](https://quantpedia.com/the-daily-volatility-of-foreign-exchange-rates-and-the-time-of-day/)
- [Medium (Shijun Ju) — Unveiling Forex Volatility: Power BI Analysis of EURUSD, USDJPY, GBPUSD](https://medium.com/@jushijun/unveiling-forex-volatility-a-power-bi-analysis-of-eurusd-usdjpy-and-gbpusd-04fc4d5d5917)
- [newyorkcityservers.com — Asian Session Forex Strategy](https://newyorkcityservers.com/blog/asian-session-forex-strategy)
- [freqtrade/freqtrade-strategies — HourBasedStrategy.py](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/HourBasedStrategy.py) (GPL-3.0, pattern reference only)
- [The Payout Report — FTMO US MT5 Setup Guide 2026](https://thepayoutreport.com/ftmo-us-mt5-setup-guide-servers-symbols-settings/)
- [The Payout Report — Latency, VPS, and Session Hours for FTMO US](https://thepayoutreport.com/latency-vps-and-session-hours-for-ftmo-us-the-execution-playbook/)
- Internal: `services/trading-engine/src/strategies/mixins/session_filter_mixin.py`, `services/trading-engine/src/strategies/orb.py`, `services/trading-engine/tests/unit/test_session_filter_mixin.py`, `configs/firms/ftmo.yaml`
