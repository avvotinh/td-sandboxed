# Implementation Plan — Strategy Tactics Phase 1 (50/50 + Trail Uncapped)

**Ngày:** 2026-05-06
**Tác giả:** Claude (Opus 4.7) cho dự án Sandboxed
**Tham chiếu:** [`strategy-tactics-quant-review.md`](./strategy-tactics-quant-review.md) §4.1 Phase 1
**Mục tiêu:** Triển khai pattern *single-fill entry → đóng 50% tại 1R, kéo SL về breakeven, trail 50% còn lại bằng Supertrend ATR(7)×2.1 uncapped* trên codebase Sandboxed hiện tại.
**Phase 2 (60/30/10 hoặc 50/25/25):** Out-of-scope của plan này — chỉ adopt sau khi Phase 1 validate trên backtest sweep ≥ 100 trades.

---

## 0. Tóm tắt scope

| Hạng mục | Phase 1 | Out-of-scope |
|---|---|---|
| Entry style | Single fill (giữ nguyên) | Multi-leg entry, scaled-in |
| Partial close events | 1 (tại +1R) | 2+ events (50/25/25, 60/30/10) |
| Breakeven move | Có, trigger tại +1R | BE adaptive, partial BE |
| Trailing method | Supertrend ATR(7)×2.1 software-emulated | Chandelier port, Donchian, Parabolic SAR |
| Trailing scope | Phần còn lại (50%) sau partial close | Trail toàn bộ position từ entry |
| Hard SL | Giữ nguyên `sl_atr_mult × ATR` (broker stop) | — |
| TP cứng | **Bỏ** — leg 2 trail uncapped | — |
| Strategies áp dụng | Trend-following: Supertrend, Donchian, MA crossover | Mean-reversion (Bollinger, RSI, ORB) — giữ TP cứng |
| Per-firm config | Mở `configs/firms/*.yaml` để bật/tắt feature | — |

Lý do gating mean-reversion: scale-out + trail uncapped tối ưu cho power-law tail của trend systems. Mean-reversion có natural target (mid-band, mean) — TP cứng vẫn tốt hơn trail.

---

## 1. Architecture: state machine của 1 trade

Hiện tại 1 trade có 2 state: `flat` ↔ `in_position`. Plan này thêm sub-states cho `in_position`:

```
flat
 │ (entry signal)
 ▼
in_position : INITIAL          ← full size, hard SL, hard TP cứng (chỉ làm cap an toàn 4-5R, tránh runaway)
 │ (price hits +1R)
 ▼
in_position : SCALED_OUT_BE    ← 50% size, SL = entry (breakeven), TP cứng cancel hoặc giữ rất xa
 │ (Supertrend flip OR price hits trail line OR price hits BE-SL)
 ▼
flat (close remaining)
```

**Lưu ý quan trọng:**

1. **TP cứng vẫn tồn tại nhưng "rất xa"** (ví dụ 6R) — không phải bỏ hẳn. Đây là safety cap chống runaway nếu trailing logic bị bug, hoặc bar feed bị gap qua trail line. Đặt 6R đủ xa để không capping outliers thực tế (>99% trades không đến 6R) nhưng đủ gần để giới hạn black-swan flash spike.

2. **SL kéo về BE phải thực hiện qua broker** (modify_order), không chỉ tracking trong memory. Nếu engine crash, SL broker phải đã ở BE.

3. **Trail line tính software từ Supertrend indicator của bar feed**, KHÔNG phải MT5 native trailing stop. Lý do: MT5 native trailing dùng pip-distance fixed, không phải ATR-based.

4. **Trailing chỉ áp dụng cho 50% phần còn lại** sau khi partial close. Trước +1R: chỉ có hard SL, không trail.

---

## 2. File-level changes

### 2.1 `services/trading-engine/src/strategies/bracket_strategy.py`

**Thay đổi chính:** Mở rộng `BracketStrategyConfig` với fields mới + thêm `BracketScaleOutMixin` để host the new state machine.

**Config additions:**

```python
class BracketStrategyConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    # ... existing fields ...

    # Phase 1 — scale-out + trail (default OFF để không break existing strategies)
    scale_out_enabled: bool = False
    scale_out_r_trigger: Decimal = Decimal("1.0")      # +1R
    scale_out_close_fraction: Decimal = Decimal("0.5")  # 50%
    breakeven_at_r: Decimal | None = Decimal("1.0")    # None = không kéo BE
    trailing_enabled: bool = False
    trailing_method: str = "supertrend"  # Literal["supertrend", "chandelier"] — Phase 1 chỉ "supertrend"
    trailing_atr_period: int = 7
    trailing_atr_multiplier: Decimal = Decimal("2.1")
    safety_tp_atr_mult: Decimal = Decimal("6.0")  # safety cap thay cho tp_atr_mult cũ

    def __post_init__(self) -> None:
        # ... existing validation ...
        if self.scale_out_enabled and not (Decimal("0") < self.scale_out_close_fraction < Decimal("1")):
            raise ValueError(
                f"scale_out_close_fraction must be in (0, 1), got {self.scale_out_close_fraction}"
            )
        if self.scale_out_enabled and self.scale_out_r_trigger <= 0:
            raise ValueError(
                f"scale_out_r_trigger must be > 0, got {self.scale_out_r_trigger}"
            )
        if self.trailing_enabled and self.trailing_method not in {"supertrend"}:
            raise ValueError(f"trailing_method '{self.trailing_method}' not supported in Phase 1")
```

