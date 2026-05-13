# Epic 12: Backtest Validation + Parameter Optimization — Technical Context

**Created:** 2026-05-03
**Last updated:** 2026-05-03
**Status:** **Backlog** — branch `epic-12-backtest` ready off `main` (post-Epic-10/11 merge)
**Epic:** 12 of 12+
**Stories:** 12 (12.1 – 12.12)
**Predecessor:** Epic 11 (Market Regime Classifier — Phase 1) — closed 2026-05-02 (head `f019861`)
**Source references:** `docs/strategy-review-2026-05-02.md`, `docs/runbooks/backtesting.md`, `docs/sprint-artifacts/8-2-backtest-engine-metrics-ftmo-actor.md`, `docs/sprint-artifacts/8-8-walk-forward-parameter-sweep-cli.md`

---

## Overview

### Problem Statement

Sau Epic 8 (backtest framework), Epic 9 (multi-firm), Epic 10 (operational hardening) và Epic 11 (regime classifier), engine có **6 strategies đã ship + đầy đủ infra backtest** (`BacktestRunner`, `run_backtest` facade, `ParameterSweep`, `WalkForward`, `SpreadAwareFeeModel`, `PropFirmComplianceActor`, HTML report writer) — nhưng **chưa từng chạy validation pass nào trên dữ liệu thật**:

1. **Không biết strategy nào có edge.** Unit tests + smoke tests verify cơ chế (signal logic, bracket submission, mixin composition) chứ không trả lời "Sharpe của Supertrend trên XAUUSD M5 trong 2 năm gần nhất là bao nhiêu, có pass FTMO daily-loss/max-DD/consistency rule không".
2. **Không có baseline comparable metrics.** Mỗi strategy có smoke test riêng, không có report bảng so sánh side-by-side (Sharpe / Sortino / MaxDD / Profit Factor / Win Rate / Avg Trade) trên cùng dataset + cùng FTMO actor.
3. **Tham số mặc định chưa qua walk-forward.** YAML defaults là educated guess; không biết có overfit hay không, không biết test-window có generalize không.
4. **Strategy review 2026-05-02 chốt 3 mục "land during backtest epic"** — bracket execution coverage tests, E2E router integration tests, `__post_init__` regression tests — đợi epic này để dùng harness fixtures làm test surface.

Đồng thời, regime classifier (Epic 11) ship với `enabled: false` — chưa từng chạy end-to-end qua dữ liệu thật để biết tỉ lệ HIGH_VOL kill-switch fire có hợp lý không, hysteresis 2-bar có miss regime change đầu phiên London không.

### Solution

**Shape B — Validation + Parameter Optimization.** Reuse hoàn toàn backtest infra hiện có; không build engine mới. Pipeline 3 phase tuần tự:

1. **Phase 12.A — In-sample validation pass**: pin một dataset chuẩn (XAUUSD M5 + M15, 2 năm) → chạy 6 strategies với YAML defaults → produce comparable metrics report → áp explicit filter (Sharpe > 0.8, MaxDD < 8%, ≥ 200 trades, 0 FTMO breach). Strategies pass filter sang Phase 12.B; fail → ghi lại nhưng không tune (overfitting risk).
2. **Phase 12.B — Walk-forward + parameter sweep** trên top 2-3 strategies pass filter: 6-month rolling walk-forward, Optuna TPE sampler trong search space đã cap, validate OOS Sharpe ≥ 70% IS Sharpe.
3. **Phase 12.C — Strategy review carryover + runbook**: bracket coverage tests, router E2E tests, `__post_init__` regression tests, runbook update (operator pointer tới harness wrappers + dataset).

```
Dataset (XAUUSD M5+M15 2y, cached)
        │
        ▼
[12.A] In-sample run — 6 strategies
        │
        ├─→ comparison report (HTML + markdown)
        ├─→ FTMO compliance verification (rule engine attached)
        ▼
   filter: Sharpe>0.8, MaxDD<8%, trades≥200, 0 breach
        │
        ▼
[12.B] Walk-forward + parameter sweep — top 2-3
        │
        ▼
[12.C] Strategy review carryover + runbook update
```

### Scope (Shape B)

**In Scope:**

