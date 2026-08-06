"""Strategy registry for dynamic strategy loading.

This module provides a registry for trading strategies, enabling
configuration-driven strategy instantiation. Strategies are registered
by name and can be retrieved for use with specific accounts.

Story 11.6 added a per-strategy regime declaration (``regimes=[...]``);
Epic 15 routes that declaration through :meth:`StrategyRegistry.get_regimes`
into :class:`BaseStrategy._allowed_regimes` so the strategy's entry seam
gates on the live :class:`~regime.actor.RegimeActor`'s published state.
A missing ``regimes`` kwarg means "always-allow" (the regime kill-switch
still blocks the entry seam in HIGH_VOLATILITY); ``regimes=[]`` means
"never route" — the explicit Phase 1 opt-out for ORB.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from src.kernel.regime.states import RegimeState

if TYPE_CHECKING:
    from src.kernel.strategies.base_strategy import BaseStrategy


def _normalise_regimes(
    regimes: Iterable[RegimeState] | None,
) -> frozenset[RegimeState] | None:
    if regimes is None:
        return None
    declared = frozenset(regimes)
    if RegimeState.UNKNOWN in declared:
        # UNKNOWN is the warmup-only sentinel — declaring it as a routing
        # target would let the strategy run on undefined indicator state.
        raise ValueError(
            "RegimeState.UNKNOWN is not a valid routing regime "
            "(it is the classifier's warmup sentinel)"
        )
    return declared


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
    _strategy_regimes: dict[str, frozenset[RegimeState] | None] = {}

    @classmethod
    def register(
        cls,
        name: str,
        strategy_class: type[BaseStrategy],
        *,
        regimes: Iterable[RegimeState] | None = None,
    ) -> None:
        """Register a strategy class by name.

        Args:
            name: Strategy name (used in account config)
            strategy_class: Strategy class (must inherit BaseStrategy)
            regimes: Optional iterable of regime states the strategy is
                allowed to trade in. ``None`` (or omitting the kwarg)
                means "always-allow" — the kill-switch still applies in
                HIGH_VOLATILITY. ``[]`` means "never route" (explicit
                opt-out, e.g. ORB Phase 1).

        Raises:
            ValueError: If name is empty, already registered, or
                ``regimes`` contains :class:`RegimeState.UNKNOWN`.
        """
        if not name:
            raise ValueError("Strategy name cannot be empty")
        if name in cls._strategies:
            raise ValueError(f"Strategy '{name}' is already registered")
        normalised = _normalise_regimes(regimes)
        cls._strategies[name] = strategy_class
        cls._strategy_regimes[name] = normalised

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
            cls._strategy_regimes.pop(name, None)
            return True
        return False

    @classmethod
    def clear(cls) -> None:
        """Clear all registered strategies.

        Primarily used for testing.
        """
        cls._strategies.clear()
        cls._strategy_regimes.clear()

    @classmethod
    def get_regimes(cls, name: str) -> frozenset[RegimeState] | None:
        """Return the regime mapping declared for ``name``.

        Returns:
            ``None`` if the strategy registered without a ``regimes``
            kwarg (always-allow); otherwise the declared frozenset
            (which may be empty for "never route").

        Raises:
            ValueError: If ``name`` is not registered.
        """
        if name not in cls._strategies:
            available = ", ".join(cls._strategies.keys()) or "none"
            raise ValueError(
                f"Strategy '{name}' not registered. Available: {available}"
            )
        # Direct key access (not .get): if the two maps ever desync, raise
        # KeyError loudly rather than masking a missing entry as the
        # always-allow sentinel.
        return cls._strategy_regimes[name]


def register_strategy(
    name: str,
    *,
    regimes: Iterable[RegimeState] | None = None,
) -> Callable[[type[BaseStrategy]], type[BaseStrategy]]:
    """Decorator to register a strategy class.

    Example:
        @register_strategy(
            "supertrend",
            regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
        )
        class SupertrendStrategy(BaseStrategy):
            ...

    Args:
        name: Strategy name for registration.
        regimes: Optional regime allow-list. See
            :meth:`StrategyRegistry.register` for semantics.

    Returns:
        Decorator function.
    """
    def decorator(cls: type[BaseStrategy]) -> type[BaseStrategy]:
        StrategyRegistry.register(name, cls, regimes=regimes)
        return cls
    return decorator
