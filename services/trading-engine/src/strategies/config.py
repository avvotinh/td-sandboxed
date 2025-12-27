"""Base strategy configuration.

This module defines the configuration model for all trading strategies.
BaseStrategyConfig inherits from NautilusTrader's StrategyConfig to ensure
proper integration with the NautilusTrader framework.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId


class BaseStrategyConfig(StrategyConfig, frozen=True, kw_only=True):
    """Base configuration for all trading strategies.

    This configuration class is required for all strategies that inherit from
    BaseStrategy. It inherits from NautilusTrader's StrategyConfig to ensure
    proper framework integration.

    Note:
        The `frozen=True` parameter is MANDATORY for NautilusTrader StrategyConfig
        subclasses. This ensures configuration immutability after instantiation,
        which NautilusTrader requires for proper strategy lifecycle management
        and serialization.

    Attributes:
        instrument_id: Instrument to trade (e.g., "XAUUSD.BROKER")
        bar_type: Bar type for data subscription (e.g., "XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL")
        trade_size: Default trade quantity in lots
        account_id: Associated account ID for routing
        order_id_tag: Tag for order identification (default "001")
    """

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("0.1")
    account_id: str = ""
    order_id_tag: str = "001"
