Start the chart-viewer and print the URL. No Docker/DB needed — the viewer reads `results/*.json` + parquet directly (see skill: `chart-viewer`).

$ARGUMENTS is an optional run-id.

1. Check if the viewer is already running (port 8777 responding). If not, start it in the background:

```bash
cd services/chart-viewer && uv run chart-viewer --results-dir ../../results --port 8777
```

2. Print the URL:
   - No argument: `http://127.0.0.1:8777/` (run list)
   - With run-id: `http://127.0.0.1:8777/run/$ARGUMENTS`

If the given run-id has no matching `results/<run-id>.json`, list available runs from `results/` and ask which one to open.
