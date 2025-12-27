"""Strategy registry for dynamic strategy loading.

This module provides a registry for trading strategies, enabling
configuration-driven strategy instantiation. Strategies are registered
by name and can be retrieved for use with specific accounts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.strategies.base_strategy import BaseStrategy


class StrategyRegistry:
    """Registry for dynamic strategy loading.

    Maintains a mapping of strategy names to strategy classes,
    enabling configuration-driven strategy instantiation.

    Example:
        # Register strategies
        StrategyRegistry.register("ma_crossover", MACrossoverStrategy)

        # Get strategy class from config
        strategy_class = StrategyRegistry.get(account.strategy)
        strategy = strategy_class(config)
    """

    _strategies: dict[str, type[BaseStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: type[BaseStrategy]) -> None:
        """Register a strategy class by name.

        Args:
            name: Strategy name (used in account config)
            strategy_class: Strategy class (must inherit BaseStrategy)

        Raises:
            ValueError: If name is empty or already registered
        """
        if not name:
            raise ValueError("Strategy name cannot be empty")
        if name in cls._strategies:
            raise ValueError(f"Strategy '{name}' is already registered")
        cls._strategies[name] = strategy_class

    @classmethod
    def get(cls, name: str) -> type[BaseStrategy]:
        """Get a registered strategy class by name.

        Args:
            name: Strategy name from configuration

        Returns:
            Strategy class

        Raises:
            ValueError: If strategy name not registered
        """
        if name not in cls._strategies:
            available = ", ".join(cls._strategies.keys()) or "none"
            raise ValueError(
                f"Strategy '{name}' not registered. Available: {available}"
            )
        return cls._strategies[name]

    @classmethod
    def list_available(cls) -> list[str]:
        """List all registered strategy names.

        Returns:
            List of registered strategy names
        """
        return list(cls._strategies.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a strategy is registered.

        Args:
            name: Strategy name to check

        Returns:
            True if strategy is registered
        """
        return name in cls._strategies

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a strategy by name.

        Args:
            name: Strategy name to unregister

        Returns:
            True if strategy was unregistered, False if not found
        """
        if name in cls._strategies:
            del cls._strategies[name]
            return True
        return False

    @classmethod
    def clear(cls) -> None:
        """Clear all registered strategies.

        Primarily used for testing.
        """
        cls._strategies.clear()


def register_strategy(name: str):
    """Decorator to register a strategy class.

    Example:
        @register_strategy("my_strategy")
        class MyStrategy(BaseStrategy):
            ...

    Args:
        name: Strategy name for registration

    Returns:
        Decorator function
    """
    def decorator(cls: type[BaseStrategy]) -> type[BaseStrategy]:
        StrategyRegistry.register(name, cls)
        return cls
    return decorator
