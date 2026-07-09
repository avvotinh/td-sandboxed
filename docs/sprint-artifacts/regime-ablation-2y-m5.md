# In-sample comparison report

- Run label: `track43-regime-ablation-xauusd-m5`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `ca810a6170c12167`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend[none]\|gate=off | -0.03 | -0.06 | 41.36% | 0.96 | 29.9% | 3951 | 0 + max-DD | FAIL — sharpe -0.03 < 0.80, max drawdown 41.36% > 8.00%, max drawdown breach flag set |
| supertrend[adx+session]\|gate=off | -0.01 | -0.03 | 14.22% | 0.95 | 30.5% | 478 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 14.22% > 8.00%, max drawdown breach flag set |
| donchian_breakout[cross]\|gate=off | 0.09 | 0.15 | 25.74% | 1.08 | 36.2% | 3029 | 0 + max-DD | FAIL — sharpe 0.09 < 0.80, max drawdown 25.74% > 8.00%, max drawdown breach flag set |
| mean_reversion[none]\|gate=off | -0.22 | -0.35 | 97.80% | 0.89 | 35.9% | 11119 | 0 + max-DD | FAIL — sharpe -0.22 < 0.80, max drawdown 97.80% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross]\|gate=off | -0.04 | -0.07 | 53.77% | 0.95 | 38.8% | 2670 | 0 + max-DD | FAIL — sharpe -0.04 < 0.80, max drawdown 53.77% > 8.00%, max drawdown breach flag set |
| supertrend[none]\|gate=on | 0.03 | 0.07 | 3.39% | 1.30 | 37.3% | 59 | 0 | FAIL — sharpe 0.03 < 0.80, trades 59 < 200 |
| supertrend[adx+session]\|gate=on | 0.02 | 0.05 | 2.91% | 1.21 | 38.6% | 44 | 0 | FAIL — sharpe 0.02 < 0.80, trades 44 < 200 |
| donchian_breakout[cross]\|gate=on | -0.01 | -0.02 | 20.91% | 0.97 | 33.5% | 558 | 0 + max-DD | FAIL — sharpe -0.01 < 0.80, max drawdown 20.91% > 8.00%, max drawdown breach flag set |
| mean_reversion[none]\|gate=on | -0.07 | -0.12 | 59.38% | 0.91 | 37.1% | 2893 | 0 + max-DD | FAIL — sharpe -0.07 < 0.80, max drawdown 59.38% > 8.00%, max drawdown breach flag set |
| mean_reversion[recross]\|gate=on | 0.04 | 0.06 | 4.78% | 1.14 | 44.6% | 166 | 0 | FAIL — sharpe 0.04 < 0.80, trades 166 < 200 |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (10): `supertrend[none]\|gate=off`, `supertrend[adx+session]\|gate=off`, `donchian_breakout[cross]\|gate=off`, `mean_reversion[none]\|gate=off`, `mean_reversion[recross]\|gate=off`, `supertrend[none]\|gate=on`, `supertrend[adx+session]\|gate=on`, `donchian_breakout[cross]\|gate=on`, `mean_reversion[none]\|gate=on`, `mean_reversion[recross]\|gate=on` — do not tune (overfitting trap, see Decision §2).

