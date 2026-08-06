# P3 parity gate

Roadmap task 3.7 requires the reorganize to be *provably* behaviour-preserving:
same trades, same metrics, before and after. These are the tools that gate it.

## The baseline

`baseline-fingerprints.txt` holds per-section SHA-256 digests of six Contract v2
exports taken from commit `960282c` — the last commit before `src/` was
reorganized. The six jobs cover both entry families, both timeframes, and the
scale-out exit path:

| run | job |
|---|---|
| donchian-m5 | `configs/backtest/epic13-donchian-baseline-m5.yaml` |
| donchian-m15 | `configs/backtest/epic13-donchian-baseline-m15.yaml` |
| supertrend-m5 | `configs/backtest/epic13-baseline.yaml` |
| supertrend-m15 | `configs/backtest/epic13-baseline-m15.yaml` |
| supertrend-scaleout-m5 | `configs/backtest/epic13-scaleout.yaml` |
| mean-reversion-m5 | `configs/backtest/parity-mean-reversion-m5.yaml` |

Headline numbers, for a sanity check that the data underneath has not moved:

| run | trades | net PnL | max DD |
|---|---|---|---|
| donchian-m5 | 4445 | +83,123.84 | 40.13% |
| donchian-m15 | 1685 | +8,679.61 | 30.05% |
| supertrend-m5 | 3676 | −67,450.74 | 68.17% |
| supertrend-m15 | 1198 | −11,203.84 | 24.32% |
| supertrend-scaleout-m5 | 3871 | −47,130.48 | 52.02% |
| mean-reversion-m5 | 11119 | −97,684.63 | 97.80% |

These are in-sample XAUUSD 2y runs at 0.5% risk with no regime gate. They are a
**fixture, not a result** — none of them passes the promotion gate, and nothing
here should be cited as a finding. Cite `results/*.json` run_ids instead.

## Running the gate

```bash
# export the six runs somewhere scratch, then:
uv run python scripts/parity/parity.py hash <dir>/*.json      # digests
uv run python scripts/parity/parity.py diff <before> <after>   # localize a mismatch
```

`run_id` and `engine.commit` are excluded from the digest — both change on every
run by construction. Everything else (params, window, data_ref, account, trades,
equity curve, indicators, metrics, breaches) must match exactly.

## Import validation

```bash
uv run python scripts/parity/check_imports.py
```

Statically resolves every intra-`src` import against the files on disk. This
catches what an import smoke test cannot: a relative import whose depth changed
during a move and now silently resolves to a *different* package that happens to
exist. Note it deliberately has no "resolvable parent" fallback — accepting one
hides a submodule that moved out from under its package, which is the exact bug
this exists to catch.
