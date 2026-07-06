# In-sample comparison report

- Run label: `track51-entry-filter-ab-xauusd-m15`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `b0ad700694500da8`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend[none] | -0.01 | -0.02 | 29.87% | 0.98 | 32.9% | 1255 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 29.87% > 8.00%, max drawdown breach flag set |
| supertrend[adx] | -0.07 | -0.14 | 20.16% | 0.87 | 31.6% | 351 | 0 + max-DD | FAIL — sharpe -0.07 < 0.80, max drawdown 20.16% > 8.00%, max drawdown breach flag set |
| supertrend[session] | -0.01 | -0.03 | 21.05% | 0.97 | 31.8% | 757 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 21.05% > 8.00%, max drawdown breach flag set |
| supertrend[adx+session] | -0.00 | -0.00 | 16.40% | 0.98 | 32.5% | 274 | 0 + max-DD | FAIL — sharpe -0.00 < 0.80, max drawdown 16.40% > 8.00%, max drawdown breach flag set |
| donchian_breakout[none] | 0.06 | 0.12 | 20.93% | 1.05 | 39.1% | 1682 | 0 + max-DD | FAIL — sharpe 0.06 < 0.80, max drawdown 20.93% > 8.00%, max drawdown breach flag set |
| donchian_breakout[adx] | -0.06 | -0.11 | 25.44% | 0.92 | 37.0% | 890 | 0 + max-DD | FAIL — sharpe -0.06 < 0.80, max drawdown 25.44% > 8.00%, max drawdown breach flag set |
| donchian_breakout[session] | -0.05 | -0.08 | 24.40% | 0.93 | 38.4% | 872 | 0 + max-DD | FAIL — sharpe -0.05 < 0.80, max drawdown 24.40% > 8.00%, max drawdown breach flag set |
| donchian_breakout[cross] | 0.05 | 0.09 | 23.82% | 1.03 | 39.0% | 1618 | 0 + max-DD | FAIL — sharpe 0.05 < 0.80, max drawdown 23.82% > 8.00%, max drawdown breach flag set |
| donchian_breakout[adx+session+cross] | -0.14 | -0.23 | 23.45% | 0.77 | 38.2% | 419 | 0 + max-DD | FAIL — sharpe -0.14 < 0.80, max drawdown 23.45% > 8.00%, max drawdown breach flag set |
| mean_reversion[none] | -0.15 | -0.25 | 64.04% | 0.93 | 35.7% | 3836 | 0 + max-DD | FAIL — sharpe -0.15 < 0.80, max drawdown 64.04% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross] | -0.19 | -0.29 | 41.29% | 0.82 | 36.3% | 893 | 0 + max-DD | FAIL — sharpe -0.19 < 0.80, max drawdown 41.29% > 8.00%, max drawdown breach flag set |
| mean_reversion[session] | -0.20 | -0.33 | 57.15% | 0.86 | 33.5% | 1581 | 0 + max-DD | FAIL — sharpe -0.20 < 0.80, max drawdown 57.15% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross+session] | -0.13 | -0.20 | 22.49% | 0.82 | 34.2% | 360 | 0 + max-DD | FAIL — sharpe -0.13 < 0.80, max drawdown 22.49% > 8.00%, max drawdown breach flag set |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (13): `supertrend[none]`, `supertrend[adx]`, `supertrend[session]`, `supertrend[adx+session]`, `donchian_breakout[none]`, `donchian_breakout[adx]`, `donchian_breakout[session]`, `donchian_breakout[cross]`, `donchian_breakout[adx+session+cross]`, `mean_reversion[none]`, `mean_reversion[recross]`, `mean_reversion[session]`, `mean_reversion[recross+session]` — do not tune (overfitting trap, see Decision §2).

