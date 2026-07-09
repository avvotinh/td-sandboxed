# Strategy Redesign Plan — 2026-07-02

**Bối cảnh:** Tiếp nhận lại project từ team trước. Phase 12.A kết luận không strategy nào
đạt Sharpe ≥ 0.8 (best: ma_crossover M15 +0.137, và con số đó là artifact do thiếu SL).
Review 2026-07-02 phát hiện thêm **bug sizing lot-vs-unit** làm sai lệch mọi kết quả
backtest (chi tiết §1). Constraint hiện tại: **chưa có TradingView Premium** và thư mục
`data/historical/` (32 shards Epic 16) **không còn trên máy** — mọi task cần data lịch sử
bị chặn cho đến khi khôi phục.

**Nguyên tắc thứ tự:** Track 1–3 làm được ngay không cần data. Track 4+ chỉ chạy sau khi
Track 0 khôi phục data VÀ Track 1 sửa xong sizing (chạy trước là phí công).

---

## §1 — Bug sizing đã xác nhận (root cause của backtest sai)

Chuỗi bằng chứng:

1. `RiskBasedPositionSizer` nhận `pip_size`/`pip_value_per_lot` từ YAML tĩnh theo quy ước
   **lot MT5** (XAUUSD: 1 lot = 100 oz, pip 0.01 = $1/lot).
2. Backtest engine (`runner_facade.py`) định nghĩa instrument là Nautilus `CurrencyPair`
   với multiplier 1 → **1 quantity = 1 oz** (XAUUSD) / 1 unit base currency (FX).
3. Output "lots" của sizer đi thẳng vào `make_qty()` không nhân contract size
   (`bracket_strategy.py:267` → `base_strategy.py:407`).
4. → Rủi ro thực nhận = 1/100 thiết kế trên XAUUSD (risk 0.5% = $500/trade thiết kế,
   thực tế ~$5/trade). Với FX theo hướng dẫn `--pip-value-per-lot 10` sẽ lệch **100.000×**.
   USDJPY còn thiếu quy đổi pip value JPY→USD (docstring sizer yêu cầu caller quy đổi
   nhưng không caller nào làm).
5. **Đối chiếu số liệu** (`epic-12-baseline-comparison.md`): EV ±$0.2–0.35/trade so với
   risk cap $500; max DD khớp tích lũy lỗ ở scale 1/100 — Bollinger MR 14.187 trades ×
   −$0.344 ≈ 4,88% vs báo cáo 5,01%; RSI MR ≈ 3,11% vs 3,19%.
6. Fee models (`PerContractFeeModel`, `SpreadAwareFeeModel`) nhân phí per-lot với
   `fill_qty` tính bằng unit — lý do lịch sử "FX fee burn" bị xử lý sai bằng cách zero fee.

**Hệ quả:** Xếp hạng Sharpe (Donchian tốt nhất / MR tệ nhất / không ai đạt 0.8) vẫn đứng
vững vì Sharpe bất biến theo scale. Nhưng EV $/trade phải nhân 100 khi đọc lại, và **mọi
kết luận FTMO compliance ("0 breaches, DD < 5.1%") vô giá trị** — chưa strategy nào từng
được kiểm tra ở mức rủi ro thật.

---

## Track 0 — Khôi phục data (song song, không chặn Track 1–3)

- [ ] **0.1** Liên hệ dev cũ xin bàn giao `data/historical/<SYMBOL>/<TF>/{in_sample,oos_reserve}.parquet`
      (+ `.manifest.json`) — 32 shards, 4 symbols × 4 TFs × 2 windows. Rẻ hơn nhiều so với re-fetch.
- [ ] **0.2** Nếu không xin được: mua/mượn TradingView Premium 1 tháng, re-fetch theo
      `docs/runbooks/backtest-data-fetch.md` (`fetch_campaign.py` + `stitch_chunks_to_window.py`,
      spec `configs/datasets/*-5y.yaml`). Sau đó chạy lại quality gates như
      `epic-16-data-quality-report.md`.
- [ ] **0.3** Đưa data vào shared artifact storage (Epic 17 đã có story "artifact storage"
      contexted) để không lặp lại tình trạng data nằm trên máy cá nhân.

## Track 1 — Sửa sizing bug (KHÔNG cần data — làm đầu tiên)

- [x] **1.1 (TDD RED)** Viết **sizing parity test**: dùng `synthetic_bars.py`, cho mỗi symbol
      (XAUUSD, EURUSD, USDJPY) chạy 1 lệnh dính SL qua backtest engine → assert lỗ thực nhận
      ≈ `risk_percent × balance` (±5%). Test này lẽ ra đã bắt được bug từ đầu; là cổng hồi quy vĩnh viễn.
- [x] **1.2** Tạo **contract spec per symbol** (contract_size, pip_size, quote_currency) làm
      nguồn sự thật duy nhất — có thể derive từ instrument definition. Xóa `pip_size`/
      `pip_value_per_lot` khỏi strategy YAML (breaking change có chủ đích).
