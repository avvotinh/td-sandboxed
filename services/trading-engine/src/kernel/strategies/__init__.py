"""Strategies module - Trading strategies.

This module provides the core strategy framework for the trading engine:
- BaseStrategy: Abstract base class for all trading strategies
- BaseStrategyConfig: Configuration for strategy initialization
- PositionSizer: Position sizing calculations based on risk parameters
- StrategyRegistry: Dynamic strategy registration and loading
- BoundAccount: Account with instantiated strategy for runtime use
- bind_strategy_to_account: Instantiate and bind strategy to account

Example:
    from src.kernel.strategies import (
        BaseStrategy,
        BaseStrategyConfig,
        PositionSizer,
        PositionSizerConfig,
        StrategyRegistry,
        register_strategy,
        bind_strategy_to_account,
        BoundAccount,
    )

    @register_strategy("my_strategy")
    class MyStrategy(BaseStrategy):
        def generate_signal(self, bar) -> SignalType:
            return SignalType.NONE

    # Bind strategy to account at runtime
    bound = bind_strategy_to_account(account_config, strategy_config)
"""

from src.kernel.strategies.account_binding import (
    BoundAccount,
    bind_strategies_to_accounts,
    bind_strategy_to_account,
)
from src.kernel.strategies.base_strategy import BaseStrategy
from src.kernel.strategies.config import BaseStrategyConfig
from src.kernel.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy
from src.kernel.strategies.position_sizer import PositionSizer, PositionSizerConfig
from src.kernel.strategies.registry import StrategyRegistry, register_strategy

__all__ = [
    "BaseStrategy",
    "BaseStrategyConfig",
    "BoundAccount",
    "MACrossoverConfig",
    "MACrossoverStrategy",
    "PositionSizer",
    "PositionSizerConfig",
    "StrategyRegistry",
    "bind_strategies_to_accounts",
    "bind_strategy_to_account",
    "register_strategy",
]
