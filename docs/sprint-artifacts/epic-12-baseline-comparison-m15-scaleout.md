# In-sample comparison report

- Run label: `epic-12a-baseline-xauusd-m15-scaleout`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `b0ad700694500da8`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend | -0.01 | -0.02 | 0.34% | 0.99 | 28.7% | 1255 | 0 | FAIL — sharpe -0.01 < 0.80 |
| donchian_breakout | 0.06 | 0.12 | 0.22% | 1.05 | 36.6% | 1681 | 0 | FAIL — sharpe 0.06 < 0.80 |
| ma_crossover | 0.14 | 0.34 | 0.03% | 1.25 | 30.2% | 884 | 0 | FAIL — sharpe 0.14 < 0.80 |
| bollinger_mean_reversion | -0.15 | -0.25 | 1.11% | 0.94 | 36.7% | 4911 | 0 | FAIL — sharpe -0.15 < 0.80 |
| rsi_mean_reversion | -0.14 | -0.21 | 0.62% | 0.93 | 48.6% | 3247 | 0 | FAIL — sharpe -0.14 < 0.80 |
| orb | -0.02 | -0.03 | 0.19% | 0.98 | 34.0% | 517 | 0 | FAIL — sharpe -0.02 < 0.80 |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (6): `supertrend`, `donchian_breakout`, `ma_crossover`, `bollinger_mean_reversion`, `rsi_mean_reversion`, `orb` — do not tune (overfitting trap, see Decision §2).

