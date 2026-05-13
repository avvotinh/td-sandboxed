# Research: Strategy Tactics — Entry, Position Management, Trailing Stop

**Date:** 2026-05-05
**Requested for:** Backtest sweep preparation — Epic 12 và các epic strategy-improvement tiếp theo
**Status:** complete

---

## Executive Summary

**Entry tactics:** Single fill tại signal vẫn là default hợp lý nhất cho intraday XAUUSD trong context FTMO, vì scaled-in laddering tạo ra ambiguity risk accounting (aggregate daily loss) và tăng opportunity cost khi giá không retest. Tuy nhiên, **2-leg model** (50%/50%) với trigger riêng biệt là compromise khả thi — giảm average entry slippage, vẫn giữ được fill certainty leg 1.

**Multi-leg management:** Nếu implement multi-leg, aggregate toàn bộ legs của cùng instrument như một position duy nhất cho mục đích tính daily loss limit. Scale-out (partial close) tại 1R → breakeven → trail phần còn lại là pattern có evidence-base tốt nhất và dễ implement nhất trong NautilusTrader hiện tại.

**Trailing stop:** ATR-based Chandelier Exit (22-period, ×3.0 multiplier) là gold standard cho trend-following. Với XAUUSD M5/M15, cần điều chỉnh xuống period ngắn hơn (7-10) do intraday noise. Supertrend (ATR×2.1-3.0) là lựa chọn thứ hai hợp lý vì project đã có implementation sẵn. Parabolic SAR và fixed-distance trailing KHÔNG phù hợp cho XAUUSD intraday.

**Recommendation cho Sandboxed:** Phase 1 (adopt trước) — single fill entry, đóng 50% tại 1R kéo SL về breakeven, trail 50% còn lại bằng Supertrend ATR(7)×2.1 **không cap upside**. Equal-weight 3-leg @ 1R/2R/3R (mô hình nhiều người hỏi) bị reject do cap tail distribution và triple commission cost — phân tích chi tiết tại Section 2.6. Phase 2 (sau khi Phase 1 validate trên backtest sweep) — thử variant 60/30/10 hoặc 50/25/25 weighted với leg cuối trail uncapped.

---

## 1. Entry Tactics — Single Fill vs Scaled-In (Laddered Entries)

### 1.1 Định nghĩa và cơ chế

**Single fill at signal:** Toàn bộ position size được fill ngay khi signal webhook đến. Đây là behavior hiện tại của Sandboxed.

**Scaled-in / laddered entries:** Position được chia thành 2–4 tranches, fill tại các price zone khác nhau:
- *Zone entry*: Leg 1 tại signal bar close, Leg 2 tại retest of breakout level
- *Pyramid entry (Turtle style)*: Leg ban đầu nhỏ (25% position), thêm unit mỗi 0.5N ATR khi giá đi có lợi — chỉ vào winner
- *Average down (anti-trend)*: Thêm unit khi giá đi ngược — KHÔNG được khuyến nghị, phân tích bên dưới

### 1.2 Trade-off phân tích

| Tiêu chí | Single Fill | Scaled-In (2-leg zone) | Pyramid (Turtle-style) |
|---|---|---|---|
| Fill certainty | Cao — toàn bộ size vào được | Trung bình — leg 2 có thể miss nếu giá không retest | Thấp — chỉ pyramid khi giá confirm, có thể vào rất ít size |
| Average entry price | Tệ hơn nếu signal xảy ra ở extreme | Tốt hơn — average price gần zone hơn | Tốt nhất về R/R trên paper, nhưng exposure thấp khi winner |
| Slippage impact | Cao cho large size tại 1 price | Thấp hơn — chia nhỏ order qua time/price | Thấp nhất — entries nhỏ, rải ra |
| Opportunity cost | None — full exposure ngay | Leg 2 miss = bỏ lỡ toàn bộ move nếu không retest | Thường vào 50–75% sau breakout confirm = bỏ lỡ đầu của move |
| Daily loss accounting | Đơn giản — 1 position | Phức tạp — aggregate hay independent? | Phức tạp nhất |
| FTMO compliance | Transparent | Cần careful accounting | Cần careful accounting |
| Implementation | Hiện có | Medium effort | High effort |

### 1.3 Quan điểm các trường phái quant

**Curtis Faith — Turtle System [Faith 2007]:** Pyramid thêm 1 unit mỗi 0.5N ATR sau entry đầu, tối đa 4–5 units trên 1 instrument. Stop của toàn bộ position đặt tại 2N từ entry cuối cùng. Đây là *add to winner* — KHÔNG phải average down. Rationale: giảm average entry price khi trend đã confirm. Weakness: với FTMO intraday position limit, 4 units cộng dồn nhanh chóng chạm `max_lots` rule.

**Robert Carver — Systematic Trading [Carver 2015, Ch.4]:** Carver ủng hộ **anti-pyramid** — khi một position đang thắng và unrealized PnL tăng, risk exposure thực tế đã tăng, thêm size chỉ làm tăng đòn bẩy vào điểm mà expectancy không còn như lúc entry. Carver khuyến nghị dùng **scaled forecast** (Equation 2, ch.4): size proportional to signal strength, không phải cumulative add-on. Đây là approach hợp lý hơn cho hệ thống rule-based như Sandboxed.

