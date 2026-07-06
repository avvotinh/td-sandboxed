# In-sample comparison report

- Run label: `track51-entry-filter-ab-xauusd-m5`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `ca810a6170c12167`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend[none] | -0.03 | -0.06 | 41.36% | 0.96 | 29.9% | 3951 | 0 + max-DD | FAIL — sharpe -0.03 < 0.80, max drawdown 41.36% > 8.00%, max drawdown breach flag set |
| supertrend[adx] | -0.07 | -0.15 | 36.69% | 0.86 | 30.0% | 970 | 0 + max-DD | FAIL — sharpe -0.07 < 0.80, max drawdown 36.69% > 8.00%, max drawdown breach flag set |
| supertrend[session] | -0.07 | -0.14 | 49.08% | 0.90 | 30.1% | 1773 | 0 + max-DD | FAIL — sharpe -0.07 < 0.80, max drawdown 49.08% > 8.00%, max drawdown breach flag set |
| supertrend[adx+session] | -0.01 | -0.03 | 14.22% | 0.95 | 30.5% | 478 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 14.22% > 8.00%, max drawdown breach flag set |
| donchian_breakout[none] | 0.06 | 0.11 | 40.05% | 1.03 | 35.4% | 4445 | 0 + max-DD | FAIL — sharpe 0.06 < 0.80, max drawdown 40.05% > 8.00%, max drawdown breach flag set |
| donchian_breakout[adx] | -0.02 | -0.03 | 27.82% | 0.97 | 33.8% | 2584 | 0 + max-DD | FAIL — sharpe -0.02 < 0.80, max drawdown 27.82% > 8.00%, max drawdown breach flag set |
| donchian_breakout[session] | -0.02 | -0.04 | 27.83% | 0.97 | 37.7% | 2143 | 0 + max-DD | FAIL — sharpe -0.02 < 0.80, max drawdown 27.83% > 8.00%, max drawdown breach flag set |
| donchian_breakout[cross] | 0.09 | 0.15 | 25.74% | 1.08 | 36.2% | 3029 | 0 + max-DD | FAIL — sharpe 0.09 < 0.80, max drawdown 25.74% > 8.00%, max drawdown breach flag set |
| donchian_breakout[adx+session+cross] | -0.03 | -0.05 | 22.63% | 0.94 | 37.2% | 950 | 0 + max-DD | FAIL — sharpe -0.03 < 0.80, max drawdown 22.63% > 8.00%, max drawdown breach flag set |
| mean_reversion[none] | -0.22 | -0.35 | 97.80% | 0.89 | 35.9% | 11119 | 0 + max-DD | FAIL — sharpe -0.22 < 0.80, max drawdown 97.80% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross] | -0.04 | -0.07 | 53.77% | 0.95 | 38.8% | 2670 | 0 + max-DD | FAIL — sharpe -0.04 < 0.80, max drawdown 53.77% > 8.00%, max drawdown breach flag set |
| mean_reversion[session] | -0.23 | -0.37 | 92.70% | 0.85 | 34.0% | 4434 | 0 + max-DD | FAIL — sharpe -0.23 < 0.80, max drawdown 92.70% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross+session] | -0.07 | -0.11 | 41.46% | 0.89 | 37.1% | 1000 | 0 + max-DD | FAIL — sharpe -0.07 < 0.80, max drawdown 41.46% > 8.00%, max drawdown breach flag set |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (13): `supertrend[none]`, `supertrend[adx]`, `supertrend[session]`, `supertrend[adx+session]`, `donchian_breakout[none]`, `donchian_breakout[adx]`, `donchian_breakout[session]`, `donchian_breakout[cross]`, `donchian_breakout[adx+session+cross]`, `mean_reversion[none]`, `mean_reversion[recross]`, `mean_reversion[session]`, `mean_reversion[recross+session]` — do not tune (overfitting trap, see Decision §2).

