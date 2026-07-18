"""Route-level tests via FastAPI TestClient."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chart_viewer.results import ResultStore
from chart_viewer.server import create_app

RUN_ID = "donchian_breakout-xauusd-m5-20260101-000000"


@pytest.fixture
def client(results_dir: Path) -> TestClient:
    return TestClient(create_app(ResultStore(results_dir)))


def test_index_lists_run(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert RUN_ID in resp.text
    assert "1 file(s) skipped" in resp.text  # the foreign-schema warning


def test_api_runs(client: TestClient) -> None:
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["run_id"] for r in body["runs"]] == [RUN_ID]
    assert body["warnings"][0]["file_name"] == "foreign.json"


def test_api_run_payload(client: TestClient) -> None:
    resp = client.get(f"/api/run/{RUN_ID}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["meta"]["runId"] == RUN_ID
    assert len(payload["trades"]) == 1
    assert len(payload["indicators"]) == 1


def test_api_run_unknown_404(client: TestClient) -> None:
    assert client.get("/api/run/ghost-run").status_code == 404


def test_api_run_invalid_400(client: TestClient) -> None:
    # traversal-y id is rejected before any filesystem touch
    assert client.get("/api/run/..%2f..%2fetc").status_code in (400, 404)


def test_api_candles_synthetic_note(client: TestClient) -> None:
    resp = client.get(f"/api/run/{RUN_ID}/candles")
    assert resp.status_code == 200
    body = resp.json()
    assert body["candles"] == []
    assert "synthetic" in body["note"]


def test_api_run_sanitizes_non_finite_metrics(results_dir: Path) -> None:
    # profit_factor = inf (zero losing trades) must not blow up JSON encoding.
    import json

    path = results_dir / f"{RUN_ID}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["metrics"]["pnl"]["profit_factor"] = float("inf")
    path.write_text(json.dumps(data), encoding="utf-8")

    client = TestClient(create_app(ResultStore(results_dir)))
    resp = client.get(f"/api/run/{RUN_ID}")
    assert resp.status_code == 200
    assert resp.json()["meta"]["profitFactor"] is None
    assert client.get("/api/runs").status_code == 200


def test_run_page_renders_shell(client: TestClient) -> None:
    resp = client.get(f"/run/{RUN_ID}")
    assert resp.status_code == 200
    assert "/static/app.js" in resp.text
    assert RUN_ID in resp.text


def test_run_page_unknown_404(client: TestClient) -> None:
    assert client.get("/run/ghost-run").status_code == 404


def test_compare_picker_without_params(client: TestClient) -> None:
    resp = client.get("/compare")
    assert resp.status_code == 200
    assert "<form" in resp.text and RUN_ID in resp.text


def test_compare_with_params_embeds_iframes(client: TestClient) -> None:
    resp = client.get(f"/compare?a={RUN_ID}&b={RUN_ID}")
    assert resp.status_code == 200
    assert resp.text.count("<iframe") == 2


def test_compare_invalid_params_fall_back_to_picker(client: TestClient) -> None:
    # Unknown / malformed run_ids must not become iframe srcs.
    resp = client.get(f"/compare?a={RUN_ID}&b=ghost-run")
    assert resp.status_code == 200
    assert "<iframe" not in resp.text
    assert "<form" in resp.text
