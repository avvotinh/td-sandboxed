"""Unit tests for the backtest strategy registry (Story 8.8)."""

from __future__ import annotations

import pytest

from src.backtesting.strategy_registry import (
    BACKTEST_STRATEGIES,
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