**New mixin** (cùng file hoặc tách thành `bracket_scale_out.py` nếu mixin > 150 LoC):

```python
@dataclass
class _ScaleOutTradeState:
    """Mutable state cho 1 trade đang mở khi scale_out_enabled = True."""
    entry_price: Decimal
    initial_sl: Decimal
    initial_qty: Decimal
    side: OrderSide                  # BUY hoặc SELL
    risk_per_unit: Decimal           # |entry - sl| = 1R
    scaled_out: bool = False         # True sau khi đóng 50% tại 1R
    breakeven_moved: bool = False
    trail_active: bool = False


class BracketScaleOutMixin:
    """Track partial close, breakeven move, và software trailing.

    Host phải provide: self.config (BracketStrategyConfig), self.cache,
    self._supertrend_trail_indicator (initialized trong on_start nếu trailing_enabled),
    self._open_position(), self._modify_sl(price), self._close_partial(fraction),
    self._close_position().
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._scale_state: _ScaleOutTradeState | None = None

    def on_position_opened(self, side: OrderSide, entry_price: Decimal,
                            sl_price: Decimal, qty: Decimal) -> None:
        """Gọi từ host ngay sau khi bracket fill confirm."""
        if not self.config.scale_out_enabled:
            return
        self._scale_state = _ScaleOutTradeState(
            entry_price=entry_price,
            initial_sl=sl_price,
            initial_qty=qty,
            side=side,
            risk_per_unit=abs(entry_price - sl_price),
        )

    def on_position_closed(self) -> None:
        self._scale_state = None

    def evaluate_scale_out(self, current_price: Decimal) -> None:
        """Gọi mỗi bar/tick. Idempotent — đã scaled_out thì no-op cho phần đó."""
        st = self._scale_state
        if st is None or st.risk_per_unit <= 0:
            return

        # Tính R-multiple đã đạt
        if st.side == OrderSide.BUY:
            unrealized_r = (current_price - st.entry_price) / st.risk_per_unit
        else:
            unrealized_r = (st.entry_price - current_price) / st.risk_per_unit

        # Step 1: partial close tại +1R
        if not st.scaled_out and unrealized_r >= self.config.scale_out_r_trigger:
            self._close_partial(self.config.scale_out_close_fraction)
            st.scaled_out = True
            logger.info(
                "Scale-out triggered at R=%.2f, closed %.0f%% of position",
                float(unrealized_r),
                float(self.config.scale_out_close_fraction * 100),
            )

        # Step 2: kéo SL về breakeven (sau khi đã scale-out, chỉ làm 1 lần)
        if (st.scaled_out and not st.breakeven_moved
                and self.config.breakeven_at_r is not None
                and unrealized_r >= self.config.breakeven_at_r):
            self._modify_sl(st.entry_price)
            st.breakeven_moved = True
            logger.info("SL moved to breakeven at %s", st.entry_price)

        # Step 3: activate trailing (sau breakeven move)
        if (st.breakeven_moved and not st.trail_active
                and self.config.trailing_enabled):
            st.trail_active = True
            logger.info("Trailing activated")

        # Step 4: update trail line mỗi bar khi active
        if st.trail_active:
            self._update_trailing_sl(st)

    def _update_trailing_sl(self, st: _ScaleOutTradeState) -> None:
        """Read Supertrend line, modify SL nếu line tightened về phía entry."""
        # Implementation chi tiết tại §2.4 — Supertrend line read.
        ...
```

**Test:** `tests/unit/test_bracket_scale_out.py` — table-driven cho từng state transition (xem §3).

---

### 2.2 `services/trading-engine/src/strategies/base_strategy.py`

**Thay đổi:** Thêm helper `_close_partial(fraction)` và `_modify_sl(price)`.

```python
def _close_partial(self, fraction: Decimal) -> None:
    """Đóng `fraction` của open position bằng reduce-only market order.

    fraction phải trong (0, 1). Số lượng đóng được làm tròn xuống
    bằng instrument.make_qty (Nautilus đảm bảo lot size step).
    Nếu kết quả round xuống 0 (position quá nhỏ), no-op + log warning.
    """
    if not (Decimal("0") < fraction < Decimal("1")):
        raise ValueError(f"fraction must be in (0,1), got {fraction}")
    if not self._position:
        return
    current_qty = Decimal(str(self._position.quantity.as_double()))
    close_qty_raw = current_qty * fraction
    close_qty = self._instrument.make_qty(close_qty_raw)
    if close_qty.as_double() <= 0:
        self._log.warning(
            "Partial close fraction %s of qty %s rounded to 0; skipping",
            fraction, current_qty,
        )
        return
    side = OrderSide.SELL if self._position.is_long else OrderSide.BUY
    order = self.order_factory.market(
        instrument_id=self.config.instrument_id,
        order_side=side,
        quantity=close_qty,
        reduce_only=True,
    )
    self.submit_order(order)
    self._log.info("Submitted partial close %s @ market", close_qty)


def _modify_sl(self, new_sl_price: Decimal) -> None:
    """Modify SL của bracket order hiện tại.

    Nautilus exposes order.modify() trên StopMarket leg của bracket.
    Nếu không tìm thấy SL leg active, log warning và no-op (broker
    có thể đã fill SL trong race với bar tick).
    """
    sl_order = self._find_active_sl_order()  # helper mới
    if sl_order is None:
        self._log.warning("No active SL order found; cannot modify to %s", new_sl_price)
        return
    new_price = self._instrument.make_price(new_sl_price)
    self.modify_order(sl_order, trigger_price=new_price)
    self._log.info("Modified SL trigger to %s", new_price)
```

