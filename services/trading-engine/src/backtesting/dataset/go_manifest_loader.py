"""Merge per-shard JSON manifests emitted by the tv-api Go CLI.

Story 12.7.0d — bridge layer between the Go backtest-fetch tool and
the Python ``DatasetPipeline`` consumer.

The Go CLI (``tv-cli -command backtest-fetch``) writes one Parquet
shard plus a single-entry sidecar manifest per invocation. Operators
typically run the CLI four times for a XAUUSD validation campaign —
M5+M15 × in_sample+oos_reserve — producing four sidecars. This module
loads those sidecars and merges them into the canonical
:class:`DatasetManifest` shape that ``DatasetPipeline.materialize_async``
already understands.

The merged manifest is identical to what Python would have produced
itself: same fingerprint formula, same field ordering. The only
difference is provenance — the bars came from TradingView free-tier
via FakeReplay rather than a vendor API.

Cross-service contract: ``trading-engine`` cannot import from
``tv-api`` (sandboxed-domain rule). The artefact files are the
single contract.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest


def _reject_traversal(paths: list[Path]) -> None:
    """Reject sidecar paths containing ``..`` segments — defence in depth.

    ``DatasetManifest.load_json`` already validates the ``parquet_path``
    field inside each entry; this guards the sidecar file path itself,
    which is operator-supplied via the ``--sidecar`` CLI flag.
    """
    for p in paths:
        if any(part == ".." for part in p.parts):
            raise ValueError(f"merge_go_manifests: refusing sidecar path with '..': {p}")


def merge_go_manifests(
    sidecar_paths: list[Path],
    *,
    spec_name: str | None = None,
    dataset_version: str | None = None,
) -> DatasetManifest:
    """Combine N single-entry Go-written manifests into one.

    Args:
        sidecar_paths: Paths to ``*.parquet.manifest.json`` files
            produced by ``tv-cli backtest-fetch``.
        spec_name: Optional override for the resulting manifest's
            ``spec_name``. When ``None``, all input sidecars must agree
            on a value or :class:`ValueError` is raised.
        dataset_version: Same semantics as ``spec_name`` for the
            ``dataset_version`` field.

    Returns:
        A merged :class:`DatasetManifest` whose ``entries`` is the
        concatenation (in input order) of every sidecar's single
        entry. The returned object is the same shape Python would have
        produced if the bars had been materialised via the native
        ``DatasetPipeline``.

    Raises:
        ValueError: when no sidecars are provided, when input sidecars
            disagree on ``symbol`` or ``max_gap_hours`` (those must be
            consistent for the merge to be meaningful), or when the
            schema_version is unrecognised.
    """
    if not sidecar_paths:
        raise ValueError("merge_go_manifests: at least one sidecar is required")

    _reject_traversal(sidecar_paths)
    parsed: list[DatasetManifest] = [
        DatasetManifest.load_json(p) for p in sidecar_paths
    ]

    symbols = {m.symbol for m in parsed}
    if len(symbols) != 1:
        raise ValueError(
            f"merge_go_manifests: sidecars disagree on symbol: {sorted(symbols)}"
        )
    max_gap_hours = {m.max_gap_hours for m in parsed}
    if len(max_gap_hours) != 1:
        raise ValueError(
            "merge_go_manifests: sidecars disagree on max_gap_hours: "
            f"{sorted(max_gap_hours)}"
        )

    if spec_name is None:
        spec_names = {m.spec_name for m in parsed}
        if len(spec_names) != 1:
            raise ValueError(
                "merge_go_manifests: sidecars disagree on spec_name; "
                f"pass spec_name= explicitly. Got: {sorted(spec_names)}"
            )
        spec_name = next(iter(spec_names))

    if dataset_version is None:
        versions = {m.dataset_version for m in parsed}
        if len(versions) != 1:
            raise ValueError(
                "merge_go_manifests: sidecars disagree on dataset_version; "
                f"pass dataset_version= explicitly. Got: {sorted(versions)}"
            )
        dataset_version = next(iter(versions))

    entries: list[DatasetEntry] = []
    for m in parsed:
        entries.extend(m.entries)

    return DatasetManifest(
        spec_name=spec_name,
        dataset_version=dataset_version,
        symbol=next(iter(symbols)),
        generated_at=datetime.now(UTC),
        max_gap_hours=next(iter(max_gap_hours)),
        entries=tuple(entries),
    )


def _cli() -> int:
    """Command-line entry point: ``python -m src.backtesting.dataset.go_manifest_loader``."""
    parser = argparse.ArgumentParser(
        description="Merge per-shard tv-api Go manifests into one DatasetManifest.",
    )
    parser.add_argument(
        "--sidecar",
        action="append",
        required=True,
        help="Path to a single-entry manifest sidecar (repeatable).",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output path for the merged manifest JSON.",
    )
    parser.add_argument(
        "--spec-name",
        default=None,
        help="Override the merged spec_name (defaults to the unanimous sidecar value).",
    )
    parser.add_argument(
        "--dataset-version",
        default=None,
        help="Override the merged dataset_version (defaults to the unanimous sidecar value).",
    )
    args = parser.parse_args()

    paths = [Path(s) for s in args.sidecar]
    merged = merge_go_manifests(
        paths,
        spec_name=args.spec_name,
        dataset_version=args.dataset_version,
    )
    out = Path(args.out)
    merged.save_json(out)
    # CLI summary line — kept on stdout so operators can pipe it into
    # shell tooling. Internal service code should use logging instead.
    print(  # noqa: T201
        f"merged {len(paths)} sidecars → {out} ({merged.total_rows} rows)"
    )
    return 0


__all__ = ["merge_go_manifests"]


if __name__ == "__main__":
    raise SystemExit(_cli())