- Dataset pipeline XAUUSD M5 + M15 (2 năm IS + 1 năm OOS reserve), versioned + Parquet cached, fingerprint trong `BacktestResult.config_snapshot`.
- In-sample baseline harness wrapper cho 6 strategies — single runner produce comparable metrics, identical venue/fee/spread, identical FTMO actor, identical seed.
- Comparison report (HTML rollup + markdown table) — Sharpe / Sortino / MaxDD / Profit Factor / Win Rate / Avg Trade / Total Trades / FTMO breaches side-by-side.
- FTMO-compliance verification under backtest — `PropFirmComplianceActor` attached, daily-loss / max-DD / consistency rule simulated bar-by-bar, breach count = 0 cho strategies eligible cho Phase 12.B.
- Walk-forward harness wrapper — 6-month rolling, train 6m / test 1m / step 1m, anchored mode reserved cho ablation.
- Parameter sweep harness wrapper — Optuna TPE sampler, search space cap ≤ 200 combos/strategy, early-stop trên `max_overall_dd_pct > 10%`.
- Run + report parameter sweep on top 2-3 strategies (the actual experiment).
- Strategy review "Land during backtest epic" items folded in: bracket execution coverage tests (tick-rounding, ATR-zero, position-reversal), E2E router integration tests (regime rejection actually filters bars), `__post_init__` regression tests (priority-1 invariants).
- Runbook update — `docs/runbooks/backtesting.md` thêm pointer tới harness wrappers + dataset fingerprint.
- (Optional) Strategy roster recommendation memo với go/no-go evidence per strategy.

**Out of Scope (defer):**

- Production cutover (separate operator step, gated bởi 10.5d/e2/f follow-ups + ops sign-off).
- Epic 11 shadow-mode validation (parallel operator step trên live test account, không block epic này).
- HMM regime classifier Phase 2 (deferred — đợi 6 tháng rule-based production data).
- New strategies ngoài 6 hiện có (Phase 2+ của strategy stack — `MeanReversionMixin`, scalper, momentum, vv).
- FX majors ngoài XAUUSD (GBP/USD, EUR/USD đã whitelisted ở `job_config.py` nhưng dataset + tuning defer Phase 2).
- Live shadow-mode automation (operator manual step).
- 10.9b swap accrual (vẫn deferred — Nautilus `SimulationModule` rollover).
- `MeanReversionMixin` extraction + `BracketHost` Protocol + `StrategyRegistry` instance-based (strategy review "land after backtest epic" items — Epic 13 candidate).

---

## Architectural Decisions

### 1. In-sample window pinned 2 năm; OOS reserve 1 năm

**Why:**

- 2 năm M5 ≈ 144K bars, đủ statistical power cho Sharpe / MaxDD ổn định (Sortino cần ≥ 100 trades; với avg trade ~1/day, 2 năm cho ~500 trades/strategy).
- 1 năm OOS reserve **không touch trong Phase 12.A/B** — chỉ verify final picked params ở 12.B closing để chắc không leak.
- Chọn 2024-01-01 → 2025-12-31 IS, 2026-01-01 → 2026-05-01 OOS (whatever data ends — XAUUSD daily là sẵn).

**Rejected alternatives:**

- 5 năm IS: dữ liệu pre-2023 chứa COVID + war shock → regime distribution không representative cho hiện tại.
- 6 tháng IS: ≤ 30K bars M5 → Sharpe noise band ±0.3 → rank 6 strategies không discriminative.

### 2. In-sample filter explicit + measurable, không subjective

**Threshold (apply per-strategy on Phase 12.A output):**

- `sharpe ≥ 0.8` (annualized, 252 trading days basis — `FtmoMetricsSchema.sharpe`)
- `max_overall_dd_pct ≤ 8.0` (FTMO MaxDD threshold 10% có buffer 2pp)
- `total_trades ≥ 200` (statistical power for OOS extrapolation)
- `daily_loss_breaches == 0 AND max_dd_breach == False` (FTMO compliance gate)

Strategy fail filter → log results vào comparison report nhưng **skip Phase 12.B** (không tune lên-tới-pass; overfitting trap).

**Why:** Strategy review §"Recommended next moves" §11 cảnh báo HMM regime probability collapse → tương tự, "tune until pass" collapse OOS information. Filter cứng buộc developer chấp nhận strategy không có edge thay vì tune cho ra số đẹp.

### 3. Parameter sweep dùng Optuna TPE, không full grid

**Why:**

- 6 tunable params/strategy × 5 levels = 15,625 combos full grid → ~50h × 6 strategies trên 4 workers — không khả thi.
- Optuna TPE (Tree-Structured Parzen Estimator) converge ≤ 200 trials cho 6-dim continuous space, 5-10x faster than grid trên objective `net_pnl`.
- Existing `ParameterSweep` (8.8) hỗ trợ `search="random"` — extend `search="optuna"` qua adapter là nhỏ; nếu Optuna add complexity quá nhiều, fallback random với `n_iter=200, seed=42`.

