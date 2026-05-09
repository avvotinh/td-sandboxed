# Epic 13: Strategy Tactics Phase 1 — 50/50 + Trail Uncapped — Technical Context

**Created:** 2026-05-09
**Last updated:** 2026-05-09
**Status:** **Contexted** — transitioning from research-only to backlog
**Epic:** 13 of 13+
**Stories:** 9 (13.1 – 13.9)
**Branch:** `epic-13-strategy-tactics`
**Predecessor:** Epic 11 (Market Regime Classifier — Phase 1) — closed 2026-05-02 (head `f019861`)
**Source references:**
- `docs/research/strategy-tactics-implementation-plan.md` (implementation plan, 706 lines, §0–§9)
- `docs/research/strategy-tactics-quant-review.md` (quant review, §2.6, §4.1)

---

## Overview

### Problem Statement

Sau Epic 8 (strategies + backtest framework) và Epic 11 (regime classifier), engine có **6 strategies đã ship** nhưng tất cả dùng **single exit pattern**: một TP cứng duy nhất tại N× ATR từ entry. Pattern này:

1. **Cap upside vô điều kiện.** Trend-following strategies (Supertrend, Donchian, MA crossover) có power-law tail distribution — 5-10% trades đi đến +5R→+15R. Khi TP cứng đặt tại 2R hoặc 3R, toàn bộ tail bị cắt. Clenow [Following the Trend, Ch.3]: *"The ratio of average winner to average loser is dominated by the largest winners."* Cắt tail = cắt edge.
2. **Không có breakeven protection.** Sau khi trade tiến +1R, SL vẫn ở entry –1R. Trade có thể về BE hoặc loss mà không lock-in bất kỳ profit nào.
3. **Không có software trailing.** MT5 native trailing dùng fixed pip distance, không adapts theo ATR. Engine hiện không có software-emulated trailing nào.
4. **Mean-reversion vs trend không phân biệt exit.** ORB, RSI, Bollinger cần TP cứng vì mean-reversion có natural target. Áp trail uncapped lên chúng là sai. Cần gating per-strategy.

Kết quả: theo phân tích §2.6 của quant review, strategy single TP 2R chỉ cho EV ≈ +0.20R/trade, trong khi 50/50 + trail uncapped estimate ≈ +0.26R/trade — 30% cải thiện EV chỉ từ exit tactic, không cần thay đổi entry hay signal.

### Solution

**Phase 1 — 50/50 + Trail Uncapped** (toàn bộ scope của Epic 13):

```
Entry: single fill (giữ nguyên — không thay đổi entry logic)
  ↓
in_position : INITIAL
  full size, hard SL tại sl_atr_mult × ATR (broker stop, safety net)
  safety TP tại 6R (anti-runaway cap — không phải exit target)
  ↓ (price hits +1R)
in_position : SCALED_OUT_BE
  đóng 50% tại thị trường (reduce_only=True)
  kéo SL remaining 50% về entry price (breakeven) via Strategy.modify_order()
  ↓ (Supertrend ATR(7)×2.1 trail tightens OR hits BE-SL)
flat (close remaining 50%)
```

**Áp dụng cho:** Supertrend, Donchian breakout, MA crossover (trend-following).
**Gated (giữ TP cứng):** Bollinger mean-reversion, RSI mean-reversion, ORB — mean-reversion có natural target, trail uncapped không tối ưu.
**Default OFF:** `scale_out_enabled: bool = False` trong `BracketStrategyConfig` — existing strategies không bị thay đổi behavior cho đến khi operator bật trong `configs/firms/*.yaml`.
**Backtest-only:** Epic 13 validate trên `BacktestExecutionClient` (Nautilus, đầy đủ). Live path (`ZmqExecutionClient._modify_order`) hiện là `NotImplementedError` — unblock là Epic 14 scope.

### Scope

**In Scope:**

- `BracketStrategyConfig` extended với 8 Phase 1 fields: `scale_out_enabled`, `scale_out_r_trigger`, `scale_out_close_fraction`, `breakeven_at_r`, `trailing_enabled`, `trailing_method`, `trailing_atr_period`, `trailing_atr_multiplier`, `safety_tp_atr_mult`; `__post_init__` invariants
- `BaseStrategy._close_partial(fraction)` — reduce-only market order với defensive cap `min(qty × fraction, qty − lot_step)`
- `BaseStrategy._modify_sl(price)` — atomic via `Strategy.modify_order()` public API (confirmed spike §5.5.2)
- `BracketScaleOutMixin` state machine (`_ScaleOutTradeState`: `INITIAL → SCALED_OUT_BE → flat`); 13 table-driven test cases
- `SupertrendStrategy` integration: `on_position_opened` hook, `on_bar` evaluation, reversal handling
- Supertrend ATR(7)×2.1 trailing indicator instance riêng (không share với signal indicator); `_update_trailing_sl()` chỉ tighten, không loosen
- Integration test e2e với synthetic bars (full lifecycle entry → scale-out → BE → trail → close)
- `configs/firms/ftmo.yaml` regime overrides + CLI smoke test
- Backtest A/B validation report: XAUUSD M5 ≥ 100 trades, baseline vs scale-out (`docs/sprint-artifacts/validation-report-epic13.md`)

