"""DataFrame → Nautilus Bar converter.

Thin wrapper over ``nautilus_trader.persistence.wranglers.BarDataWrangler``
that adds column-presence validation and a fast-path for empty frames.
"""

from __future__ import annotations

import pandas as pd
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.persistence.wranglers import BarDataWrangler


_REQUIRED_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


def dataframe_to_bars(
    df: pd.DataFrame,
    bar_type: BarType,
    instrument: Instrument,
) -> list[Bar]:
    """Convert an OHLCV DataFrame into a list of Nautilus Bars.

    Args:
        df: DataFrame indexed by a UTC-aware DatetimeIndex with columns
            ``open``, ``high``, ``low``, ``close``, ``volume``.
        bar_type: The Nautilus ``BarType`` to attach to every produced bar.
        instrument: Instrument providing tick-size / lot-size quantization.

    Returns:
        List of ``Bar`` objects of length ``len(df)``.

    Raises:
        ValueError: If required OHLCV columns are missing.
    """
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    if len(df) == 0:
        return []

    wrangler = BarDataWrangler(bar_type=bar_type, instrument=instrument)
    return wrangler.process(df)
