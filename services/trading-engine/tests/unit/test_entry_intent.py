"""Unit tests for the EntryIntent value object (roadmap task 3.3).

The intent is what an ``EntryModel`` hands back: which side, on what
evidence, as what order kind. Its validation exists so a malformed
intent fails at construction rather than at order submission — a limit
entry with no price would otherwise reach the bracket seam as a silent
market order.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.kernel.entries import EntryIntent, EntryKind, EntrySide
from src.kernel.signal import SignalType


pytestmark = pytest.mark.unit


class TestConstruction:
    def test_market_shorthand_defaults_to_market_kind(self) -> None:
        intent = EntryIntent.market(EntrySide.LONG, "donchian_upper_cross")
        assert intent.kind is EntryKind.MARKET
        assert intent.price is None
        assert intent.reason == "donchian_upper_cross"

    def test_reason_is_required(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            EntryIntent(side=EntrySide.LONG, reason="")

    def test_market_entry_rejects_a_price(self) -> None:
        # A price on a market entry means the caller expected it to be
        # honoured; silently dropping it would misprice the backtest.
        with pytest.raises(ValueError, match="must not carry a price"):
            EntryIntent(
                side=EntrySide.LONG,
                reason="donchian_upper_cross",
                kind=EntryKind.MARKET,
                price=Decimal("2400"),
            )

    @pytest.mark.parametrize("kind", [EntryKind.LIMIT, EntryKind.STOP])
    def test_non_market_entry_requires_a_price(self, kind: EntryKind) -> None:
        with pytest.raises(ValueError, match="require a price"):
            EntryIntent(side=EntrySide.LONG, reason="pullback", kind=kind)

    @pytest.mark.parametrize("kind", [EntryKind.LIMIT, EntryKind.STOP])
    def test_price_must_be_positive(self, kind: EntryKind) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            EntryIntent(
                side=EntrySide.LONG,
                reason="pullback",
                kind=kind,
                price=Decimal("0"),
            )

    def test_quote_aware_kinds_construct(self) -> None:
        # Task 3.4 will emit these; the contract is settled now so it
        # does not shift under the quote-aware models later.
        intent = EntryIntent(
            side=EntrySide.SHORT,
            reason="upper_band_limit",
            kind=EntryKind.LIMIT,
            price=Decimal("2420.5"),
        )
        assert intent.price == Decimal("2420.5")


class TestImmutability:
    def test_intent_is_frozen(self) -> None:
        intent = EntryIntent.market(EntrySide.LONG, "supertrend_flip_up")
        with pytest.raises(Exception):  # noqa: B017 — dataclasses raise FrozenInstanceError
            intent.side = EntrySide.SHORT  # type: ignore[misc]


class TestSignalBridge:
    """The bridge that lets strategies adopt EntryModel incrementally."""

    def test_long_maps_to_buy(self) -> None:
        assert (
            EntryIntent.market(EntrySide.LONG, "x").signal_type == SignalType.BUY
        )

    def test_short_maps_to_sell(self) -> None:
        assert (
            EntryIntent.market(EntrySide.SHORT, "x").signal_type == SignalType.SELL
        )