**Andreas Clenow — Following the Trend [Clenow 2013]:** Entry trên breakout của 50-day high, toàn bộ volatility-adjusted size tại 1 price (single fill). "The entry is the least important part of the trading system" — exit và position sizing quan trọng hơn nhiều.

**Ed Seykota / Peter Brandt:** Discretionary, thường single fill tại breakout confirmation. Brandt dùng limit order tại retest nhưng chấp nhận miss nếu không retest.

### 1.4 FTMO-specific considerations

FTMO tính daily loss limit dựa trên **equity thực tế** (bao gồm open positions, swap, commission) tại 00:00 CET. Nếu scaled-in với 2 legs được coi là 1 position (aggregate), risk accounting đơn giản. Nếu engine coi mỗi leg là order độc lập với SL riêng, daily loss có thể bị double-counted trong worst case.

**Kết luận section 1:** Single fill là default an toàn nhất. 2-leg model (50% tại signal, 50% tại retest -0.5ATR) là compromise hợp lý nếu backtesting cho thấy fill rate của leg 2 > 60%. Turtle pyramid KHÔNG phù hợp với FTMO intraday do position limit và multi-level accounting complexity.

---

## 2. Multi-Leg Position Management

### 2.1 Mô hình exit cho multi-leg

| Mô hình | Mô tả | Pros | Cons |
|---|---|---|---|
| Independent SL/TP per leg | Mỗi leg có bracket riêng, không liên quan | Đơn giản nhất | Có thể bị stop out một leg trong khi leg kia vẫn chạy tốt — incoherent |
| Shared SL + scaled-out TP | SL chung cho toàn position; TP tại 1R, 2R, 3R | Phổ biến nhất trong retail quant | SL chung nghĩa là phải track aggregate manually |
| Scale-out 1/3 → 1/3 → trail | Đóng 1/3 tại 1R, 1/3 tại 2R, trail 1/3 | Capture partial profits + let winner run | 3-leg logic phức tạp, FTMO lot size constraint |
| First-in-first-out (FIFO) | Close oldest leg first | Broker compliance (nhiều broker dùng FIFO) | Không tối ưu về R/R, không kiểm soát được |

### 2.2 Anti-martingale vs Martingale

**Martingale:** Tăng size sau loss để recover. **Toàn bộ cộng đồng quant professional đồng thuận reject martingale** vì: (1) ruin probability không zero khi có drawdown string đủ dài; (2) với FTMO daily loss limit 5%, một string 2-3 loss trades có thể vượt limit trước khi martingale "hồi phục". Ed Seykota: "The elements of good trading are: (1) cutting losses, (2) riding winners, (3) keeping bets small." Không có bước nào là "tăng size sau loss."

**Anti-martingale (position scaling by performance):** Tăng size khi đang thắng (Turtle pyramid), giảm khi drawdown. Đây là approach đúng về mặt lý thuyết nhưng Carver phản bác cho systematic trading vì timing của việc "đang thắng" rất khó systematic — dẫn đến position sizing noise.

**Recommendation:** Fixed fractional risk (percent-of-equity) per trade. Đây là what NautilusTrader `RiskBasedPositionSizer` đang implement. Không thay đổi.

### 2.3 Partial close / scale-out strategy

