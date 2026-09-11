# P3 parity gate

Roadmap task 3.7 requires the reorganize to be *provably* behaviour-preserving:
same trades, same metrics, before and after. These are the tools that gate it.

## The baseline

`baseline-fingerprints.txt` holds per-section SHA-256 digests of nine Contract v2
exports. Six come from commit `960282c` — the last commit before `src/` was
reorganized — and cover both entry families, both timeframes, and the scale-out
exit path. Three more were added at task 3.3 to cover the *gated* entry paths;
they are listed under **Result** below, along with why six was not enough.

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

## Result

Run at `1a28b5b` (after the 3.2 prune): **PASS, 6/6 runs identical**. Every
section digest matched the baseline and every headline number in the table
above reproduced exactly. The reorganize and the prune are behaviour-preserving.

Re-run at task 3.3 (entry logic extracted into `src/kernel/entries/`): **PASS,
9/9 runs identical** — all eight section digests match on every run.

The six original jobs alone would not have been enough evidence. They all run
with every gate off (`entry_on_cross_only` absent, `entry_mode` absent,
`session_filter_tz` absent, `adx_gate_min` absent), so `update()` and
`evaluate()` fire back to back with nothing between them and the two-phase
split is observationally identical to the fused original *by construction*.
The gated paths — the only reason the split exists — were untested. Hence the
three fixtures below, baselined at `8c2fc1a` (the task-3.3 parent) rather than
at `960282c`:

| run | job | exercises |
|---|---|---|
| donchian-gated-m5 | `configs/backtest/parity-donchian-gated-m5.yaml` | edge-triggered entries + session window: episode state must advance on gated bars |
| supertrend-gated-m5 | `configs/backtest/parity-supertrend-gated-m5.yaml` | gate-before-upkeep ordering + the ADX gate that sits after `evaluate()` |
| mean-reversion-recross-m5 | `configs/backtest/parity-mean-reversion-recross-m5.yaml` | re-cross entry (reads the prior bar) + `block_entry` policy |

| run | trades | net PnL | max DD |
|---|---|---|---|
| donchian-gated-m5 | 2094 | −31,120.41 | 38.45% |
| supertrend-gated-m5 | 841 | −19,345.16 | 22.40% |
| mean-reversion-recross-m5 | 1095 | −1,931.55 | 23.14% |

Re-run the gate after any further move under `src/` — the baseline stays valid
as long as the strategies and the parquet data underneath do not change.

One thing the baseline deliberately does **not** yet cover: Contract v2 still
writes `trade.entry.reason` as `null` and `trade.entry.kind` as the literal
`"market"` (`src/lab/export/result_writer.py`). The entry models now produce
real reasons (`donchian_upper_cross`, …) but nothing threads them into
`TradeRecord`. Wiring that up **will** change the `trades` digest by design —
re-cut the baseline in the same commit that does it.

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
