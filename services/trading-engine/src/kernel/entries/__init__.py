"""Entry models — the entry half of a strategy, as composable units.

Roadmap task 3.3. An :class:`EntryModel` owns its indicators, its rolling
state, and its decision; the strategy keeps gates, exits, sizing, and
order submission. See :mod:`src.kernel.entries.base` for the two-phase
``update`` / ``evaluate`` contract that keeps the seam lookahead-safe.

Example:
    from src.kernel.entries import DonchianCrossEntry

    entry = DonchianCrossEntry(channel_period=20)
    ...
    if entry.update(bar):          # every bar, before evaluate
        intent = entry.evaluate()  # only on bars that survive the gates
"""

from src.kernel.entries.base import EntryModel
from src.kernel.entries.donchian_cross import DonchianCrossEntry
from src.kernel.entries.intent import EntryIntent, EntryKind, EntrySide
from src.kernel.entries.mr_band import ENTRY_MODES, MeanReversionBandEntry
from src.kernel.entries.supertrend_flip import SupertrendFlipEntry

__all__ = [
    "ENTRY_MODES",
    "DonchianCrossEntry",
    "EntryIntent",
    "EntryKind",
    "EntryModel",
    "EntrySide",
    "MeanReversionBandEntry",
    "SupertrendFlipEntry",
]