**Note:** API chính xác của Nautilus `modify_order` cần verify với docs (Context7). Có thể là `cancel + new` thay vì `modify` — chọn cách Nautilus support đầy đủ. Đây là điểm cần spike trước khi implement.

---

### 2.3 `services/trading-engine/src/strategies/supertrend.py`

**Thay đổi:** Thêm `BracketScaleOutMixin` vào MRO, hook `on_bar` để gọi `evaluate_scale_out`.

```python
class SupertrendStrategy(
    BracketScaleOutMixin,        # ← thêm
    BracketStrategyMixin,
    ATRStopMixin,
    RiskSizedMixin,
    SessionFilterMixin,
    BaseStrategy,
):
    def on_bar(self, bar: Bar) -> None:
        super().on_bar(bar)  # giữ existing signal logic

        # Scale-out evaluation chỉ chạy khi config bật và đang in position
        if self.config.scale_out_enabled and not self.is_flat:
            current_price = Decimal(str(bar.close.as_double()))
            self.evaluate_scale_out(current_price)
```

Khi `_execute_signal` submit bracket thành công, hook `on_position_opened` qua Nautilus `on_position_opened` event:

```python
    def on_position_opened(self, event: PositionOpened) -> None:
        if not self.config.scale_out_enabled:
            return
        side = event.position.side  # OrderSide.BUY/SELL
        entry = Decimal(str(event.position.avg_px_open))
        # SL price từ bracket — read qua linked order
        sl_order = self._find_active_sl_order()
        sl_price = Decimal(str(sl_order.trigger_price)) if sl_order else self._last_sl_price
        qty = Decimal(str(event.position.quantity.as_double()))
        # Forward to mixin
        super().on_position_opened(side, entry, sl_price, qty)
```

**Reversal logic:** SupertrendStrategy hiện đảo position khi flip. Với scale-out enabled, flip cần đóng remainder chứ không phải reverse full size. Hành vi: nếu Supertrend flip xảy ra trong state SCALED_OUT_BE, chỉ `close_position()` rồi entry mới — không reverse với original size.

---

### 2.4 `services/trading-engine/src/indicators/supertrend.py` (re-use, không sửa)

Plan dùng existing `Supertrend` indicator nhưng **instance riêng** với `period=7, multiplier=2.1` cho trailing — KHÔNG share với indicator dùng cho signal generation (period/multiplier có thể khác).

Trong `SupertrendStrategy.on_start()`:

```python
def on_start(self) -> None:
    # existing: self._supertrend = Supertrend(period=cfg.signal_period, ...)
    # new (chỉ khi trailing_enabled):
    if self.config.trailing_enabled:
        self._supertrend_trail = Supertrend(
            period=self.config.trailing_atr_period,
            multiplier=self.config.trailing_atr_multiplier,
        )
        self.register_indicator_for_bars(self.config.bar_type, self._supertrend_trail)
```

`_update_trailing_sl` reads `self._supertrend_trail.value` (line price), so sánh với current SL, chỉ tighten (không loosen):

```python
def _update_trailing_sl(self, st: _ScaleOutTradeState) -> None:
    if not self._supertrend_trail.initialized:
        return
    trail_line = Decimal(str(self._supertrend_trail.value))

    sl_order = self._find_active_sl_order()
    if sl_order is None:
        return
    current_sl = Decimal(str(sl_order.trigger_price))

    # Tighten only: BUY → new_sl > current_sl; SELL → new_sl < current_sl
    if st.side == OrderSide.BUY and trail_line > current_sl:
        self._modify_sl(trail_line)
    elif st.side == OrderSide.SELL and trail_line < current_sl:
        self._modify_sl(trail_line)
```

---

### 2.5 `configs/firms/ftmo.yaml`

Thêm strategy-level overrides cho phép enable/disable Phase 1 features per strategy:

```yaml
strategies:
  supertrend_xauusd:
    scale_out_enabled: true        # Phase 1: bật cho Supertrend gold
    scale_out_r_trigger: 1.0
    scale_out_close_fraction: 0.5
    breakeven_at_r: 1.0
    trailing_enabled: true
    trailing_method: supertrend
    trailing_atr_period: 7
    trailing_atr_multiplier: 2.1
    safety_tp_atr_mult: 6.0

  rsi_mean_reversion_xauusd:
    scale_out_enabled: false       # mean-reversion KHÔNG dùng scale-out
```

