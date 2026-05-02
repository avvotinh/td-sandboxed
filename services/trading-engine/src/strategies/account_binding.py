"""Account-strategy binding for runtime strategy instantiation.

This module provides the mechanism to bind strategy instances to accounts
at runtime, enabling the StrategyDataRouter to route market data to the
correct strategy instances.

The AccountConfig (from accounts/models.py) defines the strategy as a string
name. This module bridges the gap by:
1. Looking up the strategy class from StrategyRegistry
2. Instantiating the strategy with proper configuration
3. Returning a BoundAccount that satisfies the HasStrategy protocol
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.strategies.registry import StrategyRegistry

if TYPE_CHECKING:
    from src.accounts.models import AccountConfig, SignalFilter
    from src.strategies.base_strategy import BaseStrategy
    from src.strategies.config import BaseStrategyConfig


@dataclass
class BoundAccount:
    """Account with instantiated strategy for runtime use.

    Wraps an AccountConfig with a live strategy instance, satisfying
    the HasStrategy protocol required by StrategyDataRouter.

    Attributes:
        config: The underlying account configuration
        strategy_instance: Instantiated strategy (None if not bound)

    Example:
        bound = bind_strategy_to_account(account_config, strategy_config)
        router = StrategyDataRouter([bound])
        redis_adapter.set_bar_callback(router.route_bar)
    """

    config: AccountConfig
    strategy_instance: BaseStrategy | None = None

    @property
    def status(self) -> str:
        """Account status (active, paused, stopped)."""
        return self.config.status

    @property
    def strategy(self) -> str:
        """Strategy name from configuration."""
        return self.config.strategy

    @property
    def signal_filter(self) -> SignalFilter:
        """Signal filtering rules."""
        return self.config.signal_filter

    @property
    def id(self) -> str:
        """Account ID."""
        return self.config.id

    @property
    def name(self) -> str:
        """Account name."""
        return self.config.name


def bind_strategy_to_account(
    account: AccountConfig,
    strategy_config: BaseStrategyConfig,
) -> BoundAccount:
    """Instantiate strategy and bind to account.

    Looks up the strategy class by name from StrategyRegistry,
    creates an instance with the provided configuration, and
    returns a BoundAccount ready for use with StrategyDataRouter.

    Args:
        account: Account configuration with strategy name
        strategy_config: Configuration for the strategy instance

    Returns:
        BoundAccount with instantiated strategy

    Raises:
        ValueError: If strategy name not registered in StrategyRegistry

    Example:
        from nautilus_trader.model.identifiers import InstrumentId
        from nautilus_trader.model.data import BarType

        config = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            account_id=account.id,
        )
        bound = bind_strategy_to_account(account, config)
    """
    strategy_class = StrategyRegistry.get(account.strategy)
    strategy = strategy_class(strategy_config)
    return BoundAccount(config=account, strategy_instance=strategy)


def bind_strategies_to_accounts(
    accounts: list[AccountConfig],
    strategy_configs: dict[str, BaseStrategyConfig],
) -> list[BoundAccount]:
    """Bind strategies to multiple accounts.

    Convenience function for binding strategies to a list of accounts.
    Each account's strategy is looked up in the strategy_configs dict
    by the account's strategy name.

    Args:
        accounts: List of account configurations
        strategy_configs: Dict mapping account IDs to strategy configs

    Returns:
        List of BoundAccount instances

    Raises:
        ValueError: If strategy not registered or config not provided
        KeyError: If account ID not in strategy_configs

    Example:
        configs = {
            "ftmo-main": BaseStrategyConfig(...),
            "ftmo-backup": BaseStrategyConfig(...),
        }
        bound_accounts = bind_strategies_to_accounts(accounts, configs)
        router = StrategyDataRouter(bound_accounts)
    """
    bound_accounts = []
    for account in accounts:
        if account.id not in strategy_configs:
            raise KeyError(
                f"No strategy config provided for account '{account.id}'"
            )
        bound = bind_strategy_to_account(account, strategy_configs[account.id])
        bound_accounts.append(bound)
    return bound_accounts
