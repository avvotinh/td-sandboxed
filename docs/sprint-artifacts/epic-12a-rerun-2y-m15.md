# In-sample comparison report

- Run label: `epic-12a-baseline-xauusd-m15`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `b0ad700694500da8`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend | -0.03 | -0.05 | 24.02% | 0.97 | 33.7% | 1198 | 0 + max-DD | FAIL — sharpe -0.03 < 0.80, max drawdown 24.02% > 8.00%, max drawdown breach flag set |
| donchian_breakout | 0.03 | 0.05 | 29.62% | 1.02 | 34.4% | 1685 | 0 + max-DD | FAIL — sharpe 0.03 < 0.80, max drawdown 29.62% > 8.00%, max drawdown breach flag set |
| mean_reversion | -0.15 | -0.25 | 64.04% | 0.93 | 35.7% | 3836 | 0 + max-DD | FAIL — sharpe -0.15 < 0.80, max drawdown 64.04% > 8.00%, max drawdown breach flag set |
| ma_crossover | -0.10 | -0.16 | 29.90% | 0.89 | 31.1% | 808 | 0 + max-DD | FAIL — sharpe -0.10 < 0.80, max drawdown 29.90% > 8.00%, max drawdown breach flag set |
| bollinger_mean_reversion | -0.15 | -0.25 | 70.54% | 0.93 | 36.7% | 4911 | 0 + max-DD | FAIL — sharpe -0.15 < 0.80, max drawdown 70.54% > 8.00%, max drawdown breach flag set |
| rsi_mean_reversion | -0.14 | -0.21 | 48.47% | 0.92 | 48.6% | 3247 | 0 + max-DD | FAIL — sharpe -0.14 < 0.80, max drawdown 48.47% > 8.00%, max drawdown breach flag set |
| orb | -0.02 | -0.03 | 17.91% | 0.97 | 34.0% | 517 | 0 + max-DD | FAIL — sharpe -0.02 < 0.80, max drawdown 17.91% > 8.00%, max drawdown breach flag set |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (7): `supertrend`, `donchian_breakout`, `mean_reversion`, `ma_crossover`, `bollinger_mean_reversion`, `rsi_mean_reversion`, `orb` — do not tune (overfitting trap, see Decision §2).