- [x] **1.3** Sửa submit path: quy đổi lot→engine-unit tại một điểm duy nhất
      (XAUUSD ×100, FX ×100.000), quy đổi pip value quote-currency→USD cho JPY pairs.
- [x] **1.4** Sửa fee models: phí per-lot tính theo `qty / contract_size`; bật lại
      commission/spread thực cho FX (đừng giữ zero-fee workaround).
- [x] **1.5** Full test suite + `python-reviewer`; cập nhật ghi chú vào các báo cáo cũ
      (banner "số liệu EV/DD trước 2026-07 bị lệch 100×" để người sau không đọc nhầm).

## Track 2 — Dọn roster strategy (KHÔNG cần data)

- [x] **2.1** Gộp RSI-MR + Bollinger-MR thành **một** strategy mean-reversion với tín hiệu
      kết hợp (chạm band BB **và** RSI cực trị) — đồng thời trả nợ `MeanReversionMixin`
      từ `strategy-review-2026-05-02.md`.
- [x] **2.2** Loại `ma_crossover` khỏi roster active (edge đã chứng minh là artifact);
      giữ EMA slope làm regime feature. ORB giữ nguyên trạng thái archived (`regimes=[]`).
- [x] **2.3** Trả nợ kỹ thuật liên quan: `BracketHost` Protocol thay duck-typing,
      `_read_account_balance` dùng Decimal/Redis HWM thay float round-trip.

## Track 3 — Research redesign (KHÔNG cần data, không cần code)

- [x] **3.1** `/research` multi-indicator confirmation cho trend-followers:
      Donchian + ADX≥25 filter; Supertrend–Donchian confluence; session VWAP làm bias filter
      (indicator `session_vwap.py` đã viết sẵn, chưa strategy nào dùng).
- [x] **3.2** `/research` session filter cho XAUUSD/FX (hạ tầng `SessionFilterMixin` có sẵn từ ORB).
- [x] **3.3** Đọc lại 2 research docs meta-labeling có sẵn (`docs/research/meta-labeling-*.md`,
      `ml-data-prep-and-training.md`) — chuẩn bị cho Track 5.

## Track 4 — Validate lại (CẦN data: chặn bởi Track 0 + Track 1)

- [x] **4.1** Re-run Phase 12.A trên XAUUSD M5/M15 với sizing đúng → viết verdict mới.
      Kỳ vọng: thứ hạng Sharpe giữ, số FTMO compliance thay đổi hoàn toàn (một số strategy
      sẽ breach daily-loss thật — đó là thông tin để loại bỏ).
      *(2026-07-05: chạy trên 2y window — `epic-12a-rerun-2y-verdict.md`. Kỳ vọng xác nhận:
      Sharpe giữ nguyên từng số trừ ma_crossover sụp vì fee per-lot; mọi strategy breach
      max-DD 10%. Re-run 5y chờ Track 0.)*
- [ ] **4.2** Baseline 5 năm × 4 symbols × M5/M15 (kiểm tra giả thuyết "XAUUSD chỉ là
      instrument nhiễu nhất" từ retro Epic 13 §8).
- [x] **4.3** Regime gating **ablation ON vs OFF** (RegimeActor Epic 15 đã xong, default-OFF) —
      quyết định bật default bằng số liệu. → `sprint-artifacts/regime-ablation-2y-verdict.md`
      (2026-07-09): KHÔNG bật global — gate cứu MR[recross] (+0.035, DD 4.8%) và supertrend
      (+0.032, DD 3.4%) trên M5 nhưng phá donchian (+0.087→−0.013); cần per-strategy opt-out.
- [ ] **4.4** Story 12.12 **roster memo**: go/no-go từng strategy trên số liệu đúng.

## Track 5 — Redesign entries + meta-labeling (CẦN data)

- [ ] **5.1** Implement các biến thể confirmation từ Track 3, validate bằng **walk-forward**
      trên 5y. KHÔNG parameter sweep (12.7b gated có chủ đích — sửa thiết kế tín hiệu,
      không tinh chỉnh số).
- [ ] **5.2** Epic 17 meta-labeling (18 stories đã contexted): triple-barrier labeling,
      purged/embargoed CV, LightGBM + calibration, `MetaLabelGate` qua seam
      `RegimeSnapshot.features` → `_meta_label_admits`.

## Track 6 — Live path (chỉ khi có strategy vượt Sharpe ≥ 0.8 sau Track 4–5)

- [ ] **6.1** Epic 14 MT5 EA (21 stories) — gỡ `ZmqExecutionClient.modify_order NotImplementedError`.
- [ ] **6.2** Shadow-trade trên demo account trước khi vào FTMO challenge thật.

---

**Điểm quyết định quan trọng:** sau Track 4, nếu không strategy nào có Sharpe > ~0.3 trên
data 5 năm đa symbol với sizing đúng, cân nhắc dừng hướng "tune 6 strategies cũ" và dồn
nguồn lực cho Track 5 (meta-labeling trên Donchian/Supertrend) hoặc tìm signal class mới —
đừng đốt thời gian vào Track 6.