**Out of Scope (Phase 2 và follow-ups):**

- Multi-leg entry (scaled-in 50/50 zone), multi-leg accounting trong `RiskBasedPositionSizer`
- Variant 60/30/10 hoặc 50/25/25 — sau Phase 1 validate
- Chandelier Exit trailing alternative
- Mean-reversion strategies: scale-out + trail không applicable, giữ TP cứng
- News blackout window (`news_blackout_minutes` config)
- Weekend close logic (`close_before_weekend: true`)
- **Live deployment:** block bởi Epic 14 (MT5 EA + ZmqExecutionClient implementation + mt5-bridge protocol extension)

---

## Architectural Decisions

### 1. Single fill entry giữ nguyên — không thay đổi

**Why:** Multi-leg entry cần aggregate accounting trong `RiskBasedPositionSizer` cho FTMO daily loss limit, phức tạp và risky. Phase 1 trả lời câu hỏi "trail uncapped có cải thiện EV không?" — không cần thay đổi entry để trả lời câu đó. Nếu Phase 1 dương EV, Phase 2 mới test entry.

**Rejected:** 2-leg zone entry (50% at signal, 50% at retest) — deferred Phase 2.

### 2. Partial close tại +1R (cố định) — không adaptive

**Why:** +1R là threshold tiêu chuẩn của industry cho scale-out trigger (InteractiveBrokers Quant Blog, 2023). Adaptive threshold (theo ATR hoặc momentum) phức tạp hơn nhiều và cần validate riêng. Phase 1 validate hypothesis trước, optimize sau.

**Parameter:** `scale_out_r_trigger: Decimal = Decimal("1.0")` trong config — configurable nếu cần test 0.8R hoặc 1.2R trong backtest sweep.

### 3. Supertrend ATR(7)×2.1 cho trailing — không Chandelier, Donchian, SAR

**Why:** Project đã có `src/indicators/supertrend.py` tested. Zero new indicator code. ATR(7)×2.1 là validated parameters cho XAUUSD M15 (TradingView community data, 20K+ bars). Parabolic SAR không adapts to ATR — accelerates trop vite trên choppy Asian session. Fixed-distance trailing không adapts volatility. MA trailing lag quá nhiều trên M5/M15. Chandelier Exit tốt nhưng cần `highest_high` rolling window — thêm code mới không cần thiết khi Supertrend đã available.

**Rejected:** Chandelier (code mới), Parabolic SAR (choppy gold), fixed-distance (không ATR-adaptive), MA trailing (lag quá).

### 4. Software-emulated trail — không MT5 native trailing

**Why:** MT5 native `TRAILING_STOP_MARKET` dùng fixed pip/percentage offset — KHÔNG phải ATR-based, offset không thay đổi theo volatility. Supertrend dynamic line thay đổi mỗi bar theo ATR. Cần emulate software-side trong strategy để adapt dynamically. Cụ thể: `_update_trailing_sl()` so sánh Supertrend line với current SL, chỉ tighten.

**Spike finding (§5.5):** `Strategy.modify_order(order, trigger_price=new_price)` là public API trên Nautilus, hoạt động đầy đủ trên `BacktestExecutionClient`. Không cần cancel-resubmit pattern (lỗi phân tích ban đầu §5.1 đã được sửa §5.5.2).

### 5. Safety TP tại 6R — không bỏ hẳn TP

**Why:** Nếu trailing logic bị bug, hoặc bar feed bị gap qua trail line, position sẽ không có exit target. 6R đủ xa để >99% trades không reach — không capping outliers thực tế — nhưng đủ gần để limit black-swan runaway. Hard broker SL vẫn là layer 1; trail là layer 2; safety TP là layer 3.

**Parameter:** `safety_tp_atr_mult: Decimal = Decimal("6.0")` — thay thế `tp_atr_mult` cũ cho trend-following strategies khi Phase 1 enabled.

### 6. Breakeven move sau scale-out — không partial BE