---

## 3. Test strategy

Pytest, table-driven nơi có thể, mock Nautilus order submission qua existing patterns trong `tests/unit/test_bracket_strategy_mixin.py`.

### 3.1 Unit tests — `tests/unit/test_bracket_scale_out.py` (mới)

| Test | Setup | Expected |
|---|---|---|
| `test_no_scale_out_when_disabled` | `scale_out_enabled=False` | `evaluate_scale_out` no-op, không submit close order |
| `test_scale_out_triggers_at_1r_long` | LONG, entry=2000, SL=1990, current=2010 (1R) | `_close_partial(0.5)` called |
| `test_scale_out_triggers_at_1r_short` | SELL, entry=2000, SL=2010, current=1990 (1R) | `_close_partial(0.5)` called |
| `test_scale_out_idempotent` | gọi `evaluate_scale_out` 5 lần với cùng price > 1R | chỉ 1 partial close submitted |
| `test_scale_out_not_triggered_below_1r` | current = entry + 0.99R | không close |
| `test_breakeven_move_after_scale_out` | sau scale-out, current = +1R | `_modify_sl(entry_price)` called |
| `test_breakeven_idempotent` | gọi nhiều lần | chỉ 1 modify_sl |
| `test_no_breakeven_when_config_none` | `breakeven_at_r=None` | không modify_sl |
| `test_trailing_only_after_breakeven` | trail_enabled=True nhưng chưa hit 1R | `_update_trailing_sl` không gọi |
| `test_trailing_tightens_only_long` | trail_line vượt current_sl về phía entry | modify_sl |
| `test_trailing_does_not_loosen` | trail_line lùi xa current_sl | không modify_sl |
| `test_state_reset_on_position_close` | `on_position_closed` | `_scale_state is None` |
| `test_invalid_fraction_raises` | `scale_out_close_fraction=0` hoặc =1 | `__post_init__` raises ValueError |

### 3.2 Integration tests — `tests/integration/test_bracket_strategies_smoke.py` (extend)

Thêm scenario `test_supertrend_scale_out_e2e_synthetic_bars`:
- Generate synthetic bar series: 20 bar uptrend (price từ 2000 → 2030), break vào range 2020-2025, sau đó Supertrend flip down
- Assert sequence: open LONG @ 2000 → partial close 50% @ 2010 (+1R giả định SL=1990) → modify SL về 2000 → trail tightening qua các bar ranging → final close @ flip
- Verify total trade = realized PnL của 50% @ 2010 + realized PnL của 50% @ trail line

### 3.3 Backtest validation (out-of-band)

Sau khi unit + integration pass, chạy backtest harness (Epic 12 vẫn paused, nhưng harness 12.1-12.6 đã ship):
- 100+ trades XAUUSD M5 trên IS dataset
- Compare metrics A/B: scale_out_enabled=true vs false
- Acceptance: positive expectancy uplift hoặc parity với cải thiện tail (max winner / 95th percentile winner tăng đáng kể)

---

## 4. Edge cases & risks

| Risk | Severity | Mitigation |
|---|---|---|
| Bar gap qua trail line: bar mở dưới Supertrend trail → broker fill SL với slippage | High | Hard SL ở `sl_atr_mult` vẫn là safety net; trail chỉ là layer 2. Dùng `STOP_MARKET` không phải `STOP_LIMIT` để guarantee fill. |
| Bar gap qua scale-out trigger: bar mở vượt +1R → partial close fill > 1R | Medium | Acceptable — slippage tích cực. Log realized R for audit. |
| Race condition: SL fill trùng với bar tick gọi `_modify_sl` | Medium | `_find_active_sl_order` trả None → no-op + log. Position event handler reset state. |
| Partial close round xuống 0 với position size nhỏ (<0.02 lot) | Low | Log warning + skip; tiếp tục track với original SL/TP. |
| Nautilus `modify_order` không support trigger price modify | High (blocker) | Spike trước implementation: nếu không support, fallback = `cancel(sl_order) + submit(new_sl_order)`. Cần verify atomicity. |
| `RiskBasedPositionSizer` aggregate logic | N/A trong Phase 1 | Không cần thay đổi (Phase 1 vẫn single fill). Document yêu cầu này trong Phase 2 plan. |
| Reversal khi đang trailing: Supertrend flip giữa trade | Medium | Đóng remaining + entry mới (không reverse full size). Test `test_supertrend_flip_during_trail`. |
| Test mock không cover được Nautilus order lifecycle | Medium | Integration test với synthetic bars + Nautilus BacktestEngine real instance — đã có pattern trong `test_bracket_strategies_smoke.py`. |
| Weekend gap với position open | High | Config `close_before_weekend: true` (Section 4.5 research doc) — track riêng story sau Phase 1. |

---

## 5. Spike before coding

3 câu hỏi cần verify TRƯỚC khi viết code, qua Context7 + small Python REPL spike:

