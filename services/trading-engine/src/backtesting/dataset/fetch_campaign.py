"""Epic 16 fetch-campaign planning — pure, credential-free core.

The orchestration script (``scripts/fetch_campaign.py``) shells out to the
Go ``tv-cli`` per chunk and reads Parquet min-timestamps to step the
``-to`` anchor backward (the server caps ~5500 bars per anchor, so a
multi-year window needs a series of stepped calls — see
``docs/runbooks/backtest-data-fetch.md``). This module holds the logic it
composes that needs neither network nor credentials, so it is unit-tested
in isolation:

* symbol mapping — dataset bare ticker ↔ TradingView ``OANDA:`` prefix,
* timeframe mapping — :class:`DatasetSpec` label → ``tv-cli -timeframe``,
* chunk path layout under the data root,
* ``tv-cli`` argv construction for one chunk.

De-duplication of the overlapping stepped chunks into a single canonical
shard Parquet + manifest is **not** done here — it is owned by
``scripts/stitch_chunks_to_window.py`` (the canonical tool per
``docs/runbooks/backtest-data-fetch.md``), which the driver invokes per
shard.

All prices are sourced from OANDA (per the project's TradingView feed), so
every symbol fetches as ``OANDA:<TICKER>``; ``tv-cli``'s ``deriveSymbolKey``
strips the prefix back to the bare ticker that ``configs/datasets/*.yaml``
and the manifest use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

OANDA_PREFIX = "OANDA:"

# DatasetSpec timeframe label → TradingView ``-timeframe`` value. Epic 16
# acquires intraday only; the minute encodings match what the tv-cli
# FakeReplay / ReplayMode path expects (H1 = 60, H4 = 240).
_TF_TO_TV: dict[str, str] = {
    "M5": "5",
    "M15": "15",
    "H1": "60",
    "H4": "240",
}


def to_oanda_symbol(ticker: str) -> str:
    """Map a bare dataset ticker to the exchange-prefixed fetch symbol.

    ``"XAUUSD"`` → ``"OANDA:XAUUSD"``. Idempotent: an already-prefixed
    value (or any ``EXCHANGE:`` form) is returned unchanged so the driver
    can accept either.
    """
    if ":" in ticker:
        return ticker
    return f"{OANDA_PREFIX}{ticker}"


def tv_timeframe(tf_label: str) -> str:
    """Map a :class:`DatasetSpec` timeframe label to the tv-cli value.

    Raises ``ValueError`` for labels outside the Epic 16 acquisition set
    so a typo in a dataset spec fails loudly rather than fetching the
    wrong timeframe.
    """
    try:
        return _TF_TO_TV[tf_label]
    except KeyError:
        known = ", ".join(sorted(_TF_TO_TV))
        raise ValueError(
            f"Unsupported timeframe label {tf_label!r}. Known: {known}"
        ) from None


def chunk_path(
    data_root: Path, ticker: str, tf_label: str, window_name: str, idx: int
) -> Path:
    """Return the Parquet path for one stepped chunk.

    Layout: ``<root>/historical/<TICKER>/<TF>/<window>/<NNN>.parquet`` —
    the bare ticker (not the OANDA-prefixed form, which carries a ``:``
    illegal in Windows paths) and a zero-padded chunk index so a glob
    sorts in fetch order.
    """
    return (
        data_root
        / "historical"
        / ticker
        / tf_label
        / window_name
        / f"{idx:03d}.parquet"
    )


def _rfc3339_z(dt: datetime) -> str:
    """Format a tz-aware datetime as ``2024-01-01T00:00:00Z`` (Go RFC3339)."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_fetch_argv(
    *,
    cli_path: str,
    oanda_symbol: str,
    tv_tf: str,
    from_dt: datetime,
    to_dt: datetime,
    out_path: Path,
    spec_name: str,
    dataset_version: str,
    window_name: str,
    window_kind: str,
    replay_mode: bool = True,
) -> list[str]:
    """Build the ``tv-cli backtest-fetch`` argv for one stepped chunk.

    ``replay_mode`` defaults to ``True`` because Epic 16 fetches on a
    premium account, where ReplayMode returns a wider per-anchor intraday
    window than free-tier FakeReplay (fewer total calls). The ``-out``
    path is rendered as a string so the caller controls absolute vs
    relative (the driver passes absolute paths because tv-cli runs with
    cwd = ``services/tv-api`` to pick up its ``.env``).
    """
    argv = [cli_path, "-command", "backtest-fetch"]
    if replay_mode:
        argv.append("-replay-mode")
    argv += [
        "-symbol", oanda_symbol,
        "-timeframe", tv_tf,
        "-from", _rfc3339_z(from_dt),
        "-to", _rfc3339_z(to_dt),
        "-spec-name", spec_name,
        "-dataset-version", dataset_version,
        "-window-name", window_name,
        "-window-kind", window_kind,
        "-out", str(out_path),
    ]
    return argv


__all__ = [
    "OANDA_PREFIX",
    "to_oanda_symbol",
    "tv_timeframe",
    "chunk_path",
    "build_fetch_argv",
]
