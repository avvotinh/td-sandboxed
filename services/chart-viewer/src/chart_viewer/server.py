"""FastAPI app for the local chart viewer.

Read-only over a ``results/`` directory of Result Contract v2 JSONs.
Pages are minimal server-rendered shells; the run/compare views pull
their data from the JSON API and draw with the vendored
lightweight-charts bundle in ``static/``. No Docker / DB (Decision D6).

Routes
------
* ``GET /``                        run-list page
* ``GET /run/{run_id}``            single-run chart page
* ``GET /compare?a=&b=``           two runs side by side
* ``GET /api/runs``                run summaries + scan warnings
* ``GET /api/run/{run_id}``        full viewer payload (no candles)
* ``GET /api/run/{run_id}/candles`` OHLCV from the run's parquet
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .candles import load_candles
from .payload import build_run_payload
from .results import RunSummary, ResultStore, UnknownRunError, is_valid_run_id

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _esc(value: Any) -> str:
    """HTML-escape any value for safe interpolation into markup."""
    return html.escape("" if value is None else str(value))


def _json_safe(obj: Any) -> Any:
    """Recursively replace non-finite floats with None.

    Real metrics carry ``inf`` (profit factor with zero losing trades)
    and occasionally ``nan``; strict JSON (Starlette, ``allow_nan=False``)
    rejects both. Coerce to ``null`` so the front-end renders them as
    "–" instead of the whole response failing.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "–"
    return f"{num:,.{digits}f}" if math.isfinite(num) else "–"


