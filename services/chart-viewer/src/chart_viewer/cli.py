"""``chart-viewer`` entry point.

    uv run chart-viewer --results-dir <repo-root>/results --port 8777

Reads Result Contract v2 JSONs from ``--results-dir`` and serves the
viewer locally. No Docker / DB (Decision D6). An optional positional
``run_id`` just prints the direct run URL alongside the index.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .results import ResultStore, is_valid_run_id
from .server import create_app


def _default_results_dir() -> Path:
    """Repo-root ``results/`` — the exporter's default output directory."""
    from .paths import repo_root

    return repo_root() / "results"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chart-viewer",
        description="Local viewer for Result Contract v2 backtest runs.",
    )
    parser.add_argument(
        "run_id", nargs="?", default=None,
        help="optional run_id — print its direct URL on startup",
    )
    parser.add_argument(
        "--results-dir", type=Path, default=None,
        help="directory of results/*.json (default: <repo-root>/results)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8777, help="bind port (default: 8777)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results_dir = (args.results_dir or _default_results_dir()).resolve()
    store = ResultStore(results_dir)

    if not results_dir.is_dir():
        print(f"warning: results dir does not exist yet: {results_dir}", file=sys.stderr)

    base = f"http://{args.host}:{args.port}"
    print(f"chart-viewer -> {base}/   (results: {results_dir})")
    if args.run_id:
        if not is_valid_run_id(args.run_id):
            print(f"warning: ignoring invalid run_id: {args.run_id}", file=sys.stderr)
        else:
            print(f"           {base}/run/{args.run_id}")

    import uvicorn

    app = create_app(store)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