1. **Nautilus `modify_order` semantics:** Có support modify `trigger_price` của `STOP_MARKET` order in-place không? Nếu chỉ support cancel-and-resubmit, atomicity guarantee gì? Tài liệu: `nautechsystems/nautilus_trader` Context7.
2. **`reduce_only=True` order behavior:** Khi submit market order ngược chiều với position đang mở + `reduce_only=True`, Nautilus có guarantee không tạo new opposite position nếu close_qty > current_qty (race) không?
3. **Supertrend indicator value access:** `Indicator.value` API có expose được Supertrend "line" (dynamic level) hay chỉ trend direction? Cần đọc `src/indicators/supertrend.py` chi tiết — có thể cần thêm property `line` nếu chưa có.

---

### 5.1 Spike findings (2026-05-06)

#### Q3 — Supertrend indicator: ✅ CONFIRMED, không cần code mới

Đọc trực tiếp `services/trading-engine/src/indicators/supertrend.py:64-66`:

```python
@property
def value(self) -> float | None:
    return self._value
```

`Supertrend.value` trả về **chính cái Supertrend line cần dùng cho trailing** — `final_lower` khi uptrend (trend=+1), `final_upper` khi downtrend (trend=-1) (xem logic line 105-126). Còn `Supertrend.trend` (+1/-1/0) cho hướng. Trước khi `initialized` (ATR chưa warm-up) thì `value is None` — phải guard.

**Implication cho plan:** Dùng `self._supertrend_trail.value` trong `_update_trailing_sl` đúng như §2.4 đã viết, KHÔNG cần modify `src/indicators/supertrend.py`. Cần guard `if not self._supertrend_trail.initialized: return` trước khi đọc.

#### Q1 — `modify_order`: ❌ Không có Strategy convenience API → đổi sang cancel-resubmit pattern

Findings từ Context7 docs cho `nautechsystems/nautilus_trader`:

- **Có** `ModifyOrder` command class (low-level), accepts `trigger_price: Price | None` parameter cùng với `quantity`/`price`.
- **KHÔNG có** Strategy-level `self.modify_order(...)` convenience wrapper trong public API. Phải construct command manually qua engine event-bus, hoặc dùng các pattern thay thế.
- **`TRAILING_STOP_MARKET` native order type** có tồn tại nhưng `trailing_offset` là **fixed distance** (price hoặc percentage) — KHÔNG phù hợp với Supertrend dynamic line vì offset thay đổi mỗi bar theo ATR.
- ExecTester có flag `modify_stop_orders_to_maintain_offset=True` nhưng đây là **backtest-only test harness**, không expose như live strategy API.

**Recommended pattern: cancel + resubmit mỗi bar khi trail line update.**

```python
def _replace_sl(self, new_trigger_price: Decimal) -> None:
    """Cancel SL hiện tại + submit SL mới với trigger price mới.

    Atomicity: có micro-window unprotected giữa cancel ack và new submit fill.
    Acceptable cho M5/M15 bars (gap window << 1s). Cần test riêng cho M1.
    """
    sl_order = self._find_active_sl_order()
    if sl_order is None:
        self._log.warning("No active SL to replace; skipping")
        return

    # Cancel cũ
    self.cancel_order(sl_order)

    # Submit mới với reduce_only=True (Q2 finding: engine sẽ auto-cancel
    # nếu position đã đóng giữa hai lệnh)
    side = OrderSide.SELL if self._position.is_long else OrderSide.BUY
    qty = Quantity.from_str(str(self._position.quantity))
    new_sl = self.order_factory.stop_market(
        instrument_id=self.config.instrument_id,
        order_side=side,
        quantity=qty,
        trigger_price=self._instrument.make_price(new_trigger_price),
        time_in_force=TimeInForce.GTC,
        reduce_only=True,
    )
    self.submit_order(new_sl)
    self._sl_order_id = new_sl.client_order_id  # track cho lần replace tiếp theo
```

**Caveat 1 — Micro-gap unprotected risk:**
- Giữa `cancel_order` ack và `submit_order` fill có window ~10-200ms (depends adapter).
- Với XAUUSD M5/M15 bars, gap window này chỉ tạo rủi ro trong news spike. Không phải blocker.
- **Mitigation:** Hard SL ban đầu (broker-side, bracket leg) vẫn còn — chỉ replace SL khi trail tighter, không loosen. Nếu replace fail (cancel ok, submit fail), hệ thống còn position không có SL → cần error handler reset SL về `last_known_safe_price`.

**Caveat 2 — Order tracking:**
- Bracket SL leg có `client_order_id` → cần track ở mixin. Sau replace, ID mới — phải update.
- Gợi ý: thêm `self._sl_order_id: ClientOrderId | None` vào `_ScaleOutTradeState`, update mỗi lần submit.

**Caveat 3 — Verify với MT5 adapter:**
- Stop market `reduce_only` semantics qua MT5 chưa được docs hóa rõ. Có thể MT5 adapter của Sandboxed không pass-through `reduce_only` xuống broker — cần check `services/mt5-bridge/` và `services/trading-engine/src/adapters/` (nếu có).
- Nếu MT5 adapter chỉ handle ở engine level, behavior backtest và live tương tự. Nếu nó forward xuống MT5 thì tùy MT5 build.