**Rejected alternatives:**

- Full grid: explicit, reproducible, nhưng quá tốn — chỉ phù hợp 2-3 dim grid.
- Hyperopt: cùng class với Optuna nhưng less maintained, no native pruner.
- Bayesian (scikit-optimize): GP scaling poor cho discrete params.

**Search space cap:** strategist define `param_space.yaml` per-strategy với explicit bounds + step (vd `fast_period: [3, 5, 7, 10, 14]`). Cap ≤ 200 trials/strategy enforced trong CLI.

### 4. Walk-forward 6-month rolling, train 6m / test 1m / step 1m

**Why:**

- Anchored mode (train_start fixed) → fold gần cuối có 1.5y train → quá nhiều data leak từ regime cũ; rolling tốt hơn cho regime-shifting market như XAUUSD.
- Train 6m / test 1m → 12 folds non-overlapping trên 2y IS → ~12 OOS metrics per strategy → đủ aggregate stat (mean OOS Sharpe ± std).
- Step 1m = test 1m → no test overlap; mỗi tháng sau train là một fold.

**OOS acceptance threshold:** `mean(OOS sharpe) ≥ 0.7 × IS sharpe` AND `std(OOS sharpe) / mean(OOS sharpe) ≤ 0.5`. Strategy fail OOS threshold → recommendation = "không deploy live, cần Phase 2 redesign".

### 5. Regime classifier `enabled: false` trong baseline; ablation `enabled: true` riêng

**Why:**

