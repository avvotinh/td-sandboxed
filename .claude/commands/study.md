Run a complete study cycle: backtests → verdict markdown in `docs/v2/studies/`.

$ARGUMENTS is the study slug (e.g. `donchian-m5-oos-check`).

1. **Quant gate first**: if NEW strategy/entry/exit model code was written for this study, run the `quant-reviewer` subagent on it BEFORE running backtests — backtest results of unreviewed models must not be trusted (anti-lookahead rule, `.claude/rules/common/sandboxed-domain.md`).

2. **Run the backtests** for the study — point runs, A/B matrix, or walk-forward as the study requires (see skill: `strategy-lab`), always with `--export ../../results/` so every cell produces a Contract v2 JSON with a `run_id`:

```bash
cd services/trading-engine && uv run python -m src backtest run --job <job.yaml> --export ../../results/
```

3. **Generate the verdict**: invoke the `backtest-analyst` subagent with the study slug and the list of run_ids produced. It writes `docs/v2/studies/$ARGUMENTS-<yyyy-mm-dd>.md`, compares against promotion gate D7 (OOS Sharpe ≥ 0.8 + WF pass + acceptable DD — `docs/v2/decisions.md`), and MUST attach a `run_id` to every cited number.

4. Report: verdict file path, headline conclusion (promote / not promoted / needs OOS), and the run_ids involved. Remind that `results/` is gitignored — only the verdict markdown gets committed.
