"""Entry intent — what an :class:`~src.kernel.entries.base.EntryModel` decides.

The intent is deliberately *not* an order. It says which side to take, on
what evidence, and — for the quote-aware models of roadmap task 3.4 — at
what price and with what order kind. Turning that into a bracket order
(SL/TP, sizing, reversal handling) stays with the strategy.

``reason`` is the human-readable tag that Contract v2 carries on
``trade.entry.reason`` (``docs/v2/01-architecture.md`` §4), so it must
name the *evidence*, not the side: ``donchian_upper_cross``, not ``buy``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.kernel.signal import SignalType


class EntrySide(str, Enum):
    """Direction of an entry."""

    LONG = "LONG"
    SHORT = "SHORT"


class EntryKind(str, Enum):
    """How the entry reaches the book.

    ``MARKET`` is the only kind the bar-based models emit today. ``LIMIT``
    and ``STOP`` are the quote-aware kinds of task 3.4 (Decision D5) —
    defined here so the contract does not change under them later.
    """

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class EntryIntent:
    """An immutable entry decision for the bar just closed.

    Attributes:
        side: Direction to take.
        reason: Evidence tag, exported as ``trade.entry.reason``.
        kind: Order kind; ``MARKET`` needs no price, the others require one.
        price: Trigger/limit price for non-market kinds.
    """

    side: EntrySide
    reason: str
    kind: EntryKind = EntryKind.MARKET
    price: Decimal | None = None

    def __post_init__(self) -> None:
        """Reject intents the execution seam could not act on."""
        if not self.reason:
            raise ValueError("reason must not be empty")
        if self.kind is EntryKind.MARKET:
            if self.price is not None:
                raise ValueError("market entries must not carry a price")
        elif self.price is None:
            raise ValueError(f"{self.kind.value} entries require a price")
        elif not self.price.is_finite():
            # Must precede the comparison: Decimal("NaN") <= 0 raises
            # InvalidOperation, not ValueError. A quote-aware model (3.4)
            # computing a limit price off an indicator that is still
            # warming up is exactly how a NaN gets here.
            raise ValueError(f"price must be finite, got {self.price}")
        elif self.price <= 0:
            raise ValueError(f"price must be positive, got {self.price}")

    @property
    def signal_type(self) -> SignalType:
        """The legacy :class:`SignalType` this intent maps onto.

        The bridge that lets strategies adopt ``EntryModel`` without
        rewriting ``_execute_signal`` in the same step.
        """
        return SignalType.BUY if self.side is EntrySide.LONG else SignalType.SELL

    @classmethod
    def market(cls, side: EntrySide, reason: str) -> EntryIntent:
        """Shorthand for the bar-based models' market entry."""
        return cls(side=side, reason=reason, kind=EntryKind.MARKET)
