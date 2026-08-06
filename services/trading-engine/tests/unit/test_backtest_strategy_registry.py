"""Unit tests for the backtest strategy registry (Story 8.8 + Track 2)."""

from __future__ import annotations

import pytest

from src.lab.strategy_registry import (
    BACKTEST_STRATEGIES,
    ArchivedStrategyError,
    StrategyEntry,
    UnknownStrategyError,
    resolve_strategy,
)


@pytest.mark.unit
class TestBacktestStrategyRegistry:
    def test_known_strategies_registered(self) -> None:
        expected = {
            "ma_crossover",
            "supertrend",
            "donchian_breakout",
            "rsi_mean_reversion",
            "bollinger_mean_reversion",
            "mean_reversion",
            "orb",
        }
        assert expected <= set(BACKTEST_STRATEGIES.keys())

    def test_entries_carry_config_and_strategy_classes(self) -> None:
        for name, entry in BACKTEST_STRATEGIES.items():
            assert isinstance(entry, StrategyEntry), name
            assert entry.config_cls is not None, name
            assert entry.strategy_cls is not None, name

    def test_resolve_returns_entry(self) -> None:
        entry = resolve_strategy("ma_crossover")
        assert entry is BACKTEST_STRATEGIES["ma_crossover"]

    def test_unknown_strategy_raises_with_known_names(self) -> None:
        with pytest.raises(UnknownStrategyError) as exc:
            resolve_strategy("does_not_exist")
        msg = str(exc.value)
        assert "does_not_exist" in msg
        assert "ma_crossover" in msg  # listing helps the user fix the typo


@pytest.mark.unit
class TestArchivedRoster:
    """Track 2 roster contract (redesign plan 2026-07-02)."""

    def test_active_roster(self) -> None:
        active = {n for n, e in BACKTEST_STRATEGIES.items() if not e.archived}
        assert active == {"supertrend", "donchian_breakout", "mean_reversion"}

    def test_archived_roster(self) -> None:
        archived = {n for n, e in BACKTEST_STRATEGIES.items() if e.archived}
        assert archived == {
            "ma_crossover",
            "rsi_mean_reversion",
            "bollinger_mean_reversion",
            "orb",
        }

    def test_archived_resolvable_by_default_for_ab_reruns(self) -> None:
        entry = resolve_strategy("ma_crossover")
        assert entry.archived is True

    def test_archived_refused_on_live_path(self) -> None:
        with pytest.raises(ArchivedStrategyError, match="ARCHIVED"):
            resolve_strategy("ma_crossover", allow_archived=False)

    def test_active_allowed_on_live_path(self) -> None:
        entry = resolve_strategy("mean_reversion", allow_archived=False)
        assert entry.archived is False
