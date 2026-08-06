"""Backtest strategy registry.

Maps a strategy name (as used in backtest job YAML) to the pair of
(config class, strategy class) needed to instantiate the strategy for a
Nautilus ``BacktestEngine``. Separate from the live-trading
``src.kernel.strategies.registry.StrategyRegistry`` on purpose: the live
registry dispatches by name only, whereas backtests need to build the
strategy config from a plain dict (sweep parameter overrides) which
requires the config class too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.kernel.strategies.bollinger_mean_reversion import (
    BollingerMeanReversionConfig,
    BollingerMeanReversionStrategy,
)
from src.kernel.strategies.donchian_breakout import (
    DonchianBreakoutConfig,
    DonchianBreakoutStrategy,
)
from src.kernel.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy
from src.kernel.strategies.mean_reversion import (
    MeanReversionConfig,
    MeanReversionStrategy,
)
from src.kernel.strategies.orb import ORBConfig, ORBStrategy
from src.kernel.strategies.rsi_mean_reversion import (
    RSIMeanReversionConfig,
    RSIMeanReversionStrategy,
)
from src.kernel.strategies.supertrend import SupertrendConfig, SupertrendStrategy

if TYPE_CHECKING:
    from nautilus_trader.config import StrategyConfig

    from src.kernel.strategies.base_strategy import BaseStrategy


class UnknownStrategyError(KeyError):
    """Raised when a backtest job references an unregistered strategy name."""


class ArchivedStrategyError(ValueError):
    """Raised when a LIVE caller resolves an archived strategy.

    ``regimes=[]`` archival only bites when regime gating is wired for
    the account; this error is the independent hard stop for the live
    path (Track 2 review follow-up) — an archived strategy must never
    trade real capital regardless of regime configuration.
    """


@dataclass(frozen=True, slots=True)
class StrategyEntry:
    """Registry entry: (config class, strategy class) pair.

    ``archived=True`` marks strategies retired from the active roster
    (Track 2, redesign plan 2026-07-02). They stay resolvable for
    backtest A/B re-runs but are refused on the live path
    (``resolve_strategy(..., allow_archived=False)``).
    """

    config_cls: type[StrategyConfig]
    strategy_cls: type[BaseStrategy]
    archived: bool = False


BACKTEST_STRATEGIES: Final[dict[str, StrategyEntry]] = {
    # Active roster (Track 2, redesign plan 2026-07-02).
    "supertrend": StrategyEntry(SupertrendConfig, SupertrendStrategy),
    "donchian_breakout": StrategyEntry(
        DonchianBreakoutConfig, DonchianBreakoutStrategy
    ),
    "mean_reversion": StrategyEntry(MeanReversionConfig, MeanReversionStrategy),
    # Archived (regimes=[] + archived=True; kept resolvable for A/B
    # re-runs of the old Phase 12.A reports — see the sizing-bug banners
    # in sprint-artifacts).
    "ma_crossover": StrategyEntry(
        MACrossoverConfig, MACrossoverStrategy, archived=True
    ),
    "rsi_mean_reversion": StrategyEntry(
        RSIMeanReversionConfig, RSIMeanReversionStrategy, archived=True
    ),
    "bollinger_mean_reversion": StrategyEntry(
        BollingerMeanReversionConfig, BollingerMeanReversionStrategy,
        archived=True,
    ),
    "orb": StrategyEntry(ORBConfig, ORBStrategy, archived=True),
}


def resolve_strategy(name: str, *, allow_archived: bool = True) -> StrategyEntry:
    """Return the ``StrategyEntry`` for ``name`` or raise.

    Args:
        name: Registered strategy name.
        allow_archived: ``True`` (default) serves backtest callers —
            archived strategies stay runnable for A/B re-runs against
            the banner-flagged Phase 12.A reports. The LIVE path
            (``node_factory``) passes ``False`` so an archived strategy
            can never be provisioned onto a real account, independent
            of whether regime gating is enabled there.

    Raises:
        UnknownStrategyError: ``name`` is not registered. The message
            lists known strategies so callers (and users) can fix typos.
        ArchivedStrategyError: ``name`` is archived and
            ``allow_archived=False``.
    """
    try:
        entry = BACKTEST_STRATEGIES[name]
    except KeyError as exc:
        known = ", ".join(sorted(BACKTEST_STRATEGIES.keys()))
        raise UnknownStrategyError(
            f"Unknown strategy {name!r}. Known: {known}"
        ) from exc
    if entry.archived and not allow_archived:
        active = ", ".join(
            sorted(n for n, e in BACKTEST_STRATEGIES.items() if not e.archived)
        )
        raise ArchivedStrategyError(
            f"Strategy {name!r} is ARCHIVED (Track 2, redesign plan "
            f"2026-07-02) and cannot run on the live path. Active: {active}"
        )
    return entry