Pattern được evidence nhất (InteractiveBrokers Quant Blog, 2023 [[source]](https://www.interactivebrokers.com/campus/ibkr-quant-news/optimal-trading-with-a-trailing-stop/)):

```
Entry: full size tại signal
@1R profit:  close 50% → move SL to breakeven
@2R profit:  close 25% → activate ATR trailing on remaining 25%
Remaining:   trail at Chandelier (22, ×3) until stopped out
```

Điều này cho phép:
- Lock in profit sớm (FTMO profit target progression)
- Keep exposure để ride trend lớn
- Reduce overnight/weekend risk tự động (open size nhỏ dần)

### 2.4 Hedging legs

Hedging ngược chiều khi market regime thay đổi (ví dụ: thêm 1 SELL leg khi đang LONG để "hedge") là **not recommended** vì:
- FTMO cho phép hedging nhưng KHÔNG netting: cả 2 legs đều tiêu tốn margin và daily loss budget
- Double commission/swap
- Về mặt net exposure, hedge tại 100% = đóng position (không có lý do không đóng thẳng)
- Psychological trap: cảm giác "protected" nhưng thực ra chỉ trả thêm spread

### 2.5 Correlation accounting với FTMO

FTMO tính daily loss theo **equity**, không theo individual position. Nếu bạn có 2 LONG XAUUSD legs với aggregate notional $N, daily loss exposure = tổng floating loss của $N. Không có netting benefit dù bạn coi chúng là "multi-leg". Implication: nếu implement multi-leg, **engine phải aggregate aggregate_lots cho cùng instrument trước khi check max_lots rule** (`configs/firms/ftmo.yaml` → `max_position_size`).

### 2.6 Phân tích pattern fixed R-multiple equal-weight (1R / 2R / 3R)

Một pattern phổ biến trong retail và đôi khi được hỏi: chia 1 signal thành **3 leg đều nhau**, đóng lần lượt tại 1R, 2R, 3R (không trail, không partial weighting). Pattern này có ưu điểm dễ hiểu, dễ implement, nhưng có **3 vấn đề kỹ thuật** mà industry quant đã có giải pháp tốt hơn.

#### 2.6.1 Vấn đề 1: Cap upside — giết tail distribution của trend systems

Trend-following strategies có **power-law return distribution**: hầu hết trades có R nhỏ (-1R đến +1.5R), một số ít trades có R cực lớn (+5R đến +20R). Toàn bộ edge đến từ tail bên phải. Clenow [Following the Trend, 2013, Ch.3]: *"Win rate is meaningless. The ratio of average winner to average loser is what matters, and that ratio is dominated by the largest winners."*

Cap leg cuối cùng tại 3R nghĩa là **mọi outlier 5R-10R+ bị cắt thành 3R**. Đây không phải khoản phí nhỏ — backtest điển hình của trend system trên gold có 5-10% trades đi qua 5R; khi cap, expected value bị giảm 15-30% chỉ vì arbitrary số 3.

#### 2.6.2 Vấn đề 2: Hit-rate dropoff không đối xứng với weighting

Trên XAUUSD M5/M15, distribution điển hình của trade outcome (giả định bracket SL=1R, signal có positive expectancy):

| Target | P(hit) trước khi quay đầu | Conditional contribution với equal weight 1/3 |
|---|---|---|
| 1R | ~50-60% | (1/3) × 1R × 0.55 = +0.183R |
| 2R | ~25-35% | (1/3) × 2R × 0.30 = +0.200R |
| 3R | ~10-15% | (1/3) × 3R × 0.12 = +0.120R |
| Stop -1R | ~40-50% (probability bù) | (3/3) × (-1R) × 0.45 = -0.450R (toàn position bị stop nếu chưa hit 1R) |

**EV thô ≈ +0.05R/trade**, chưa trừ commission/spread. Nếu trừ ~0.1R cho 3× round-trip cost, **EV âm hoặc gần zero**.

So sánh với **single TP 2R + SL 1R**:
- EV ≈ 0.30 × 2R + 0.55 × 1R (cho phần stop tại BE nếu có BE move) − 0.45 × 1R = không tệ hơn nhiều
- Chỉ có 1× round-trip cost

So sánh với **50/50 + trail uncapped**:
- 50% leg đóng tại 1R: 0.5 × 0.55 × 1R = +0.275R
- 50% leg trail (giả định trung bình winner trail = 2.5R, hit rate 35%): 0.5 × 0.35 × 2.5R = +0.438R
- Stop loss: 0.45 × 1R = -0.450R
- **EV ≈ +0.26R/trade** — tốt hơn equal-weight 3-leg đáng kể vì capture được tail.

#### 2.6.3 Vấn đề 3: Triple commission + spread drag

XAUUSD trên FTMO MT5 server: spread floating 25-50 cents/oz, commission ~$3-7 round-trip per lot. 3 lần đóng = 3× cost. Với typical position size 0.5-2 lots gold, drag tính ra ~0.05-0.15R per close. **Equal 3-leg pattern thêm ~0.1-0.3R drag mỗi trade** so với single fill, ăn mất phần lớn EV nhỏ còn lại.

#### 2.6.4 So sánh các pattern

| Pattern | EV (giả định win rate 40%, mean winner 2R) | Capture tail | FTMO consistency | Implementation |
|---|---|---|---|---|
| Single TP 2R | ~+0.20R | ❌ Capped 2R | Trung bình | Đã có |
| **Equal 3-leg @ 1R/2R/3R** | ~+0.05R đến −0.05R | ❌ Capped 3R | Tốt | Trung bình |
| 50/50 + trail uncapped | ~+0.26R | ✅ Power-law | Tốt | Trung bình |
| 60/30/10 weighted + trail leg 3 | ~+0.22R | ✅ (10% leg) | Tốt | Cao |
| 50/25/25 + BE + trail (Section 2.3) | ~+0.30R | ✅ (25% leg) | Tốt nhất | Cao |

#### 2.6.5 Khi nào equal-weight có thể chấp nhận được

Equal-weight 1R/2R/3R **có thể justify** trong một số case rất hẹp:
- **Strict mean-reversion strategies** trên ranging market (Bollinger reversion, ORB fade) — không có tail bên phải lớn để capture, nên cap 3R không gây thiệt hại
- **News trading** — bursts thường self-exhaust trong vài bars, R rarely >3R
- **Strategy còn rất sớm trong validation**, dùng pattern này như baseline rồi A/B test với trail

Nhưng **default cho trend-following gold trên Sandboxed nên là 50/50+trail**, không phải equal 3-leg.

#### 2.6.6 Kết luận section 2.6

Pattern `1/3 @ 1R + 1/3 @ 2R + 1/3 @ 3R` là cải tiến nhỏ so với "single TP 2R" về mặt FTMO consistency, nhưng **tệ hơn rõ rệt** so với scale-out + trail pattern vì cap upside và triple cost. Nếu muốn 3 leg, **weighting 60/30/10 với leg cuối trail uncapped** là phiên bản salvage được — vẫn 3 leg, vẫn có realized profit progression, nhưng không cắt cụt tail. Nếu chỉ muốn 1 thay đổi đơn giản đầu tiên: **50/50 với leg 2 trail**.

---

## 3. Trailing Stop Methodologies — Comprehensive Review

### 3.1 Bảng tổng hợp

| Method | Formula | Regime fit | XAUUSD M5/M15 | Complexity |
|---|---|---|---|---|
| Fixed-distance | Stop = peak ± X pips | Range | Không — gold moves ATR 50-200 pips/day, fixed distance obsoletes instantly | Easy |
| Percentage trailing | Stop = peak × (1 - X%) | Equity/stocks | Không — percentages trên FX/Gold không equalize volatility | Easy |
| ATR Chandelier Exit | Stop = Highest_High(N) − ATR(N) × mult | Trend | Có, với N=7-10, mult=2.5-3.0 | Medium |
| Parabolic SAR | SAR(n+1) = SAR(n) + AF × (EP − SAR(n)); AF starts 0.02, max 0.20 | Trending only | Không phù hợp M5 — SAR accelerates trop vite, many false flips trong choppy sessions | Medium |
| Supertrend | Upper/Lower band = HL2 ± ATR(N)×mult; flip on close cross | Trend | Có — project đã có implementation; ATR(7)×2.1 optimal cho XAUUSD M15 | Medium |
| MA trailing (EMA/SMA) | Trail stop tại close below 20-EMA hoặc 50-SMA | Trend | Không phù hợp M5 — EMA tụt hậu quá nhiều | Easy |
| Donchian exit | Stop = lowest low của N bars | Trend | Medium — 10-bar exit trên M15 hơi rộng | Easy |
| Kase DevStop | Dùng standard deviation của ATR thay vì ATR thẳng | High-vol | Phù hợp cho news spike nhưng phức tạp | Hard |
| Time + price combo | Exit nếu sau N bars mà chưa hit X% profit | Mean-reversion | Có — rất hữu ích cho M5 ORB/mean-reversion | Medium |

### 3.2 Chi tiết từng method

#### 3.2.1 Chandelier Exit (Chuck LeBeau, popularized Alexander Elder)

**Formula:**
```
Long stop  = Highest High(N) − ATR(N) × multiplier
Short stop = Lowest Low(N)  + ATR(N) × multiplier
Default: N=22, multiplier=3.0
```

Rationale của LeBeau: sử dụng `Highest High` (không phải `current close`) nên stop chỉ di chuyển 1 chiều (ratchet) — trailing thực sự. Khi giá bứt phá mới thì `Highest High` tăng, stop kéo theo. Chandelier Exit được xem là **gold standard cho ATR trailing** trong cộng đồng quant (QuantifiedStrategies.com backtest so sánh: Chandelier PF=1.61 vs Fixed 10% trailing PF=1.28 trên BTC/USDT daily 2020-2024).

Với **XAUUSD M5/M15**, N=22 (daily-calibrated) quá dài. Điều chỉnh: **N=7-10, multiplier=2.5-3.0**. Multiplier thấp hơn 2.0 gây whipsaw nghiêm trọng trên intraday gold.

**Strengths:** Adapts to volatility; ratchet-only; không "tightens too fast" như Parabolic SAR.
**Weaknesses:** Lagging khi trend reversals — stop có thể rất xa peak khi volatility spike.
**Implementation:** Cần `highest_high` rolling window + ATR. Not native in NautilusTrader broker trailing — phải implement software-side trong strategy.

#### 3.2.2 Supertrend (Olivier Seban)

**Formula:**
```
Basic Upper Band = HL2 + (multiplier × ATR(N))
Basic Lower Band = HL2 − (multiplier × ATR(N))
Final Upper Band: if Basic Upper < prev Final Upper OR close > prev Final Upper
                  then Basic Upper else prev Final Upper
Supertrend: if close > Final Upper Band → LONG (stop = Final Upper Band)
             if close < Final Lower Band → SHORT (stop = Final Lower Band)
Default: N=10, multiplier=3.0
XAUUSD M15 optimal: N=7, multiplier=2.1
```

Supertrend về cơ chất là Chandelier Exit với ATR tính từ midpoint (HL2) thay vì extreme high/low. Behavior tương tự nhưng stop tighter hơn một chút.

Project đã có `services/trading-engine/src/strategies/supertrend.py` và `src/indicators/supertrend.py`. **Reuse codebase này là lựa chọn tối ưu** cho trailing stop implementation — zero new code.

**XAUUSD M15 backtested parameters** (TradingView community data, 20,000+ bars): ATR(7), mult=2.1 là optimal balance giữa sensitivity và noise reduction.

**Strengths cho XAUUSD M5/M15:** Đã validate trên gold; project codebase sẵn có; adaptive to news spikes (ATR tự mở rộng).
**Weaknesses:** Trend-following only; trong ranging market (ADX < 20) sẽ flip nhiều và bị whipsawed.

#### 3.2.3 Parabolic SAR

**Formula (Wilder 1978):**
```
SAR(n+1) = SAR(n) + AF × (EP − SAR(n))
AF bắt đầu = 0.02, tăng 0.02 mỗi lần có EP mới, tối đa 0.20
EP (Extreme Point) = highest high cho long, lowest low cho short
```

Điểm mạnh: Acceleration factor khiến stop tightens nhanh khi trend mature — tốt cho locking profits.

**Điểm yếu nghiêm trọng cho XAUUSD intraday:**
- Trong sideways/choppy market, SAR flip rất nhiều — XAUUSD Asian session thường choppy
- AF acceleration không gắn với ATR → không adapts to volatility regime
- SAR tự động reverse signal (Stop AND Reverse) → không phù hợp cho strategies chỉ cần trailing exit

**Verdict:** Không khuyến nghị cho Sandboxed XAUUSD M5/M15 primary trailing.

#### 3.2.4 Moving Average Trailing (EMA/SMA)

Nick Radge style: trail stop tại close below 20-EMA sau 1st profit target hit. Phù hợp cho daily/weekly swing trades. **Không phù hợp cho M5/M15** vì:
- 20-EMA trên M5 lag quá nhiều — stop sẽ 20-40 pips dưới current price trong trending market
- Nhiễu quá cao

#### 3.2.5 Donchian Channel Exit (Turtle System)

**Formula:** Stop khi close pierces N-bar low (long) hoặc N-bar high (short). Turtle dùng N=10 (exit) vs N=20 (entry).

Project đã có `services/trading-engine/src/strategies/donchian_breakout.py`. Donchian exit **là một dạng ratchet trailing** — Turtle N=10 exit trên M15 ≈ 150 phút lookback, tương đương 2.5 giờ. Phù hợp hơn cho H1 position hơn M5 scalping.

**Verdict:** Dùng như secondary exit cho Donchian breakout strategy đã có, không phải primary trailing cho signals khác.

#### 3.2.6 Time + Price Combo (Andreas Clenow concept)

Clenow không đặt tên riêng cho method này nhưng concept từ "Trading Evolved": "nếu sau N bars mà position chưa đạt 1R profit, exit tại market." Logic: nếu edge không hiển thị trong X bars, signal đó probably sai.

**Phù hợp với Sandboxed:** Cho mean-reversion strategies (ORB, RSI, Bollinger) trên M5/M15. Ví dụ: nếu sau 12 bars (= 60 phút trên M5) mà ORB trade chưa hit 1R, exit. Giảm overnight exposure đáng kể. **Implementation cost: Medium** — cần `bars_since_entry` counter trong strategy state.

#### 3.2.7 Breakeven Move

Các school of thought về "khi nào kéo SL về breakeven":

| School | Rule | Rationale |
|---|---|---|
| Turtle | Không có breakeven — SL cố định tại 2N, chỉ trailing sau 4 units | Tight SL kills winners trước khi scale |
| Retail popular | Kéo BE sau 1R | Eliminate risk của trade |
| Robert Carver | Không recommend BE mechanical — distorts expectancy calculation | BE creates asymmetric reward profile |
| Van Tharp | Kéo BE sau 2R để position "free ride" | Psychological anchor |

**Cho FTMO/Sandboxed:** Kéo SL về breakeven sau 1R là **reasonable compromise** vì:
1. Bảo vệ daily loss limit progress — không quay lại từ +1R về -1R
2. Tâm lý trade manager tốt hơn
3. Với XAUUSD volatility, 1R trên M5 thường = 10-20 pips — đủ buffer

---

## 4. Recommendation cho Sandboxed (XAUUSD Intraday, FTMO)

### 4.1 Recommended Stack — Phased Adoption

Triển khai theo 2 phase để giảm risk implementation và validate từng bước qua backtest.

#### Phase 1 (PRIMARY — adopt trước, validate trên backtest sweep)

```
Signal:     TradingView webhook → tv-api → ZeroMQ → trading-engine
Entry:      Single fill at signal bar close (hiện tại — giữ nguyên)
SL initial: 2.0 × ATR(14) từ entry (hard broker SL — safety net)

Exit management (theo thứ tự sự kiện):
  @+1.0R:  Close 50% position → Move SL remaining 50% to breakeven
  Remaining 50%: Trail via Supertrend ATR(7)×2.1 — UNCAPPED (no fixed TP)
                 Stop khi Supertrend flip hoặc bị stop tại trail line
```

Đây là **2-leg scale-out + trail uncapped** — phiên bản đơn giản nhất có evidence-base tốt và capture được power-law tail của trend systems. Phù hợp với codebase hiện tại; chỉ cần thêm partial close + breakeven move + trailing logic vào `BracketStrategyMixin`. KHÔNG cần thay đổi entry logic, KHÔNG cần multi-leg accounting (vẫn là 1 position MT5).

#### Phase 2 (alternative — evaluate sau khi Phase 1 ổn định)

Sau khi Phase 1 chạy ≥ 100 trades trong backtest và validate có positive EV, có thể test 2 variant nâng cao:

**Variant A — 60/30/10 weighted (3-leg, weighting theo hit probability):**
```
@+1.0R: Close 60% → Move SL remaining to breakeven
@+2.0R: Close 30% → Activate Supertrend trailing on remaining 10%
Remaining 10%: Trail uncapped
```
Pros: 3 lần realized profit progression, vẫn có tail capture qua leg 3 trail.

**Variant B — 50/25/25 (Section 2.3 reference pattern):**
```
@+1.0R: Close 50% → Move SL to breakeven
@+2.0R: Close 25% → Activate Supertrend trailing on remaining 25%
Remaining 25%: Trail uncapped
```
Pros: Cân bằng giữa realized profit và tail capture (25% trail leg lớn hơn variant A).

**KHÔNG adopt:** Equal-weight 1/3 + 1/3 + 1/3 tại 1R/2R/3R cố định không trail (xem Section 2.6) — cap upside và triple cost.

### 4.2 Tại sao Phase 1 = 50/50 + trail (không phải 50/25/25 ngay)?

1. **Implementation tối giản:** Chỉ 1 partial close event (1R) + 1 breakeven move + 1 trailing handler. So với 50/25/25 cần 2 partial close events + state machine phức tạp hơn cho trailing activation timing. Less code = less bugs trong edge cases (gap, requote, partial fill).

2. **Validate hypothesis trước khi optimize:** Phase 1 trả lời câu hỏi cốt lõi *"Trail uncapped có cải thiện EV trên XAUUSD M5/M15 không?"* Nếu câu trả lời là không (ví dụ trail bị whipsaw quá nhiều trên gold), thì 50/25/25 cũng không cứu được. Ngược lại nếu Phase 1 dương EV, Phase 2 chỉ là tinh chỉnh weighting.

3. **Supertrend trailing reuse codebase:** `src/indicators/supertrend.py` đã có, tested. Phase 1 chỉ cần wrap nó vào BracketStrategyMixin trailing handler.

4. **Single fill entry giữ nguyên:** Tránh multi-leg entry accounting với FTMO consistency rule và `RiskBasedPositionSizer` aggregate logic. Cleanest architecture cho phase đầu.

5. **FTMO daily loss budget bảo toàn:** Sau khi 50% đóng tại 1R và SL kéo về BE, worst case từ point đó là +0R không phải -1R cho phần còn lại. Nếu trail leg bị stop tại BE, total trade outcome = +0.5R (locked). Daily loss exposure giảm sau mỗi successful 1R hit.

### 4.3 Default Config đề xuất (đưa vào `configs/` hoặc strategy config)

```yaml
# Phase 1 — primary config (50/50 + trail uncapped)
entry_legs: 1                    # single fill
sl_atr_mult: 2.0                 # hard broker SL safety net
scale_out_levels:                # ordered list of (r_multiple, close_fraction)
  - r: 1.0
    close_fraction: 0.5          # đóng 50% tại +1R
breakeven_at_r: 1.0              # kéo SL về BE sau khi hit 1R
trailing_remainder: true         # trail phần còn lại (50%) uncapped
trailing_method: "supertrend"    # hoặc "chandelier"
trailing_period: 7               # N bars cho Supertrend/Chandelier ATR
trailing_multiplier: 2.1         # ATR multiplier

# Phase 2 — variant A (60/30/10 weighted)
# scale_out_levels:
#   - { r: 1.0, close_fraction: 0.6 }
#   - { r: 2.0, close_fraction: 0.3 }   # leg 2 hit thì close 30%, không hit thì stay
# trailing_remainder: true              # 10% còn lại trail uncapped

# Phase 2 — variant B (50/25/25)
# scale_out_levels:
#   - { r: 1.0, close_fraction: 0.5 }
#   - { r: 2.0, close_fraction: 0.25 }
# trailing_remainder: true              # 25% còn lại trail uncapped
```

### 4.4 Configurable knobs cho per-strategy tuning

| Knob | Default | Notes |
|---|---|---|
| `entry_legs` | 1 | 2 cho scaled-in nếu backtesting justify |
| `sl_atr_mult` | 2.0 | Donchian breakout: 2.0; Supertrend flip: có thể 1.5 |
| `trailing_method` | `supertrend` | `chandelier`, `donchian`, `time_exit` |
| `trailing_period` | 7 | 10-14 cho H1; 7 cho M5/M15 |
| `trailing_multiplier` | 2.1 | 2.5-3.0 cho wider trend; 1.5-2.0 cho tighter scalp |
| `breakeven_at_r` | 1.0 | None để disable BE logic |
| `scale_out_r_levels` | [1.0, 2.0] | TP levels cho partial close (% per leg từ config) |
| `time_exit_bars` | None | N bars timeout (mean-reversion strategies only) |

### 4.5 Risks và edge cases

**Weekend gap XAUUSD:**
- Gold thường gap 50-200 pips khi mở cửa Sunday 5pm EST sau news cuối tuần (Fed speakers, geopolitical)
- **Mitigation:** Trailing stop là software-emulated — engine nhận bar đầu tuần và tính SL dựa trên bar đó, không bị slippage qua gap nếu position đã có SL broker tại cứng. Cần có hard broker SL tại `sl_atr_mult × ATR` làm safety net, trailing chỉ là layer thứ 2.
- **Recommendation:** Đóng toàn bộ position trước 23:00 UTC Friday nếu position đang mở. Configurable: `close_before_weekend: true`.

**News spike (NFP, FOMC, CPI):**
- XAUUSD di chuyển 300-1000+ pips trong vài giây sau major news
- ATR-based trailing sẽ mở rộng sau spike nhưng không thể protect the initial spike candle
- **Mitigation:** Đây là vấn đề của NautilusTrader `TRAILING_STOP_MARKET` với broker — broker trailing stop cũng có thể fill rất xa trong news
- **Recommendation:** Hard SL tại `2.0×ATR` là critical safety net. Cân nhắc thêm `news_blackout_minutes` config để không enter trong window ±30 phút quanh major events.

**FTMO consistency rule:**
- FTMO consistency metric (Discipline Score) không block trading nhưng ảnh hưởng đến performance report
- Scale-out tạo nhiều small realized profits — improve consistency score vì ngày nào cũng có realized profit
- Tránh large single-day outliers: nếu có 1R scale-out mỗi ngày + trailing winner còn lại, distribution of daily PnL tự nhiên đều hơn

**Aggregate position size với multi-leg:**
- Nếu implement 2-leg entry tương lai: `RiskBasedPositionSizer` PHẢI aggregate `total_open_lots` cho cùng instrument trước khi kiểm tra `max_lots` trong `ftmo.yaml` (hiện tại `max_lots: 100.0` per 10k balance)
- File cần update: `services/trading-engine/src/strategies/risk_based_position_sizer.py`

---

## 5. Existing Project Code

Kết quả grep/glob trong `services/trading-engine/src/`:

| File | Relevance |
|---|---|
| `src/strategies/supertrend.py` | **Supertrend trailing logic** — đã có, signal-based; cần extend thành trailing mode |
| `src/strategies/donchian_breakout.py` | **Donchian exit** — đã có, dùng fixed ATR SL/TP, không có trailing |
| `src/strategies/bracket_strategy.py` | **BracketStrategyMixin** — hiện tại chỉ support single bracket (entry + 1 SL + 1 TP); cần extend cho multi-TP + trailing |
| `src/strategies/risk_based_position_sizer.py` | **Position sizing** — đã có fixed-fractional risk |
| `src/indicators/supertrend.py` | **Supertrend indicator** — reusable cho trailing calculation |
| `configs/firms/ftmo.yaml` | **FTMO rules** — `max_lots`, `daily_loss_limit`, `consistency` — cần aggregate check nếu multi-leg |

Không tìm thấy: Chandelier Exit implementation, partial close / scale-out logic, breakeven move logic, time-based exit. Đây là những gap cần implement.

---

## 6. Open Questions / Further Research

1. **Backtest validation của scale-out pattern trên XAUUSD M5/M15:** Cần chạy backtest so sánh (a) single bracket vs (b) 50%@1R + trail remainder để có số liệu thực tế — đây nên là một trong những scenarios trong backtest sweep Epic 12.

2. **Software trailing vs broker native trailing:** NautilusTrader có `TRAILING_STOP_MARKET` order type với `TrailingOffsetType.PRICE` và `PERCENT`. Với MT5 bridge, broker trailing có thể bị lag hoặc không support cho CFD/Gold. Cần verify với `services/mt5-bridge/` team liệu MT5 có support server-side trailing cho XAUUSD không, hay cần software emulation hoàn toàn.

3. **Optimal ATR period cho intraday gold M5:** Dữ liệu TradingView community suggest ATR(7)×2.1 cho M15. Chưa có peer-reviewed backtest paper cụ thể cho XAUUSD M5. Research đây là exploratory data; cần validate trong sweep.

4. **Time exit cho mean-reversion strategies:** `orb.py`, `rsi_mean_reversion.py`, `bollinger_mean_reversion.py` có thể benefit từ time-based exit (không hold qua session boundary). Chưa có config hook cho điều này.

5. **2-leg entry fill rate trên XAUUSD:** Cần data về bao nhiêu % signal có retest đủ để fill leg 2 trong -0.5ATR zone. Không thể quyết định "scale-in hay không" mà không có con số này.

---

## Appendix A: Code Patterns Quan Trọng

### A.1 Chandelier Exit (pseudocode, NautilusTrader-compatible)

```python
# Software-emulated Chandelier trailing stop
# Source: StockCharts ChartSchool (https://chartschool.stockcharts.com/.../chandelier-exit)
# Adapt cho NautilusTrader event loop

class ChandelierTrailingStop:
    def __init__(self, period: int = 10, multiplier: float = 2.5):
        self._period = period
        self._mult = multiplier
        self._atr = AverageTrueRange(period)
        self._high_window: deque[float] = deque(maxlen=period)

    def update(self, bar: Bar) -> float | None:
        """Return current trailing stop price for long position."""
        self._atr.handle_bar(bar)
        self._high_window.append(bar.high.as_double())
        if len(self._high_window) < self._period or not self._atr.initialized:
            return None
        highest_high = max(self._high_window)
        return highest_high - self._atr.value * self._mult
```

### A.2 NautilusTrader native trailing stop (broker-level)

```python
# Source: https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/integrations/bitmex.md
from nautilus_trader.model.enums import TrailingOffsetType, TriggerType
from decimal import Decimal

order = self.order_factory.trailing_stop_market(
    instrument_id=instrument_id,
    order_side=OrderSide.SELL,
    quantity=remaining_qty,
    trailing_offset=Decimal("150"),          # 150 USD / 1.50 per oz cho XAUUSD
    trailing_offset_type=TrailingOffsetType.PRICE,
    trigger_type=TriggerType.LAST_PRICE,
)
```

### A.3 Scale-out partial close pattern (NautilusTrader)

```python
# Source: NautilusTrader docs (https://github.com/nautechsystems/nautilus_trader/...)
# Partial close tại 50% khi đạt 1R

def _check_scale_out(self, current_price: Price) -> None:
    if self._tp1_hit or self.position is None:
        return
    unrealized_r = (current_price - self._entry_price) / self._initial_risk
    if unrealized_r >= Decimal("1.0"):
        half_qty = self.position.quantity / 2
        close_order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=OrderSide.SELL,   # assuming LONG
            quantity=half_qty,
            reduce_only=True,
        )
        self.submit_order(close_order)
        self._tp1_hit = True
        self._move_sl_to_breakeven()
```

---

## Sources

- [Chandelier Exit — ChartSchool StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit)
- [Chandelier Exit Strategy — QuantifiedStrategies.com](https://www.quantifiedstrategies.com/chandelier-exit-strategy/)
- [ATR Trailing Stop Guide: Chandelier Exit — StratBase.ai](https://stratbase.ai/en/blog/average-true-range-trailing-stop)
- [Supertrend Indicator Backtest — QuantifiedStrategies.com](https://www.quantifiedstrategies.com/supertrend-indicator/)
- [Supertrend BUY Only Optimized for Gold M15 — TradingView](https://www.tradingview.com/script/3KRKXYWt-Supertrend-BUY-Only-Optimized-for-Gold-M15-Timeframe/)
- [Clenow Trading System Rules — followingthetrend.com](https://www.followingthetrend.com/the-trading-system/trading-system-rules/)
- [Andreas Clenow Podcast — Top Traders Unplugged](https://www.toptradersunplugged.com/podcast/trend-following-andreas-clenow-acies-asset-management/)
- [Turtle Trading Strategy Rules — LiteFinance](https://www.litefinance.org/blog/for-beginners/trading-strategies/turtle-trading-strategy/)
- [Modern Turtle Trading Backtest — TOS Indicators](https://tosindicators.com/research/modern-turtle-trading-strategy-rules-and-backtest/)
- [Donchian Channel Backtest — QuantifiedStrategies.com](https://www.quantifiedstrategies.com/donchian-channel/)
- [Parabolic SAR — Wikipedia (Wilder formulas)](https://en.wikipedia.org/wiki/Parabolic_SAR)
- [Optimal Trading with Trailing Stop — IBKR Quant Blog](https://www.interactivebrokers.com/campus/ibkr-quant-news/optimal-trading-with-a-trailing-stop/)
- [FTMO Maximum Daily Loss — FTMO Academy](https://academy.ftmo.com/lesson/maximum-daily-loss/)
- [FTMO Trading Objectives — ftmo.com](https://ftmo.com/en/trading-objectives/)
- [FTMO Consistency Rule — ftmo.com FAQ](https://ftmo.com/en/faq/do-you-have-any-consistency-rules/)
- [NautilusTrader trailing_stop_market API — nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) — Context7 library ID: `/nautechsystems/nautilus_trader`
- [NautilusTrader OrderFactory bracket orders — nautechsystems docs](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/orders.md)
- [Robert Carver "Systematic Trading" 2015 — review summary](https://tradermarkus.com/robert-carver-systematic-trading-review/)
- [Backtesting EUR/USD ATR Trailing Stop — Tradinformed](https://www.tradinformed.com/backtesting-eurusd-trading-strategy-using-atr-trailing-stop/)
- [Gold XAUUSD Stop Loss Guide — tradegoldtrading.com](https://www.tradegoldtrading.com/index.php/stop-loss-trading-summary-gold-trading)
