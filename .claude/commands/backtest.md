Run a point backtest from a job YAML and export the Result Contract v2 JSON.

$ARGUMENTS is the path to a job YAML (e.g. `configs/backtest/epic13-donchian-baseline-m5.yaml`, relative to `services/trading-engine/`).

```bash
cd services/trading-engine && uv run python -m src backtest run --job $ARGUMENTS --export ../../results/
```

Then report:
1. The `run_id` (printed as `Contract v2 result written to ... (run_id=...)`)
2. The exported path: `results/<run_id>.json` (repo root, gitignored — do NOT commit)
3. One-line metrics summary from the CLI output: net PnL, trades, win rate, max overall DD

If the run fails, show the error and check the job YAML against `src/lab/job_config.py` (see skill: `strategy-lab`). To inspect the run visually, suggest `/viewer <run-id>`.