#### Q2 — `reduce_only=True`: ✅ Engine enforces, nhưng có nuance

Findings từ Context7:
- Khi position được đóng hoàn toàn (bởi order khác) trước khi `reduce_only` order trigger → **order bị CANCEL hoàn toàn**, không partial fill.
- Khi position size giảm (race với order khác) → **order qty tự động được giảm tương ứng** bởi engine.
- **KHÔNG cap qty xuống current position size** — tức không "fill như nhiều như có thể"; nó cancel toàn bộ nếu inconsistent.
- Engine-level enforcement, KHÔNG phụ thuộc broker. Backtest và live behave giống nhau ở engine layer.

**Implication cho `_close_partial`:**
- An toàn về reversal: `reduce_only=True` đảm bảo không tạo opposite position.
- Risk: nếu race khiến order bị cancel hoàn toàn, partial close fail → state machine cần handle (ví dụ scaled_out=True nhưng thực tế chưa close → wrong). Cần listen `OrderCanceled` event để reset state.
- **Defensive cap recommended:** trước khi submit, manually cap qty:
  ```python
  current_qty = Decimal(str(self._position.quantity.as_double()))
  close_qty = min(current_qty * fraction, current_qty - Decimal("0.01"))
  ```
  Cap leo phía dưới `current_qty` để không trigger reduce_only auto-reduce nếu lot rounding tạo over-spec.

---

### 5.2 Plan adjustments sau spike (V2 — superseded by §5.5)

**Note 2026-05-06:** Bảng dưới đây là output của spike §5.1 (cancel-resubmit pattern). Đã bị **superseded bởi §5.5 discovery** rằng `Strategy.modify_order` là public API. Giữ làm historical record. Adjustments thực tế áp dụng cho plan: chỉ items không liên quan tới modify pattern (defensive cap, TRAILING_STOP_MARKET reject).

| Item | Original (§2) | Updated post §5.5 (final) |
|---|---|---|
| `BaseStrategy._modify_sl(price)` | Modify SL trigger in-place | ✅ Giữ tên `_modify_sl` (atomic) — qua `Strategy.modify_order` public API |
| Track SL order ID | Không nhắc | Không cần (modify giữ stable order ID) |
| `_close_partial` defensive cap | `make_qty(qty * fraction)` | ✅ **Áp dụng**: `min(qty * fraction, qty - lot_step)` |
| Listen OrderCanceled | Không nhắc | Không cần cho partial close logic; vẫn thêm cho audit (optional) |
| TRAILING_STOP_MARKET native type | Considered | ✅ **Reject** — fixed offset không hợp Supertrend dynamic |
| Cancel-resubmit pattern | Recommended từ §5.1 | ❌ **Drop** — không cần |

### 5.3 Story breakdown — final

- **13.1 — Spike Nautilus modify_order + reduce_only** (✅ DONE — §5.1 + §5.5 verification)
- **13.2 → 13.9** giữ nguyên §6 ban đầu (9 stories), với 1 đổi nhỏ:
  - 13.3 dùng `_modify_sl` (atomic via `Strategy.modify_order`) — KHÔNG phải `_replace_sl`
  - Defensive cap trong `_close_partial`: `min(qty * fraction, qty - lot_step)` (story 13.3)
- Story `13.1.5` (MT5 adapter spike) **drop** — vấn đề thuộc Epic 14 scope.
- Stories `13.3a-d`, `13.1.6` (protocol extension) **drop** — chuyển hẳn sang Epic 14.

### 5.4 Caveats về spike findings

- **Docs-lookup agent §5.1 wrong về `Strategy.modify_order`** — agent conclude từ Context7 docs nhưng `dir(Strategy)` thực tế cho thấy public method tồn tại. Bài học: verify Python API bằng `uv run python -c` trước khi accept conclusion từ docs agent.
- **Live path `_modify_order` chưa work** (`ZmqExecutionClient` raise `NotImplementedError`) — Epic 13 chỉ chạy trên backtest, live block bởi Epic 14.
- **`Strategy.modify_order` semantics trên BacktestExecutionClient** — chưa test thực tế xem behavior với bracket order linked SL như nào. Story 13.3 spike trước khi commit (5-min REPL test với synthetic bars).

---

### 5.5 Architecture revisit (2026-05-06) — Epic 13 backtest-only + Epic 14 separate

**Câu hỏi từ user (lần 1):** *"trading-engine đang dùng ZeroMQ bridge MT5 đúng không? Tại sao không tự tạo function modify order?"*

**User context (lần 2):** *"Hiện tại MT5 EA MQL5 chưa code. Có thể tạo epic để làm riêng."*

Hai câu hỏi này expose 2 blind spot:

1. **Spike §5.1 Q1 wrong về Nautilus public API.** Verified bằng `uv run python -c "from nautilus_trader.trading.strategy import Strategy; print(dir(Strategy))"`: `Strategy.modify_order`, `cancel_order`, `close_position`, `cancel_all_orders` đều là public methods. Trong backtest, `BacktestExecutionClient` implement đầy đủ — `self.modify_order(...)` works immediately, không cần cancel-resubmit, không cần protocol extension.

