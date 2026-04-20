"""Backtest strategy registry.

Maps a strategy name (as used in backtest job YAML) to the pair of
(config class, strategy class) needed to instantiate the strategy for a
Nautilus ``BacktestEngine``. Separate from the live-trading
``src.strategies.registry.StrategyRegistry`` on purpose: the live
registry dispatches by name only, whereas backtests need to build the
strategy config from a plain dict (sweep parameter overrides) which
requires the config class too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.strategies.bollinger_mean_reversion import (
    BollingerMeanReversionConfig,
    BollingerMeanReversionStrategy,
)
from src.strategies.donchian_breakout import (
    DonchianBreakoutConfig,
    DonchianBreakoutStrategy,
)
from src.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy
from src.strategies.orb import ORBConfig, ORBStrategy
from src.strategies.rsi_mean_reversion import (
    RSIMeanReversionConfig,
    RSIMeanReversionStrategy,
)
from src.strategies.supertrend import SupertrendConfig, SupertrendStrategy

if TYPE_CHECKING:
    from nautilus_trader.config import StrategyConfig

    from src.strategies.base_strategy import BaseStrategy


class UnknownStrategyError(KeyError):
    """Raised when a backtest job references an unregistered strategy name."""


@dataclass(frozen=True, slots=True)
class StrategyEntry:
    """Registry entry: (config class, strategy class) pair."""

    config_cls: type[StrategyConfig]
    strategy_cls: type[BaseStrategy]


BACKTEST_STRATEGIES: Final[dict[str, StrategyEntry]] = {
    "ma_crossover": StrategyEntry(MACrossoverConfig, MACrossoverStrategy),
    "supertrend": StrategyEntry(SupertrendConfig, SupertrendStrategy),
    "donchian_breakout": StrategyEntry(
        DonchianBreakoutConfig, DonchianBreakoutStrategy
    ),
    "rsi_mean_reversion": StrategyEntry(
        RSIMeanReversionConfig, RSIMeanReversionStrategy
    ),
    "bollinger_mean_reversion": StrategyEntry(
        BollingerMeanReversionConfig, BollingerMeanReversionStrategy
    ),
    "orb": StrategyEntry(ORBConfig, ORBStrategy),
}


def resolve_strategy(name: str) -> StrategyEntry:
    """Return the ``StrategyEntry`` for ``name`` or raise.

    Raises:
        UnknownStrategyError: ``name`` is not registered. The message
            lists known strategies so callers (and users) can fix typos.
    """
    try:
        return BACKTEST_STRATEGIES[name]
    except KeyError as exc:
        known = ", ".join(sorted(BACKTEST_STRATEGIES.keys()))
        raise UnknownStrategyError(
            f"Unknown strategy {name!r}. Known: {known}"
        ) from exc
