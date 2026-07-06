# In-sample comparison report

- Run label: `track5-trailing-ab-xauusd-m15`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `b0ad700694500da8`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend[baseline] | -0.03 | -0.05 | 24.02% | 0.97 | 33.7% | 1198 | 0 + max-DD | FAIL — sharpe -0.03 < 0.80, max drawdown 24.02% > 8.00%, max drawdown breach flag set |
| supertrend[scaleout] | -0.01 | -0.02 | 29.88% | 0.98 | 28.8% | 1255 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 29.88% > 8.00%, max drawdown breach flag set |
| supertrend[trailonly] | -0.04 | -0.08 | 31.02% | 0.95 | 29.0% | 1291 | 0 + max-DD | FAIL — sharpe -0.04 < 0.80, max drawdown 31.02% > 8.00%, max drawdown breach flag set |
| supertrend[scaleout-beoffset] | -0.01 | -0.02 | 29.87% | 0.98 | 32.9% | 1255 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 29.87% > 8.00%, max drawdown breach flag set |
| donchian_breakout[baseline] | 0.03 | 0.05 | 29.62% | 1.02 | 34.4% | 1685 | 0 + max-DD | FAIL — sharpe 0.03 < 0.80, max drawdown 29.62% > 8.00%, max drawdown breach flag set |
| donchian_breakout[scaleout] | 0.06 | 0.11 | 21.00% | 1.04 | 36.6% | 1681 | 0 + max-DD | FAIL — sharpe 0.06 < 0.80, max drawdown 21.00% > 8.00%, max drawdown breach flag set |
| donchian_breakout[trailonly] | 0.02 | 0.04 | 24.96% | 1.01 | 33.2% | 2005 | 0 + max-DD | FAIL — sharpe 0.02 < 0.80, max drawdown 24.96% > 8.00%, max drawdown breach flag set |
| donchian_breakout[scaleout-beoffset] | 0.06 | 0.12 | 20.93% | 1.05 | 39.1% | 1682 | 0 + max-DD | FAIL — sharpe 0.06 < 0.80, max drawdown 20.93% > 8.00%, max drawdown breach flag set |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (8): `supertrend[baseline]`, `supertrend[scaleout]`, `supertrend[trailonly]`, `supertrend[scaleout-beoffset]`, `donchian_breakout[baseline]`, `donchian_breakout[scaleout]`, `donchian_breakout[trailonly]`, `donchian_breakout[scaleout-beoffset]` — do not tune (overfitting trap, see Decision §2).

