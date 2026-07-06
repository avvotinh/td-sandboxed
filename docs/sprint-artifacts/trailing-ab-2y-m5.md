# In-sample comparison report

- Run label: `track5-trailing-ab-xauusd-m5`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `ca810a6170c12167`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend[baseline] | -0.11 | -0.18 | 68.16% | 0.92 | 32.9% | 3676 | 0 + max-DD | FAIL — sharpe -0.11 < 0.80, max drawdown 68.16% > 8.00%, max drawdown breach flag set |
| supertrend[scaleout] | -0.04 | -0.09 | 51.90% | 0.95 | 29.3% | 3871 | 0 + max-DD | FAIL — sharpe -0.04 < 0.80, max drawdown 51.90% > 8.00%, max drawdown breach flag set |
| supertrend[trailonly] | -0.03 | -0.06 | 41.36% | 0.96 | 29.9% | 3951 | 0 + max-DD | FAIL — sharpe -0.03 < 0.80, max drawdown 41.36% > 8.00%, max drawdown breach flag set |
| supertrend[scaleout-beoffset] | -0.04 | -0.09 | 50.97% | 0.95 | 32.6% | 3871 | 0 + max-DD | FAIL — sharpe -0.04 < 0.80, max drawdown 50.97% > 8.00%, max drawdown breach flag set |
| donchian_breakout[baseline] | 0.06 | 0.11 | 40.05% | 1.03 | 35.4% | 4445 | 0 + max-DD | FAIL — sharpe 0.06 < 0.80, max drawdown 40.05% > 8.00%, max drawdown breach flag set |
| donchian_breakout[scaleout] | 0.01 | 0.01 | 45.32% | 1.00 | 36.5% | 4974 | 0 + max-DD | FAIL — sharpe 0.01 < 0.80, max drawdown 45.32% > 8.00%, max drawdown breach flag set |
| donchian_breakout[trailonly] | -0.04 | -0.08 | 51.12% | 0.96 | 32.5% | 5915 | 0 + max-DD | FAIL — sharpe -0.04 < 0.80, max drawdown 51.12% > 8.00%, max drawdown breach flag set |
| donchian_breakout[scaleout-beoffset] | 0.00 | 0.00 | 45.69% | 0.99 | 39.0% | 4977 | 0 + max-DD | FAIL — sharpe 0.00 < 0.80, max drawdown 45.69% > 8.00%, max drawdown breach flag set |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (8): `supertrend[baseline]`, `supertrend[scaleout]`, `supertrend[trailonly]`, `supertrend[scaleout-beoffset]`, `donchian_breakout[baseline]`, `donchian_breakout[scaleout]`, `donchian_breakout[trailonly]`, `donchian_breakout[scaleout-beoffset]` — do not tune (overfitting trap, see Decision §2).

