"""Technical indicators for trading strategies.

NautilusTrader-backed indicators are re-exported under shorter aliases so
strategies can write ``from src.indicators import ATR, RSI, Bollinger,
Donchian`` without deep Nautilus paths. Custom indicators not present in
Nautilus (``Supertrend``, ``ADX``, ``SessionVWAP``) are implemented in
this package and exported alongside.

All exports subclass ``nautilus_trader.indicators.base.Indicator`` so they
are compatible with ``Strategy.register_indicator_for_bars()``.
"""

from __future__ import annotations

from nautilus_trader.indicators.momentum import RelativeStrengthIndex as RSI
from nautilus_trader.indicators.volatility import (
    AverageTrueRange as ATR,
)
from nautilus_trader.indicators.volatility import (
    BollingerBands as Bollinger,
)
from nautilus_trader.indicators.volatility import (
    DonchianChannel as Donchian,
)

from src.indicators.adx import ADX
from src.indicators.session_vwap import SessionVWAP
from src.indicators.supertrend import Supertrend

__all__ = [
    "ADX",
    "ATR",
    "RSI",
    "Bollinger",
    "Donchian",
    "SessionVWAP",
    "Supertrend",
]