**Why:** Kéo toàn bộ SL về entry price sau khi đóng 50% là pattern đơn giản nhất, đảm bảo worst-case từ điểm scale-out là +0R chứ không phải −1R. Partial BE (SL về +0.5R) phức tạp hơn và cần validate riêng. FTMO daily loss budget: sau 1R hit + BE move, exposure của remaining 50% không còn ăn vào daily loss budget (SL tại BE).

### 7. Default OFF — per-firm config opt-in

**Why:** Cần đảm bảo existing strategies không thay đổi behavior khi Epic 13 land. `scale_out_enabled: bool = False` là safe default. Operator chọn opt-in per-strategy trong `configs/firms/ftmo.yaml` (strategy-level overrides, Epic 9 firm-bound discipline). Backtest A/B chạy với cả 2 settings trên same dataset.

### 8. Backtest-only — live path deferred sang Epic 14

**Why (§5.5 of implementation plan):** Backtest path (`BacktestExecutionClient`) đã implement đầy đủ `modify_order`, `cancel_order`, `close_position`. Live path (`ZmqExecutionClient`) hiện raise `NotImplementedError` cho `_modify_order`. mt5-bridge protocol (`protocol.rs`) chỉ có `{Tick, Order, OrderResult, Heartbeat, Ack, Error}` — chưa có `ModifyOrder`, `CancelOrder`. MT5 EA (MQL5) chưa tồn tại. Ba gaps này thuộc Epic 14 scope — riêng, parallel với Epic 13, không block validation.

```
Epic 12 (backtest validation)        ─── PAUSED ──┐
                                                  │
Epic 13 (strategy tactics, backtest) ─── ACTIVE  ─┼─── Epic 15 (production deploy)
                                                  │
Epic 14 (MT5 EA + bridge live path)  ─── NEW ────┘
```

---

## Story Breakdown

Story 13.1 đã hoàn thành dưới dạng **research spike** (không có code commit, không có story doc — phát hiện landed trong §5.1 + §5.5 của implementation plan). Stories 13.2–13.9 là backlog chờ dev.

| ID | Title | Size | Status |
|---|---|---|---|
| 13.1 | Nautilus modify_order + reduce_only spike | S | **done** (research spike — §5.1 + §5.5 of implementation plan; no code commit) |
| 13.2 | Config fields + validation | S | backlog |
| 13.3 | BaseStrategy helpers: `_close_partial` + `_modify_sl` | M | backlog |
| 13.4 | `BracketScaleOutMixin` state machine | M | backlog |
| 13.5 | SupertrendStrategy integration | M | backlog |
| 13.6 | Supertrend trailing indicator + `_update_trailing_sl` | M | backlog |
| 13.7 | Integration test e2e với synthetic bars | M | backlog |
| 13.8 | Per-firm config wiring + ftmo.yaml updates | S | backlog |
| 13.9 | Backtest A/B validation report | M | backlog |

**Size breakdown:** 6 M + 2 S + 1 done (S) ≈ **1.5–2 tuần** dev time 1 FT.

**Per-story docs:** Không có (Option C — không có XL stories trong epic này).

---

## Dependencies & Sequencing

```
13.1 (done — research spike)
  ↓
13.2 (config fields)
  ↓
13.3 (BaseStrategy helpers)
  ↓
13.4 (BracketScaleOutMixin state machine)
  ↓
13.5 (SupertrendStrategy integration)
  ↓
13.6 (Supertrend trailing indicator)
  ↓
13.7 (integration test e2e synthetic bars)
  ↓
13.8 (per-firm config wiring) → 13.9 (backtest A/B validation)
                                       ↑
                          depends: operator dataset fetch
                          (docs/runbooks/backtest-data-fetch.md)
                          shared blocker với Epic 12.7
```

13.9 là story duy nhất block bởi dataset thực từ operator fetch. Stories 13.2–13.8 chỉ cần synthetic bars + unit tests — có thể chạy **parallel với Epic 12.7 data fetch campaign**.

---

## Risks & Coordination Notes

### R1 — Strategy.modify_order semantics trên BacktestExecutionClient với bracket linked SL

**Risk:** `Strategy.modify_order(sl_order, trigger_price=new_price)` chưa được test thực tế với bracket order linked SL trong backtest. Behavior khi modify linked order có thể khác expected.

**Mitigation:** Story 13.3 bao gồm 5-min REPL spike với synthetic bars + Nautilus BacktestEngine trước khi commit implementation. Pattern đã được confirm hoạt động ở strategy level (§5.5.2 spike), nhưng bracket-specific behavior cần verify trực tiếp.