2. **MT5 EA chưa tồn tại.** Live path (`ZmqExecutionClient`) hiện raise `NotImplementedError` cho modify/cancel — đây là known gap, deferred Epic 11+. Live trading chưa hoạt động end-to-end. Toàn bộ "Option A protocol extension" tôi viết trước đó thuộc về Epic riêng (MT5 EA), KHÔNG phải scope Epic 13.

#### 5.5.1 Architecture verified (2026-05-06)

**Backtest path (Epic 13 chạy trên này):**
```
Strategy (Python/Nautilus)
  │  Strategy.modify_order(order, ...)            ← public API, ✅ works
  │  emits ModifyOrder command
  ▼
BacktestExecutionClient._modify_order(command)   ← Nautilus internal, full impl
  ▼
SimulatedVenue: update SL/TP của order trong-memory atomic
```

**Live path (Epic 14 scope):**
```
Strategy (Python/Nautilus)
  │  Strategy.modify_order(order, ...)
  ▼
ZmqExecutionClient._modify_order(command)        ← services/trading-engine/src/engine/clients/zmq_execution_client.py:234
  │  HIỆN TẠI: raise NotImplementedError ❌
  ▼
ValidatedZmqAdapter ─ ZMQ PUB ─▶ mt5-bridge (Rust)
                                  │  protocol.rs MessageType::{Tick, Order, OrderResult, Heartbeat, Ack, Error}
                                  │  CHƯA CÓ: ModifyOrder, CancelOrder
                                  ▼
                                MT5 EA (MQL5) ❌ CHƯA CODE
                                  │  expected: OrderSend(TRADE_ACTION_SLTP)
                                  ▼
                                MetaTrader 5
```

**Kết luận:** Backtest path đầy đủ → Epic 13 unblocked. Live path 3 gaps (engine translator + bridge protocol + MT5 EA) thuộc về **Epic 14 — riêng và độc lập**, ship được Epic 13 trước khi Epic 14 done.

#### 5.5.2 Discovery: `Strategy.modify_order` là public API

```
$ uv run python -c "from nautilus_trader.trading.strategy import Strategy;
                    print([m for m in dir(Strategy) if 'order' in m or 'cancel' in m or 'close_position' in m])"

cancel_all_orders, cancel_order, cancel_orders, close_position,
modify_order, query_order, submit_order, submit_order_list, ...
```

`self.modify_order(order, trigger_price=new_price)` từ Strategy hoạt động trực tiếp trên backtest. Trên live, command đi xuống `ZmqExecutionClient._modify_order` (hiện stub `NotImplementedError`) — Epic 14 sẽ implement.

**Implication cho Epic 13 plan §2.2:** giữ nguyên tên `_modify_sl` (atomic), implementation đơn giản:

```python
def _modify_sl(self, new_sl_price: Decimal) -> None:
    """Atomic SL modify via Nautilus public API.

    Backtest: BacktestExecutionClient handles in-memory.
    Live: routes to ZmqExecutionClient._modify_order (Epic 14 stub).
    """
    sl_order = self._find_active_sl_order()
    if sl_order is None:
        self._log.warning("No active SL to modify")
        return
    self.modify_order(
        order=sl_order,
        trigger_price=self._instrument.make_price(new_sl_price),
    )
```

KHÔNG cần `_replace_sl` cancel-resubmit pattern. KHÔNG cần thêm story tracking SL order ID changes.

#### 5.5.3 Epic 13 scope adjustment — backtest-only Phase 1

Epic 13 ship được standalone trên backtest path. Live deployment block bởi Epic 14 nhưng không ảnh hưởng validation:

| Khía cạnh | Epic 13 (standalone, backtest-only) |
|---|---|
| Modify SL implementation | `Strategy.modify_order` — works in backtest, `NotImplementedError` trên live (Epic 14 sẽ unblock) |
| Partial close | `order_factory.market(reduce_only=True)` — works in backtest |
| Validation harness | Epic 12 backtest harness (đã ship 12.1-12.6) |
| Acceptance gate | Backtest A/B trên ≥ 100 trades XAUUSD M5 — không cần live |
| Live deployment | Defer — block bởi Epic 14 (MT5 EA + bridge protocol) |

Epic 13 stories **giữ nguyên 9 stories** như §6 ban đầu, drop 13.1.6 / 13.3a-d (đã add cho Option A). Story 13.3 đổi tên helper từ `_replace_sl` sang `_modify_sl` (atomic).

#### 5.5.4 Epic 14 scope (separate document)

Toàn bộ "Option A protocol extension" mà §5.5.3 cũ liệt kê (mt5-bridge protocol enum, MT5 EA MQL5 handler, ZmqExecutionClient implementation, integration test E2E) **chuyển sang Epic 14**. Detail outline tại [`epic-14-mt5-ea-outline.md`](./epic-14-mt5-ea-outline.md) (separate doc).

Epic 14 là epic độc lập, parallel-able với Epic 13. Khi cả 2 done: Epic 15 = production deployment.

