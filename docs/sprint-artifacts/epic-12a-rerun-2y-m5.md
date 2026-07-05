# In-sample comparison report

- Run label: `epic-12a-baseline-xauusd-m5`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `ca810a6170c12167`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend | -0.11 | -0.18 | 68.16% | 0.92 | 32.9% | 3676 | 0 + max-DD | FAIL — sharpe -0.11 < 0.80, max drawdown 68.16% > 8.00%, max drawdown breach flag set |
| donchian_breakout | 0.06 | 0.11 | 40.05% | 1.03 | 35.4% | 4445 | 0 + max-DD | FAIL — sharpe 0.06 < 0.80, max drawdown 40.05% > 8.00%, max drawdown breach flag set |
| mean_reversion | -0.22 | -0.35 | 97.80% | 0.89 | 35.9% | 11119 | 0 + max-DD | FAIL — sharpe -0.22 < 0.80, max drawdown 97.80% > 8.00%, max drawdown breach flag set |
| ma_crossover | -0.02 | -0.03 | 31.79% | 0.98 | 33.8% | 2576 | 0 + max-DD | FAIL — sharpe -0.02 < 0.80, max drawdown 31.79% > 8.00%, max drawdown breach flag set |
| bollinger_mean_reversion | -0.28 | -0.45 | 99.37% | 0.88 | 36.4% | 12940 | 0 + max-DD | FAIL — sharpe -0.28 < 0.80, max drawdown 99.37% > 8.00%, max drawdown breach flag set |
| rsi_mean_reversion | -0.25 | -0.37 | 96.48% | 0.86 | 48.1% | 9816 | 0 + max-DD | FAIL — sharpe -0.25 < 0.80, max drawdown 96.48% > 8.00%, max drawdown breach flag set |
| orb | 0.03 | 0.05 | 14.31% | 1.05 | 36.6% | 517 | 0 + max-DD | FAIL — sharpe 0.03 < 0.80, max drawdown 14.31% > 8.00%, max drawdown breach flag set |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (7): `supertrend`, `donchian_breakout`, `mean_reversion`, `ma_crossover`, `bollinger_mean_reversion`, `rsi_mean_reversion`, `orb` — do not tune (overfitting trap, see Decision §2).

