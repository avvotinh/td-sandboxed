# Phân tích entry / exit / trailing — active roster (XAUUSD M5/M15)

**Date:** 2026-07-05
**Input cho:** Track 5.1 (redesign plan) — cải thiện profit qua thiết kế tín hiệu, KHÔNG sweep
**Evidence:** baseline 2y sizing-đúng (`epic-12a-rerun-2y-verdict.md`), A/B scale-out Epic 13
(`epic13-donchian-scaleout-results.md`, R-based stats scale-invariant nên vẫn valid),
quant review (`strategy-tactics-quant-review.md`), Track 3 research (2 docs 2026-07-05).
Code refs đọc trực tiếp từ `src/strategies/` @ main (post PR #5).

---

## 0. Khung chẩn đoán

Baseline 2y (risk 0.5%/trade, không filter, không scale-out, không regime gate):

| | Sharpe M5/M15 | PF M5/M15 | Trades M5/M15 | maxDD M5/M15 |
|---|---|---|---|---|
| donchian_breakout | +0.06 / +0.03 | 1.034 / 1.015 | 4445 / 1685 | 40% / 30% |
| supertrend | −0.11 / −0.03 | 0.921 / 0.969 | 3676 / 1198 | 68% / 24% |
| mean_reversion | −0.22 / −0.15 | 0.886 / 0.927 | 11119 / 3836 | **98% / 64%** |

Chẩn đoán tổng: **vấn đề số 1 là khối lượng entry chất lượng thấp, không phải cấu trúc
exit**. PF cụm quanh 1.0 nghĩa là mỗi edge nhỏ đang bị chi phí (spread+commission per-lot
thật) và chuỗi entry trong chop nuốt sạch. Bằng chứng đối chứng: orb — strategy duy nhất
có session filter — chỉ 517 trades và DD 14.3% (thấp nhất toàn bảng). Exit/trailing là
đòn bẩy thứ hai, đã có evidence A/B định lượng, và **hiệu ứng phụ thuộc strategy ×
timeframe** (không áp dụng đồng loạt được).

---

## 1. ENTRY — hiện trạng và lỗ hổng

### 1.1 supertrend — flip-only, không đo trend strength

Hiện trạng (`supertrend.py:137-156`): vào lệnh **chỉ tại bar flip** của
`Supertrend(10, 3.0)`; có reversal (flip ngược → close rồi vào chiều mới cùng bar);
suppression duy nhất là `is_flat`.

Lỗ hổng:
- **Không phân biệt flip-trong-trend và flip-trong-chop.** 3676 flips/2y trên M5
  (~7/ngày) với WR 32.9%, PF 0.92 — đa số flip là nhiễu ranging. Flip vừa là entry vừa
  là exit (reversal) nên chuỗi whipsaw bị tính phí 2 đầu.
- **ATR bên trong Supertrend dùng MA mặc định SIMPLE của Nautilus, không phải Wilder**
  (indicator constructor không truyền `ma_type`). Supertrend chuẩn dùng RMA/Wilder —
  SMA-ATR phản ứng nhanh hơn → band giật hơn → nhiều flip hơn. Đây là sai lệch fidelity
  so với spec indicator, sửa không tính là sweep.

### 1.2 donchian_breakout — entry đúng chuẩn, nhưng churn khi re-entry

Hiện trạng (`donchian_breakout.py:128-148`): close vượt band 20-bar **của bar trước**
(chống look-ahead đúng); không reversal; không cooldown.

Lỗ hổng:
- **Re-entry ngay sau khi đóng lệnh nếu điều kiện breakout còn giữ.** Signal bắn BUY mỗi
  bar close còn nằm trên prev_upper; sau khi SL/TP đóng vị thế, bar đủ điều kiện kế tiếp
  vào lại ngay → churn phí trên move kéo dài, đặc biệt M5 (4445 trades). Thiếu semantics
  "crossing" (vào 1 lần mỗi episode breakout — yêu cầu close bar trước nằm TRONG channel).
- **Không đo chất lượng breakout**: break 0.01×ATR và break quyết đoán được đối xử như
  nhau; trong chop, mép channel bị xuyên liên tục. ADX gate xử lý đúng failure mode này.

### 1.3 mean_reversion — bắt dao rơi trong trend là nguồn DD 98%

Hiện trạng (`mean_reversion.py:114-158`): BUY khi `close < BB_lower` AND `RSI ≤ 0.3`
(zone tĩnh, cùng bar); exit middle-band ưu tiên trước entry; không reversal, không cooldown.

Lỗ hổng (nghiêm trọng nhất roster):
- **Zone check tĩnh khi giá đang NGOÀI band = counter-trend knife-catching.** Trong
  trend mạnh (gold 2024–2025), giá trượt dọc band, RSI ghim vùng cực trị → điều kiện
  luôn thỏa → cứ đóng lệnh (SL 1×ATR) là vào lại ngay. 11k trades M5, DD 98% = chết vì
  ngàn nhát cắt cùng chiều. Chuỗi này chỉ dừng khi... hết 2 năm data.
- **Phòng tuyến thiết kế là regime gate RANGING — nhưng baseline chạy OFF** (RegimeActor
  Epic 15 default-OFF). Số baseline của MR là floor, không phải ước lượng; Track 4.3
  ablation là phép thử thật.
- **Không có time-stop**: thesis mean-reversion có thời hạn — nếu không revert trong N
  bars thì thesis sai, nhưng position được giữ đến khi chạm middle/SL/TP.

---

## 2. EXIT — hiện trạng và lỗ hổng

Cấu trúc chung (`bracket_strategy.py:346-421`): bracket MARKET entry + STOP_MARKET SL +
LIMIT TP, giá tham chiếu = close bar trước khi fill; SL/TP tính từ ATR(14)×mult; **không
bao giờ recompute** sau entry (trừ scale-out path sửa SL).

| Strategy | SL/TP | Exit ngoài bracket | Nhận xét |
|---|---|---|---|
| supertrend | 1.5 / 3.0 (2R) | reversal khi flip ngược | winner thường bị cắt bởi flip trước khi chạm TP; loser ăn đủ SL → asymmetry ngược |
| donchian | 2.0 / 4.0 (2R) | **không có** | TP cứng 4×ATR **cap mất fat tail** — p95 winner chỉ 1.94R (M5 baseline); breakout sống nhờ tail |
| mean_reversion | 1.0 / 2.0 (2R) | CLOSE tại middle band | middle-band exit đúng sách; thiếu time-stop |

Điểm cần lưu ý thêm:
- Donchian không có cả exit tín hiệu đối xứng (Turtle dùng channel 10-bar ngược chiều làm
  exit) — hiện chỉ SL/TP tĩnh.
- `safety_tp_atr_mult` (default 6.0) **được declare + validate nhưng KHÔNG được tiêu thụ
  ở bất kỳ đâu** — dead config field; "anti-runaway cap" thực tế là operator tự nâng
  `tp_atr_mult=6.0` trong overlay. Cần fix (consume hoặc xóa) để config không đánh lừa.

---

## 3. TRAILING — hiện trạng, evidence, và gaps

Hiện trạng (`bracket_scale_out.py`): chỉ MỘT method — Supertrend trail ATR(7)×2.1,
tighten-only, update mỗi bar. State machine: partial close 50% tại +1R → SL về BE (đúng
giá entry, cùng bar do invariant `breakeven_at_r ≤ scale_out_r_trigger`) → kích hoạt
trail. **Trailing bị buộc chặt vào scale-out** (`trailing_enabled` requires
`scale_out_enabled`) — không thể trail full position mà không partial close.
`mean_reversion` không compose mixin → mọi key scale-out trên nó là inert (đúng thiết kế).

Evidence A/B (R-based, vẫn valid sau sizing fix):

| Combo | ΔEV | Cơ chế |
|---|---|---|
| Supertrend M5 / M15 | **+52% / +62%** | BE protection > chi phí mất tail — hợp signal whipsaw |
| Donchian M5 | **−91%** | median winner sụp 1.92R→1.26R: "half-at-1R + half-at-BE" — M5 noise dễ retrace về BE |
| Donchian M15 | **+91%** | tail capture p95 1.97R→3.37R — trend M15 đủ chậm cho trail sống |

Kết luận trailing: **tactic đúng nhưng phải gate theo strategy × timeframe** — Donchian
M15 ON / M5 OFF; Supertrend ON cả 2 (nhưng lưu ý +52% của EV âm vẫn là EV âm: −0.282 →
−0.134 — tactic không cứu được entry tồi, chỉ khuếch đại entry tốt).

Gaps kỹ thuật:
1. BE đặt **đúng giá entry** — sau spread/commission, stop-tại-BE thực chất là lỗ nhỏ;
   chuẩn thực hành là BE + phí (offset nhỏ). Ảnh hưởng lớn ở M5 nơi BE bị tag thường xuyên.
2. Không có biến thể **trail-only** (không partial) — với Donchian M5, "giữ nguyên full
   position + trail sau 2R" là hình dạng chưa test được vì config invariant chặn.
3. `_modify_sl` live path raise `NotImplementedError` (ZmqExecutionClient) — trailing
   hiện là backtest-only; Epic 14 phải gỡ trước khi live.
4. Docstring mixin còn ghi trail là "no-op stub" — stale, đã implement đầy đủ.

---

### 3.5 Trailing thay thế — đánh giá theo failure mode đã đo

Phân rã "trailing tốt hơn" thành 4 tầng, xếp theo impact kỳ vọng:

1. **Chính sách BE (tầng có bằng chứng mạnh nhất):** thất bại đo được ở Donchian M5
   không phải do đường trail — remainder chết tại BE-đúng-giá-entry TRƯỚC khi trail kịp
   kích hoạt. Sửa: BE + fee offset (từ ContractSpec), và test biến thể **trail-only
   không partial/không BE** (giữ SL gốc 2×ATR đến khi trail line vượt qua nó — hình dạng
   Turtle: không BE cơ học, đúng trường phái Carver "BE làm méo expectancy").
   Cần gỡ invariant `trailing_enabled requires scale_out_enabled` (Phase-1 coupling là
   tiện implementation, không phải kết luận evidence).
2. **Đường trail thay thế đáng test — Chandelier Exit** (`Highest High(N) − ATR(N)×mult`,
   N=7–10, mult=2.5–3.0 intraday gold): khác Supertrend-trail (neo HL2) ở chỗ neo vào
   extreme → sau impulse bar, stop treo từ đỉnh mới, ít bị retrace tag hơn. Đây là
   "gold standard" ATR-trailing theo quant review §3.2.1 (external backtest PF 1.61 vs
   1.28 fixed-trailing); config surface đã dự trù `trailing_method: "chandelier"`
   (§4.4). Cost: ~40 dòng indicator + mở validation. Defaults canonical, không sweep.
3. **Exit cấu trúc cho donchian — Turtle 10-bar channel exit**: thoát tại extreme
   10-bar ngược chiều (entry 20/exit 10 là cặp canonical). Uncap tail không cần partial
   close, chịu noise M5 tốt hơn BE+tight-trail vì stop lùi theo cấu trúc giá thay vì
   theo band ATR. Native với chính indicator Donchian đang có.
4. **Loại bỏ khỏi bàn**: Parabolic SAR (flip liên tục trong chop Asian session), MA-trail
   (lag M5), fixed-distance/percentage (không equalize volatility gold), Kase DevStop
   (phức tạp, defer), Nautilus native TRAILING_STOP_MARKET (offset chỉ price/bp/ticks
   không ATR-aware; live path MT5 chưa có — software trail vẫn đúng hướng).

Ma trận đề xuất theo strategy: supertrend giữ supertrend-trail (+52/62% đã đo);
donchian M15 A/B ba ứng viên (supertrend-trail hiện tại vs chandelier vs turtle-exit,
mỗi cái thêm biến thể trail-only); donchian M5 mặc định KHÔNG trail trừ khi
trail-only-no-BE chứng minh ngược; mean_reversion không trail (time-stop + middle-band
là đúng hình dạng).

## 4. Khuyến nghị — xếp theo (impact × evidence) / cost, tuân thủ no-sweep

**Nhóm A — Entry filters (đòn bẩy lớn nhất, làm trước):**
1. **ADX(14) ≥ 25 gate** cho supertrend + donchian tại seam `generate_signal`
   (индicator `src/indicators/adx.py` Wilder-correct có sẵn, cùng threshold regime
   classifier đang dùng). ~10 dòng/strategy. Kỳ vọng: cắt cụm entry chop → PF↑, DD↓,
   trades↓ mạnh.
2. **Session filter**: trend pair → London+NY (07:00–16:00 America/New_York);
   mean_reversion → Asian low-vol window. `BaseStrategy._in_session` đã có sẵn từ base
   class — chỉ cần wire config. Evidence nội bộ: orb DD 14% nhờ đúng cơ chế này.
3. **mean_reversion re-cross entry**: đổi từ "close ngoài band + RSI zone" sang "bar
   trước ngoài band, bar này close CẮT NGƯỢC vào trong band, RSI vẫn extreme" — xác nhận
   snap-back thay vì bắt dao rơi. Đây là thay đổi thiết kế tín hiệu (không sweep).
4. **Donchian crossing semantics**: chỉ vào ở bar ĐẦU TIÊN vượt channel (bar trước còn
   trong channel) — diệt churn re-entry trên move kéo dài.

**Nhóm B — Exit/trailing (config-only, evidence sẵn):**
5. **Bật scale-out theo ma trận**: supertrend M5+M15 ON, donchian M15 ON, donchian M5
   OFF. Chạy qua `run_baseline` với FTMO actor để lấy Sharpe/compliance (13.10 chưa đo).
6. **Time-stop cho mean_reversion** (Clenow): exit market nếu chưa revert sau `bb_period`
   (=20) bars — anchor theo chính chu kỳ BB, không phải số tune. Cần thêm
   `bars_since_entry` counter.
7. **BE + fee offset**: dời breakeven từ entry-price sang entry ± k_fee (lấy từ
   ContractSpec spread/commission thực) — sửa đúng bản chất, không phải tham số tự do.

**Nhóm C — Nợ kỹ thuật liên quan trực tiếp:**
8. Fix `safety_tp_atr_mult` dead field (consume trong scale-out mode hoặc xóa + migration
   note).
9. Supertrend indicator: truyền Wilder MA type cho ATR nội bộ (fidelity với spec gốc).
10. Cập nhật docstring stale ("no-op stub") trong `bracket_scale_out.py`.

**Trình tự validate** (giữ kỷ luật walk-forward, baseline so sánh =
`epic-12a-rerun-2y-{m5,m15}.md`): mỗi thay đổi A/B riêng lẻ trước, rồi stack
(ADX → +session → +tactic matrix). Tiêu chí thành công: DD compression + PF uplift tại
trade count thấp hơn đáng kể — không chỉ Sharpe. Chạy song song Track 4.3 (regime
ablation) vì mean_reversion chỉ có ý nghĩa sau gate RANGING.

**Kỳ vọng thực tế**: nhóm A+B là con đường khả dĩ nhất đưa donchian (PF 1.034 @ 4445
trades) lên vùng compliance-viable; supertrend cần ADX gate chứng minh flip có edge sau
phí trước khi đầu tư thêm; mean_reversion sống chết theo regime gate + re-cross — nếu
Track 4.3 + re-cross không kéo nó dương, đó là ứng viên archive tiếp theo trước khi tốn
công meta-labeling.
