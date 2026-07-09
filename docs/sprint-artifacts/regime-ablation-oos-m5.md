# In-sample comparison report

- Run label: `track43-regime-ablation-xauusd-m5`
- Dataset: `xauusd-validation` v`1.0.0` (window `oos_reserve`)
- Dataset fingerprint: `17e28d422baea568`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend[none]\|gate=off | -0.12 | -0.24 | 31.78% | 0.87 | 27.6% | 608 | 0 + max-DD | FAIL — sharpe -0.12 < 0.80, max drawdown 31.78% > 8.00%, max drawdown breach flag set |
| supertrend[adx+session]\|gate=off | -0.22 | -0.37 | 12.72% | 0.49 | 21.1% | 71 | 0 + max-DD | FAIL — sharpe -0.22 < 0.80, max drawdown 12.72% > 8.00%, trades 71 < 200, max drawdown breach flag set |
| donchian_breakout[cross]\|gate=off | -0.11 | -0.18 | 18.52% | 0.89 | 31.3% | 358 | 0 + max-DD | FAIL — sharpe -0.11 < 0.80, max drawdown 18.52% > 8.00%, max drawdown breach flag set |
| mean_reversion[none]\|gate=off | 0.01 | 0.01 | 31.94% | 1.00 | 37.5% | 1819 | 0 + max-DD | FAIL — sharpe 0.01 < 0.80, max drawdown 31.94% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross]\|gate=off | -0.09 | -0.14 | 12.34% | 0.91 | 38.5% | 413 | 0 + max-DD | FAIL — sharpe -0.09 < 0.80, max drawdown 12.34% > 8.00%, max drawdown breach flag set |
| supertrend[none]\|gate=on | -0.10 | -0.19 | 8.34% | 0.64 | 27.5% | 40 | 0 | FAIL — sharpe -0.10 < 0.80, max drawdown 8.34% > 8.00%, trades 40 < 200 |
| supertrend[adx+session]\|gate=on | -0.24 | -0.28 | 4.64% | 0.25 | 11.8% | 17 | 0 | FAIL — sharpe -0.24 < 0.80, trades 17 < 200 |
| donchian_breakout[cross]\|gate=on | -0.10 | -0.16 | 11.19% | 0.85 | 30.4% | 161 | 0 + max-DD | FAIL — sharpe -0.10 < 0.80, max drawdown 11.19% > 8.00%, trades 161 < 200, max drawdown breach flag set |
| mean_reversion[none]\|gate=on | -0.12 | -0.19 | 22.19% | 0.89 | 34.6% | 517 | 0 + max-DD | FAIL — sharpe -0.12 < 0.80, max drawdown 22.19% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross]\|gate=on | -0.01 | -0.01 | 2.16% | 0.96 | 41.9% | 31 | 0 | FAIL — sharpe -0.01 < 0.80, trades 31 < 200 |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (10): `supertrend[none]\|gate=off`, `supertrend[adx+session]\|gate=off`, `donchian_breakout[cross]\|gate=off`, `mean_reversion[none]\|gate=off`, `mean_reversion[recross]\|gate=off`, `supertrend[none]\|gate=on`, `supertrend[adx+session]\|gate=on`, `donchian_breakout[cross]\|gate=on`, `mean_reversion[none]\|gate=on`, `mean_reversion[recross]\|gate=on` — do not tune (overfitting trap, see Decision §2).