#### 5.5.5 Updated dependency map

```
Epic 12 (backtest validation)        ─── PAUSED ──┐
                                                  │
Epic 13 (strategy tactics, backtest) ─── ACTIVE  ─┼─── Epic 15 (production deploy + ops)
                                                  │
Epic 14 (MT5 EA + bridge live path)  ─── NEW ────┘
```

Epic 13 và Epic 14 không depend lẫn nhau ở giai đoạn implementation. Khi backtest validation của Epic 13 cho positive EV và Epic 14 ship live path, Epic 15 wire chúng lại + deploy.

---

---

## 6. Story breakdown (gợi ý cho planner agent)

Pattern: `Implement spec <epic>.<story>` per CLAUDE.md sandboxed-domain rules. Phase 1 mới = epic mới (đề xuất tên `epic-13-strategy-tactics`).

| Story | Size | Dependencies | Deliverable |
|---|---|---|---|
| 13.1 — Spike Nautilus modify_order + reduce_only | S | — | Append decisions section vào plan |
| 13.2 — Add Phase 1 config fields + validation | S | 13.1 | `BracketStrategyConfig` extended, unit tests pass |
| 13.3 — `_close_partial` + `_modify_sl` helpers in `BaseStrategy` | M | 13.1, 13.2 | Helpers + tests cho các edge cases |
| 13.4 — `BracketScaleOutMixin` state machine | M | 13.3 | Mixin + table-driven unit tests (13 cases trong §3.1) |
| 13.5 — Integrate into `SupertrendStrategy` | M | 13.4 | `on_position_opened` hookup, `on_bar` evaluation, reversal handling |
| 13.6 — Supertrend trailing indicator instance + `_update_trailing_sl` | M | 13.5 | Trail tightening logic + tests |
| 13.7 — Integration test e2e với synthetic bars | M | 13.6 | `test_supertrend_scale_out_e2e_synthetic_bars` xanh |
| 13.8 — Per-firm config wiring + ftmo.yaml updates | S | 13.7 | Config load, CLI smoke test |
| 13.9 — Backtest A/B validation report | M | 13.8 | `docs/sprint-artifacts/validation-report-epic13.md` |

Tổng: ~9 stories, ước lượng 1.5-2 tuần dev time tùy spike outcome.

---

## 7. Out-of-scope (Phase 2 và follow-ups)

- **Multi-leg entry** (scaled-in zone, 2-leg 50/50 entry): cần aggregate accounting trong `RiskBasedPositionSizer`, chưa làm.
- **Variant 60/30/10 hoặc 50/25/25:** thêm partial close events. Sau khi Phase 1 stable.
- **Chandelier Exit** trailing alternative: port từ TA-Lib hoặc tự implement. Sau Phase 1 nếu Supertrend whipsaw quá nhiều.
- **Mean-reversion strategies** (Bollinger, RSI, ORB): không adopt scale-out. Có thể thêm time-based exit như follow-up riêng.
- **News blackout window:** `news_blackout_minutes` config. Story riêng.
- **Weekend close logic:** `close_before_weekend: true`. Story riêng.

---

## 8. Acceptance criteria của Phase 1

- [ ] Tất cả unit tests trong §3.1 pass (13 cases)
- [ ] Integration test §3.2 pass với synthetic bars (Nautilus BacktestEngine)
- [ ] Lint sạch: `uv run ruff check services/trading-engine/`
- [ ] Type-clean: không thêm `# type: ignore` mới ngoại trừ Nautilus mixin pattern hiện tại
- [ ] Coverage 80%+ cho new code (`bracket_scale_out.py`, helpers mới trong `base_strategy.py`)
- [ ] Backtest A/B trên ≥ 100 trades XAUUSD M5: scale-out variant không tệ hơn baseline về EV, có cải thiện về 95th percentile winner
- [ ] `configs/firms/ftmo.yaml` cập nhật, smoke test load config thành công
- [ ] `docs/sprint-artifacts/sprint-status.yaml` reflect epic-13 stories
- [ ] Commit messages theo format `Implement spec 13 story 13.x`
- [ ] **Live deployment NOT in Epic 13 scope** — block bởi Epic 14. Document rõ trong validation report rằng tactics được validate trên backtest path, live ship trong Epic 15 sau khi Epic 14 done.

---

## 9. References

- [`docs/research/strategy-tactics-quant-review.md`](./strategy-tactics-quant-review.md) §2.6, §4.1
- `services/trading-engine/src/strategies/bracket_strategy.py:55-218`
- `services/trading-engine/src/strategies/base_strategy.py:261-345`
- `services/trading-engine/src/strategies/supertrend.py`
- `services/trading-engine/src/indicators/supertrend.py`
- `tests/unit/test_bracket_strategy_mixin.py` (existing test pattern)
- `tests/integration/test_bracket_strategies_smoke.py` (e2e pattern)
- `configs/firms/ftmo.yaml` (per-firm overrides)
- CLAUDE.md `.claude/rules/python/coding-style.md`, `python/testing.md`, `common/sandboxed-domain.md`
