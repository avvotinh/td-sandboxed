# In-sample comparison report

- Run label: `track43-regime-ablation-xauusd-m15`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `b0ad700694500da8`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend[none]\|gate=off | -0.01 | -0.02 | 29.87% | 0.98 | 32.9% | 1255 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 29.87% > 8.00%, max drawdown breach flag set |
| donchian_breakout[none]\|gate=off | 0.06 | 0.12 | 20.93% | 1.05 | 39.1% | 1682 | 0 + max-DD | FAIL — sharpe 0.06 < 0.80, max drawdown 20.93% > 8.00%, max drawdown breach flag set |
| mean_reversion[none]\|gate=off | -0.15 | -0.25 | 64.04% | 0.93 | 35.7% | 3836 | 0 + max-DD | FAIL — sharpe -0.15 < 0.80, max drawdown 64.04% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross]\|gate=off | -0.19 | -0.29 | 41.29% | 0.82 | 36.3% | 893 | 0 + max-DD | FAIL — sharpe -0.19 < 0.80, max drawdown 41.29% > 8.00%, max drawdown breach flag set |
| supertrend[none]\|gate=on | -0.08 | -0.15 | 9.48% | 0.72 | 29.7% | 91 | 0 | FAIL — sharpe -0.08 < 0.80, max drawdown 9.48% > 8.00%, trades 91 < 200 |
| donchian_breakout[none]\|gate=on | 0.00 | 0.00 | 14.80% | 0.99 | 36.8% | 440 | 0 + max-DD | FAIL — sharpe 0.00 < 0.80, max drawdown 14.80% > 8.00%, max drawdown breach flag set |
| mean_reversion[none]\|gate=on | -0.14 | -0.22 | 36.13% | 0.88 | 34.0% | 1055 | 0 + max-DD | FAIL — sharpe -0.14 < 0.80, max drawdown 36.13% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross]\|gate=on | -0.01 | -0.02 | 2.55% | 0.94 | 36.8% | 38 | 0 | FAIL — sharpe -0.01 < 0.80, trades 38 < 200 |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (8): `supertrend[none]\|gate=off`, `donchian_breakout[none]\|gate=off`, `mean_reversion[none]\|gate=off`, `mean_reversion[recross]\|gate=off`, `supertrend[none]\|gate=on`, `donchian_breakout[none]\|gate=on`, `mean_reversion[none]\|gate=on`, `mean_reversion[recross]\|gate=on` — do not tune (overfitting trap, see Decision §2).

