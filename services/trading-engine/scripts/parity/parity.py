"""P3 parity gate — fingerprint Contract v2 results so before/after reorg can be compared.

Two fields are volatile by construction and are excluded from the fingerprint:
  * ``run.run_id``        — embeds the wall-clock time of the run
  * ``run.engine.commit`` — changes with every reorg commit, by design

Everything else (params, window, data_ref, account, trades, equity curve,
indicators, metrics, breaches) must be byte-identical across the reorganize.

Usage (from services/trading-engine/):
    python parity.py hash  <result.json> [...]        # print per-section digests
    python parity.py diff  <before.json> <after.json> # localize a mismatch
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SECTIONS = (
    "schema_version",
    "run",
    "account",
    "trades",
    "equity_curve",
    "indicators",
    "metrics",
    "breaches",
)


def load(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    run = doc.get("run")
    if isinstance(run, dict):
        run.pop("run_id", None)
        engine = run.get("engine")
        if isinstance(engine, dict):
            engine.pop("commit", None)
    return doc


def digest(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def fingerprint(doc: dict[str, Any]) -> dict[str, str]:
    return {name: digest(doc.get(name)) for name in SECTIONS}


def cmd_hash(paths: list[str]) -> int:
    for path in paths:
        doc = load(path)
        fp = fingerprint(doc)
        overall = digest([fp[name] for name in SECTIONS])
        print(f"\n{Path(path).name}  [{overall}]")
        print(f"  trades={len(doc.get('trades') or [])}  equity={len(doc.get('equity_curve') or [])}")
        for name in SECTIONS:
            print(f"  {name:<16} {fp[name]}")
    return 0


def _describe(before: Any, after: Any, trail: str, out: list[str], depth: int = 0) -> None:
    """Walk two mismatching values and report the first few concrete differences."""
    if len(out) >= 12 or depth > 6:
        return
    if type(before) is not type(after):
        out.append(f"{trail}: type {type(before).__name__} -> {type(after).__name__}")
        return
    if isinstance(before, dict):
        for key in sorted(set(before) | set(after)):
            if key not in before:
                out.append(f"{trail}.{key}: added ({after[key]!r:.60})")
            elif key not in after:
                out.append(f"{trail}.{key}: removed ({before[key]!r:.60})")
            elif before[key] != after[key]:
                _describe(before[key], after[key], f"{trail}.{key}", out, depth + 1)
        return
    if isinstance(before, list):
        if len(before) != len(after):
            out.append(f"{trail}: length {len(before)} -> {len(after)}")
        for idx, (lhs, rhs) in enumerate(zip(before, after)):
            if lhs != rhs:
                _describe(lhs, rhs, f"{trail}[{idx}]", out, depth + 1)
                if len(out) >= 12:
                    return
        return
    out.append(f"{trail}: {before!r} -> {after!r}")


def cmd_diff(before_path: str, after_path: str) -> int:
    before, after = load(before_path), load(after_path)
    fp_before, fp_after = fingerprint(before), fingerprint(after)

    bad = [name for name in SECTIONS if fp_before[name] != fp_after[name]]
    if not bad:
        print(f"PARITY OK  {Path(before_path).name} == {Path(after_path).name}")
        return 0

    print(f"PARITY FAIL  {Path(before_path).name} != {Path(after_path).name}")
    for name in bad:
        print(f"\n  section {name}: {fp_before[name]} -> {fp_after[name]}")
        detail: list[str] = []
        _describe(before.get(name), after.get(name), name, detail)
        for line in detail:
            print(f"    {line}")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "hash":
        return cmd_hash(argv[2:])
    if argv[1] == "diff" and len(argv) == 4:
        return cmd_diff(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