- Phase 12.A baseline answer "strategy có edge mà không filter regime không?" — nếu pass mà không regime filter, lợi thế là **lower bound** trên live performance.
- Phase 12.A.1 (ablation, optional sub-story) — chạy lại 6 strategies với `regime_classifier.enabled: true` → so sánh per-strategy Sharpe delta. Quantify regime layer's contribution before promoting to live.
- Vì strategy review chỉ ra regime rejection path không có E2E test (item §coverage gap #3 + #6.5 "regime declarations are declared but the rejection path is not exercised"), 12.9 (router E2E tests) cũng wire ablation harness path — cùng surface code.

**Recommendation:** baseline không regime; landing-doc cho 12.7 phải report cả 2 numbers nếu strategy is candidate cho live.

### 6. Reuse existing HTML writer; comparison report là markdown table

**Why:**

- `src/backtesting/reports/html_writer.py` (8.9) đã ship deterministic single-file HTML per-result — phù hợp cho per-strategy report.
- Comparison report (6 strategies side-by-side) khó render ở HTML deterministic không-JS — markdown table dễ diff trong git, dễ paste vào memo.
- Per-fold walk-forward table cũng markdown.
- Single-file deliverable cuối cùng: `docs/sprint-artifacts/epic-12-validation-report.md` chứa cả markdown table + link tới per-strategy HTML.

### 7. Dataset fingerprint embedded in `BacktestResult.config_snapshot`

**Why:**

- `data_cache.py` đã có `ContentHashFingerprint` (8.3 cache key) — extend để stamp fingerprint vào result config snapshot.
- Validation report cite fingerprint → bất cứ ai re-run cùng fingerprint chắc chắn cùng dataset → reproducibility.
- Migration: dataset version bump (refresh, broker spread re-cached) → fingerprint thay đổi → old reports invalidate clearly.

---

## Story Breakdown

### Phase 12.A — In-sample validation

| # | Story | Effort | Status |
|---|---|---|---|
| 12.1 | Dataset pipeline XAUUSD M5+M15 (2y IS + 1y OOS reserve), Parquet cached + fingerprint stamped | M | backlog |
| 12.2 | In-sample baseline harness wrapper — single runner cho 6 strategies, identical venue/fee/seed | M | backlog |
| 12.3 | Comparison report writer — markdown rollup table (Sharpe/Sortino/MaxDD/PF/WinRate/Trades/Breaches) | S | backlog |
| 12.4 | FTMO-compliance verification under backtest — `PropFirmComplianceActor` attached + breach assertions | M | backlog |

### Phase 12.B — Walk-forward + parameter sweep

| # | Story | Effort | Status |
|---|---|---|---|
| 12.5 | Walk-forward harness wrapper — 6m rolling, OOS metrics aggregation, ratio threshold check | M | backlog |
| 12.6 | Parameter sweep harness wrapper — Optuna TPE adapter (fallback random), search space cap ≤ 200 | L | backlog |
| 12.7 | Run + report parameter sweep trên top 2-3 strategies — actual experiment story (XL) | XL | backlog |

### Phase 12.C — Strategy review carryover + runbook

| # | Story | Effort | Status |
|---|---|---|---|
| 12.8 | Bracket execution coverage tests — tick-rounding, ATR-zero, position-reversal (5 bracket strategies) | M | backlog |
| 12.9 | E2E router integration tests — regime rejection path actually filters bars (1-2 strategies + 4 CSV fixtures) | M | backlog |
| 12.10 | `__post_init__` regression tests — one deliberately-invalid config per strategy, asserts `ValueError` | S | backlog |
| 12.11 | Runbook update — `docs/runbooks/backtesting.md` thêm harness wrapper pointers + dataset fingerprint | S | backlog |
| 12.12 | (Optional) Strategy roster recommendation memo với go/no-go evidence per strategy | S | backlog |

**Total effort:** 1 XL + 1 L + 5 M + 4 S + 1 (optional S) ≈ **2-3 sprint** (4-6 tuần) 1 dev FT.

**Per-story details:** Story 12.7 has full doc tại `docs/sprint-artifacts/12-7-parameter-sweep-experiment.md` (XL only — Lightweight docs Option C). Other stories tracked trong context doc + sprint-status.yaml comments. Stories 12.8 và 12.9 có thể parallelize sau 12.2.

---

## Dependencies & Sequencing

```
12.1 (dataset)
  ↓
12.2 (in-sample harness) → 12.4 (FTMO compliance) → 12.3 (comparison report)
  ↓
[in-sample filter applied → top 2-3 picked]
  ↓
12.5 (walk-forward) → 12.6 (parameter sweep) → 12.7 (run + report)
  ↓
12.8, 12.9, 12.10 (parallel — no inter-dep)
  ↓
12.11 (runbook) → 12.12 (memo, optional)
```

12.8/12.9/12.10 không thực sự phụ thuộc Phase 12.A/B; có thể start parallel sau 12.1 nếu capacity. Đặt cuối Phase 12.C để aligned với "strategy review carryover" framing.

---

## Risks & Coordination Notes

### R1 — Historical data quality

**Risk:** XAUUSD M5 cache có thể có gaps (broker holidays, weekends, server outages), spread series thiếu, hoặc spread broker-A khác broker-B → backtest metrics phụ thuộc dataset implementation detail.

**Mitigation:**

- 12.1 acceptance criterion: gap detection report (max gap allowed = 1 weekend = 48h; longer → flagged).
- Spread baseline = `configs/firms/ftmo.yaml` `commission.per_lot_usd: 7.0` + per-symbol `spread_pips` (Epic 10.9 `SpreadAwareFeeModel`); broker-specific spread time-series defer Phase 2.
- Dataset fingerprint trong report — re-run với fingerprint khác phải re-validate.

### R2 — Overfitting trong parameter sweep

**Risk:** Tune 6-dim space với 200 trials → có thể tìm ra params đạt IS Sharpe 2.0 mà OOS chỉ 0.3 — pure noise.

**Mitigation:**

- Phase 12.A in-sample filter Decision §2 — fail filter ⇒ skip sweep, không tune lên-tới-pass.
- Walk-forward (Decision §4) OOS threshold: `mean(OOS) ≥ 0.7 × IS AND std/mean ≤ 0.5`. Fail ⇒ recommendation "không deploy".
- Search space cap ≤ 200 trials enforced trong CLI (Decision §3).
- Reserve 1 năm OOS không touch trong Phase 12.A/B — final sanity check trên picked params.

### R3 — Walk-forward compute cost

**Risk:** 200 trials × 12 folds × 3 strategies = 7,200 backtest runs. Nếu 1 run = 30s → 60h sequential. ProcessPoolExecutor 8 workers → 7.5h — borderline với 1 dev iteration cycle.

**Mitigation:**

- Search space cap ≤ 200 trials/strategy + early-stop trên `max_overall_dd_pct > 10%` (skip-record không abort) → typical run time giảm 30-50%.
- Compute cost budget acceptance: ≤ 10h trên dev workstation (4-8 cores). Vượt → reduce trials hoặc folds.
- Parquet cache hot path (12.1) — bar load < 100ms từ second run.
- Synthetic-bar fast lane vẫn hoạt động cho unit tests.

### R4 — FTMO rules under backtest divergent với production

**Risk:** Daily-loss reset timezone (CET trong `ftmo.yaml`), consistency rule cumulative window, swap accrual (10.9b deferred — không có rollover trong backtest) → backtest pass có thể fail live.

**Mitigation:**

- 12.4 acceptance: rule engine attach giống Epic 9.5 (timezone-aware reset), Epic 9.7 (consistency rule + DailyProfitHistory backtest parity).
- Document trong runbook (12.11): "swap accrual currently absent in backtest — strategies giữ position qua rollover hour có thể overestimate PnL ~0.1-0.5% / month per position. Track 10.9b follow-up."
- 12.7 report cite swap caveat per-strategy — nếu strategy hold > 24h average → flag warning.

### R5 — Epic 11 regime classifier interaction

**Question:** backtest run với `regime_classifier.enabled: true` để test gating, hay `false` để baseline strategies trong isolation?

**Recommendation (per Decision §5):** **Baseline = `enabled: false`**, ablation phụ với `enabled: true`. Lý do:

- "Strategy có edge tự thân không?" là question Phase 12.A trả lời — regime filter add lên trên là multiplier, không substitute.
- Ablation isolate regime layer's contribution → quantify giá trị Epic 11 thay vì gộp.
- E2E router integration test (12.9) cần cả 2 path để verify regime rejection thực sự fire — tự nhiên là vehicle cho ablation.
- 12.9 wires `enabled: true` sub-fixture; 12.7 report cite cả 2 numbers nếu candidate cho live.

### R6 — Strategy review HIGH items đã land

**Note:** Strategy review §"Land before backtest epic" gồm 3 items (cross-strategy validation invariants, squeeze + ATR-zero guards, `MeanReversionMixin` extraction). 2 items đầu **đã ship** trong commits `595e635`, `e1ecbfd`, `d8b8d5e` (post-merge of `feature/architecture` 2026-05-03). `MeanReversionMixin` extraction declined (16% mechanical duplication không justify abstraction cost; revisit khi có MR variant thứ 3 — tracked Phase 2 preview). **No pre-12.1 gate needed.**

---

## Phase 2 Roadmap (preview, NOT in scope)

Sau khi Epic 12 đóng, các candidate cho Epic 13+:

1. **HMM regime classifier (Epic 11 Phase 2)** — `hmmlearn>=0.3` + walk-forward training pipeline + `RegimeAdmission` Protocol để probabilities không collapse to hard states. Reference `docs/research/regime-classifier.md` §Phase 2.
2. **Additional strategies** — `MeanReversionMixin` extracted (strategy review §3), 1-2 momentum / scalper variants, 1 volatility breakout cho HIGH_VOL regime (currently kill-switch).
3. **FX majors beyond XAUUSD** — GBP/USD, EUR/USD, USD/JPY datasets + per-symbol thresholds tuned via 12.6 harness (already supports — chỉ cần dataset).
4. **Live shadow-mode automation** — engine flag `shadow_mode: true` route signals tới audit log thay vì MT5; cron compare shadow vs live PnL daily. Pre-step cho production cutover.
5. **Architectural cleanup post-backtest** (strategy review §"Land after backtest epic"):
   - `BracketHost` Protocol — replace `# type: ignore[attr-defined]` trong `BracketStrategyMixin`.
   - `StrategyRegistry` instance-based — support per-backtest-run distinct strategy sets.
   - `_read_account_balance` route qua Redis HWM snapshot.
   - `BaseStrategy._reverse_to(side)` template method — remove `ma_crossover` `is_flat` bypass.
6. **10.9b swap accrual** — Nautilus `SimulationModule` rollover model.
7. **Observability surface** — Prometheus metrics + OpenTelemetry tracing (Epic 10 carryover).

---

## References

- **Strategy review:** `docs/strategy-review-2026-05-02.md` (6 per-strategy + architect + coverage)
- **Predecessor epic context:** `docs/epic-11-context.md` (Epic 11 closed 2026-05-02 head `f019861`)
- **Architecture doc:** `docs/architecture.md` v3.2 (post-Epic-11)
- **Backtest infra design:** `docs/sprint-artifacts/8-2-backtest-engine-metrics-ftmo-actor.md`, `docs/sprint-artifacts/8-8-walk-forward-parameter-sweep-cli.md`
- **Runbook:** `docs/runbooks/backtesting.md`
- **Source code surveyed:** `services/trading-engine/src/backtesting/{engine,runner_facade,job_config,data_loader,data_cache,parameter_sweep,walk_forward,prop_firm_actor,synthetic_bars,reports/html_writer,spread_fee_model}.py`
- **Configs:** `configs/firms/ftmo.yaml`, `configs/strategies/*.yaml`
- **Project rules:** `.claude/rules/python/`, `.claude/rules/common/sandboxed-domain.md`
