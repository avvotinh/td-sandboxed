"""Unit tests for the Epic 16 fetch-campaign pure core (story 16.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.lab.dataset.fetch_campaign import (
    build_fetch_argv,
    chunk_path,
    to_oanda_symbol,
    tv_timeframe,
)


@pytest.mark.unit
class TestSymbolMapping:
    def test_bare_ticker_gets_oanda_prefix(self) -> None:
        assert to_oanda_symbol("XAUUSD") == "OANDA:XAUUSD"
        assert to_oanda_symbol("USDJPY") == "OANDA:USDJPY"

    def test_already_prefixed_is_idempotent(self) -> None:
        assert to_oanda_symbol("OANDA:EURUSD") == "OANDA:EURUSD"


@pytest.mark.unit
class TestTimeframeMapping:
    @pytest.mark.parametrize(
        ("label", "tv"),
        [("M5", "5"), ("M15", "15"), ("H1", "60"), ("H4", "240")],
    )
    def test_known_labels(self, label: str, tv: str) -> None:
        assert tv_timeframe(label) == tv

    def test_unknown_label_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            tv_timeframe("D1")


@pytest.mark.unit
class TestChunkPath:
    def test_layout_and_padding(self) -> None:
        p = chunk_path(Path("/data"), "XAUUSD", "H1", "in_sample", 7)
        assert p == Path("/data/historical/XAUUSD/H1/in_sample/007.parquet")

    def test_uses_bare_ticker_not_colon(self) -> None:
        # Colon is illegal in Windows paths; the OANDA: prefix must never
        # reach the filesystem layer.
        p = chunk_path(Path("/data"), "USDJPY", "M5", "oos_reserve", 0)
        assert ":" not in str(p.relative_to("/data"))


@pytest.mark.unit
class TestBuildFetchArgv:
    def _argv(self, **over) -> list[str]:
        base = dict(
            cli_path="./bin/tv-cli",
            oanda_symbol="OANDA:XAUUSD",
            tv_tf="60",
            from_dt=datetime(2021, 1, 1, tzinfo=UTC),
            to_dt=datetime(2026, 1, 1, tzinfo=UTC),
            out_path=Path("/data/historical/XAUUSD/H1/in_sample/000.parquet"),
            spec_name="xauusd-5y",
            dataset_version="1.0.0",
            window_name="in_sample",
            window_kind="in_sample",
        )
        base.update(over)
        return build_fetch_argv(**base)

    def test_replay_mode_flag_present_by_default(self) -> None:
        assert "-replay-mode" in self._argv()

    def test_replay_mode_omitted_when_false(self) -> None:
        assert "-replay-mode" not in self._argv(replay_mode=False)

    def test_rfc3339_z_timestamps(self) -> None:
        argv = self._argv()
        assert "2021-01-01T00:00:00Z" in argv
        assert "2026-01-01T00:00:00Z" in argv

    def test_carries_symbol_timeframe_and_out(self) -> None:
        argv = self._argv()
        # adjacency: each flag immediately precedes its value
        assert argv[argv.index("-symbol") + 1] == "OANDA:XAUUSD"
        assert argv[argv.index("-timeframe") + 1] == "60"
        assert argv[argv.index("-out") + 1].endswith("000.parquet")
        assert argv[argv.index("-command") + 1] == "backtest-fetch"

    def test_response_timeout_default_avoids_2s_flake(self) -> None:
        # tv-cli's own default (2000) intermittently fails on the ReplayMode
        # initial batch; the builder must pass a generous default + honour
        # an override.
        argv = self._argv()
        assert argv[argv.index("-response-timeout-ms") + 1] == "8000"
        override = self._argv(response_timeout_ms=12000)
        assert override[override.index("-response-timeout-ms") + 1] == "12000"

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            self._argv(from_dt=datetime(2021, 1, 1))  # noqa: DTZ001