def _fmt_pct(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "–"
    return f"{100 * num:.1f}%" if math.isfinite(num) else "–"


_PAGE_CSS = """
  :root { --bg:#131722; --panel:#1e222d; --border:#2a2e39; --text:#d1d4dc;
          --muted:#787b86; --green:#26a69a; --red:#ef5350; --accent:#2962ff; }
  * { box-sizing:border-box; margin:0; padding:0; }
  html,body { height:100%; }
  body { background:var(--bg); color:var(--text);
         font:13px/1.45 -apple-system,"Segoe UI",Roboto,sans-serif; }
  a { color:var(--accent); text-decoration:none; }
  a:hover { text-decoration:underline; }
  .pos { color:var(--green); } .neg { color:var(--red); }
"""


def _list_row(s: RunSummary) -> str:
    net = s.net_pnl
    net_cls = "pos" if (net or 0) >= 0 else "neg"
    return (
        "<tr>"
        f'<td class="run"><a href="/run/{_esc(s.run_id)}">{_esc(s.run_id)}</a></td>'
        f"<td>{_esc(s.strategy)}</td>"
        f"<td>{_esc(s.symbol)}</td>"
        f"<td>{_esc(s.timeframe)}</td>"
        f"<td>{_esc(s.window_name)}</td>"
        f"<td>{s.trade_count}</td>"
        f'<td class="{net_cls}">{_fmt_num(net, 0) if net is not None else "–"}</td>'
        f"<td>{_fmt_pct(s.win_rate)}</td>"
        f"<td>{_fmt_num(s.profit_factor)}</td>"
        f"<td>{_fmt_num(s.sharpe_ratio, 3)}</td>"
        f"<td>{_fmt_pct(s.max_drawdown_pct)}</td>"
        "</tr>"
    )


def _render_list_page(store: ResultStore) -> str:
    summaries, warnings = store.scan()
    rows = "".join(_list_row(s) for s in summaries)
    if not summaries:
        rows = (
            '<tr><td colspan="11" style="text-align:center;color:var(--muted);'
            f'padding:24px">No Contract v2 results in {_esc(store.results_dir)}</td></tr>'
        )
    warn_html = ""
    if warnings:
        items = "".join(
            f"<li><code>{_esc(w.file_name)}</code> — {_esc(w.reason)}</li>" for w in warnings
        )
        warn_html = (
            '<details class="warn"><summary>'
            f"{len(warnings)} file(s) skipped</summary><ul>{items}</ul></details>"
        )
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest runs — chart-viewer</title>
<style>{_PAGE_CSS}
  .wrap {{ max-width:1200px; margin:0 auto; padding:20px; }}
  h1 {{ font-size:18px; margin-bottom:4px; }}
  .sub {{ color:var(--muted); margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--panel);
           border:1px solid var(--border); border-radius:6px; overflow:hidden; }}
  th,td {{ padding:7px 10px; text-align:right; white-space:nowrap; }}
  th {{ color:var(--muted); font-weight:500; font-size:11px; text-transform:uppercase;
        letter-spacing:.04em; border-bottom:1px solid var(--border); }}
  th:first-child,td:first-child {{ text-align:left; }}
  td.run {{ font-family:ui-monospace,monospace; }}
  tbody tr:hover {{ background:#2a2e3966; }}
  tbody tr {{ border-bottom:1px solid #ffffff08; }}
  .warn {{ margin-top:16px; color:var(--muted); }}
  .warn code {{ color:var(--text); }}
</style></head><body>
<div class="wrap">
  <h1>Backtest runs</h1>
  <div class="sub">{_esc(store.results_dir)} · Result Contract v2 · <a href="/compare">compare A/B →</a></div>
  <table><thead><tr>
    <th>run_id</th><th>strategy</th><th>symbol</th><th>tf</th><th>window</th>
    <th>trades</th><th>net pnl</th><th>win</th><th>PF</th><th>Sharpe</th><th>max DD</th>
  </tr></thead><tbody>{rows}</tbody></table>
  {warn_html}
</div></body></html>"""


def _render_run_page(run_id: str) -> str:
    """Chart shell — app.js reads ``__RUN_ID__`` and fetches the data."""
    rid_json = json.dumps(run_id)  # run_id is validated [A-Za-z0-9._-]
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(run_id)} — chart-viewer</title>
<style>{_PAGE_CSS}
  body {{ display:flex; flex-direction:column; overflow:hidden; }}
  header {{ display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
            padding:8px 14px; background:var(--panel); border-bottom:1px solid var(--border); }}
  header h1 {{ font-size:15px; font-weight:600; }}
  header h1 a {{ color:var(--muted); font-weight:400; }}
  header .stat {{ color:var(--muted); }}
  header .stat b {{ color:var(--text); font-weight:600; }}
  main {{ display:flex; flex:1; min-height:0; }}
  .chart-wrap {{ position:relative; flex:1; min-width:0; display:flex; }}
  #legend {{ position:absolute; z-index:10; top:8px; left:12px; font-size:12px;
             color:var(--muted); pointer-events:none; text-shadow:0 1px 2px #000; }}
  #note {{ position:absolute; z-index:10; top:8px; right:12px; font-size:11px;
           color:var(--muted); background:#00000066; padding:2px 6px; border-radius:3px; }}
  #chart {{ flex:1; min-width:0; }}
  aside {{ width:330px; display:flex; flex-direction:column; background:var(--panel);
           border-left:1px solid var(--border); }}
  aside h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.05em;
              color:var(--muted); padding:10px 12px 6px; }}
  #trades {{ flex:1; overflow-y:auto; }}
  table {{ width:100%; border-collapse:collapse; }}
  th,td {{ padding:4px 8px; text-align:right; white-space:nowrap; }}
  th {{ position:sticky; top:0; background:var(--panel); color:var(--muted);
        font-weight:500; font-size:11px; border-bottom:1px solid var(--border); }}
  th:first-child,td:first-child {{ text-align:left; }}
  tbody tr {{ cursor:pointer; border-bottom:1px solid #ffffff08; }}
  tbody tr:hover {{ background:#2a2e3966; }}
  tbody tr.sel {{ background:#2962ff33; }}
  .badge {{ display:inline-block; min-width:34px; text-align:center; padding:0 5px;
            border-radius:3px; font-size:11px; font-weight:600; }}
  .badge.buy {{ background:#26a69a33; color:var(--green); }}
  .badge.sell {{ background:#ef535033; color:var(--red); }}
  #detail {{ border-top:1px solid var(--border); padding:10px 12px; font-size:12px;
             min-height:116px; }}
  #detail .row {{ display:flex; justify-content:space-between; padding:1px 0; }}
  #detail .row span:first-child {{ color:var(--muted); }}
</style></head><body>
<header id="header"><h1><a href="/">runs</a> / …</h1></header>
<main>
  <div class="chart-wrap"><div id="legend"></div><div id="note"></div><div id="chart"></div></div>
  <aside>
    <h2>Trades</h2>
    <div id="trades"></div>
    <div id="detail"><span style="color:var(--muted)">Click a trade to inspect entry / SL / TP.</span></div>
  </aside>
</main>
<script>window.__RUN_ID__ = {rid_json};</script>
<script src="/static/lightweight-charts.standalone.production.js"></script>
<script src="/static/app.js"></script>
</body></html>"""


def _render_compare_page(store: ResultStore, a: str | None, b: str | None) -> str:
    if a and b:
        body = (
            '<div class="grid">'
            f'<iframe src="/run/{_esc(a)}"></iframe>'
            f'<iframe src="/run/{_esc(b)}"></iframe>'
            "</div>"
        )
    else:
        summaries, _ = store.scan()
        opts = "".join(f'<option value="{_esc(s.run_id)}">{_esc(s.run_id)}</option>' for s in summaries)
        body = f"""<form class="pick" method="get" action="/compare">
          <label>A <select name="a">{opts}</select></label>
          <label>B <select name="b">{opts}</select></label>
          <button type="submit">Compare</button>
        </form>"""
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — chart-viewer</title>
<style>{_PAGE_CSS}
  body {{ display:flex; flex-direction:column; height:100vh; }}
  .bar {{ padding:8px 14px; background:var(--panel); border-bottom:1px solid var(--border); }}
  .grid {{ flex:1; display:grid; grid-template-columns:1fr 1fr; min-height:0; }}
  .grid iframe {{ width:100%; height:100%; border:0; border-right:1px solid var(--border); }}
  .pick {{ padding:24px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
  .pick select {{ background:var(--bg); color:var(--text); border:1px solid var(--border);
                  border-radius:4px; padding:4px 6px; font-family:ui-monospace,monospace; }}
  .pick button {{ background:var(--accent); color:#fff; border:0; border-radius:4px;
                  padding:5px 12px; cursor:pointer; }}
</style></head><body>
<div class="bar"><a href="/">← runs</a> · compare A/B</div>
{body}
</body></html>"""


def create_app(store: ResultStore) -> FastAPI:
    """Build the FastAPI app bound to a :class:`ResultStore`."""
    app = FastAPI(title="chart-viewer", docs_url=None, redoc_url=None)
    app.state.store = store

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    def _require_run(run_id: str) -> dict[str, Any]:
        if not is_valid_run_id(run_id):
            raise HTTPException(status_code=400, detail="invalid run_id")
        try:
            return store.get(run_id)
        except UnknownRunError as exc:
            raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}") from exc

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _render_list_page(store)

    def _known_run(run_id: str | None) -> str | None:
        """A run_id only if it is well-formed and present, else None."""
        if run_id and is_valid_run_id(run_id):
            try:
                store.get(run_id)
                return run_id
            except UnknownRunError:
                return None
        return None

    @app.get("/compare", response_class=HTMLResponse)
    def compare(a: str | None = Query(None), b: str | None = Query(None)) -> str:
        # Validate like every other route; invalid/unknown → the picker.
        return _render_compare_page(store, _known_run(a), _known_run(b))

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    def run_page(run_id: str) -> str:
        _require_run(run_id)  # 404 before rendering a shell for a ghost run
        return _render_run_page(run_id)

    @app.get("/api/runs")
    def api_runs() -> JSONResponse:
        summaries, warnings = store.scan()
        return JSONResponse(
            _json_safe(
                {
                    "runs": [s.__dict__ for s in summaries],
                    "warnings": [w.__dict__ for w in warnings],
                }
            )
        )

    @app.get("/api/run/{run_id}")
    def api_run(run_id: str) -> JSONResponse:
        data = _require_run(run_id)
        return JSONResponse(_json_safe(build_run_payload(data)))

    @app.get("/api/run/{run_id}/candles")
    def api_candles(run_id: str) -> JSONResponse:
        data = _require_run(run_id)
        run = data.get("run") or {}
        result = load_candles(run.get("data_ref") or {}, run.get("window") or {})
        return JSONResponse(
            _json_safe(
                {
                    "candles": result.candles,
                    "note": result.note,
                    "resampledFactor": result.resampled_factor,
                }
            )
        )

    return app