**Reference:** `Strategy.modify_order` confirmed public API (§5.5.2): `cancel_all_orders, cancel_order, cancel_orders, close_position, modify_order, query_order, submit_order, submit_order_list` — tất cả là public methods.

### R2 — Live path NotImplementedError vẫn còn sau Epic 13

**Risk:** Sau khi Epic 13 ship, nếu operator muốn enable live trading với scale-out, `ZmqExecutionClient._modify_order` sẽ raise `NotImplementedError` → position không có trailing SL update trên live.

**Mitigation:** Document rõ trong validation report (story 13.9) rằng Phase 1 validate trên backtest, live deployment block bởi Epic 14. `scale_out_enabled: false` là default trong ftmo.yaml — không ai vô tình enable live.

### R3 — reduce_only behavior với bracket linked SL untested

**Risk:** Khi submit `reduce_only=True` market order để close 50%, behavior của Nautilus engine khi position còn bracket linked SL/TP chưa được documented rõ. Engine có thể cancel toàn bộ bracket hay chỉ adjust.

**Mitigation:** Story 13.3 spike (5-min REPL test). Defensive cap: `min(qty × fraction, qty − lot_step)` tránh edge case nếu reduce_only auto-cancel toàn bộ. `OrderCanceled` event handling (optional audit, không block state machine).

### R4 — Shared blocker với Epic 12.7 = operator dataset fetch

**Risk:** Story 13.9 (backtest A/B với real data ≥ 100 trades) cần cùng XAUUSD M5 dataset mà Epic 12.7 cần. Nếu operator fetch bị delay, cả 2 stories block.

**Mitigation:** 13.9 chỉ block 13.9 — stories 13.2–13.8 với synthetic bars hoàn toàn độc lập. Parallel với data fetch: dev làm 13.2–13.8 trong khi operator fetch data. Backtest harness (Epic 12.1–12.6) đã ship và sẵn sàng consume data khi có.

---

## Phase 2 Roadmap (preview, NOT in scope)

Items deferred từ Phase 1 (§7 của implementation plan):

1. **Multi-leg entry** (2-leg 50/50 zone entry) — cần `RiskBasedPositionSizer` aggregate accounting
2. **Variant 60/30/10** (3-leg weighted, leg 3 trail uncapped) — sau Phase 1 positive EV confirm
3. **Variant 50/25/25** (Section 2.3 reference pattern) — cao hơn 60/30/10 về capture tail
4. **Chandelier Exit** trailing alternative — sau Phase 1 nếu Supertrend whipsaw nhiều
5. **Mean-reversion strategies** exit improvement — time-based exit (`bars_since_entry` counter); không phải scale-out
6. **News blackout window** (`news_blackout_minutes` config) — story riêng
7. **Weekend close logic** (`close_before_weekend: true`) — story riêng

---

## Architecture.md Update Note

`docs/architecture.md` hiện ở version 3.2 (post-Epic 11). Sau khi Epic 13 ships, architecture.md nên được cập nhật để thêm **Strategy State Machine subsection** (new: `INITIAL → SCALED_OUT_BE → flat` sub-states cho in-position phase) và note về software-emulated trailing layer. **Không cần update ngay — defer đến epic-done trigger khi tất cả 9 stories done.**

---

## References

- **Implementation plan:** `docs/research/strategy-tactics-implementation-plan.md` (§0–§9, spike findings §5.1/§5.5)
- **Quant review:** `docs/research/strategy-tactics-quant-review.md` (§2.6 EV analysis, §4.1 Phase 1 stack)
- **Epic 14 outline:** `docs/research/epic-14-mt5-ea-outline.md` (live path scope)
- **Predecessor epic context:** `docs/epic-11-context.md` (closed 2026-05-02, head `f019861`)
- **Architecture doc:** `docs/architecture.md` v3.2 (post-Epic-11)
- **Source code:**
  - `services/trading-engine/src/strategies/bracket_strategy.py` (BracketStrategyConfig + BracketStrategyMixin)
  - `services/trading-engine/src/strategies/base_strategy.py` (BaseStrategy helpers seam)
  - `services/trading-engine/src/strategies/supertrend.py` (integration target)
  - `services/trading-engine/src/indicators/supertrend.py` (trail indicator reuse — `.value` property confirmed §5.1 Q3)
  - `tests/unit/test_bracket_strategy_mixin.py` (existing test pattern to match)
  - `tests/integration/test_bracket_strategies_smoke.py` (e2e pattern)
- **Configs:** `configs/firms/ftmo.yaml` (per-firm strategy overrides)
- **Project rules:** `.claude/rules/python/`, `.claude/rules/common/sandboxed-domain.md`
