"""EquityRecorderActor — per-bar equity curve, independent of compliance.

Historically the equity curve came as a side effect of
``PropFirmComplianceActor`` (gap G2 in ``docs/v2/00-analysis.md``): a
backtest without a ``prop_firm`` block produced an EMPTY curve and thus
empty drawdown/Sharpe metrics. This actor records equity per bar with
ZERO rule-engine / compliance coupling, so every run — research-loop
runs included — gets a populated curve.

The equity read mirrors the venue branch of
``PropFirmComplianceActor._read_equity`` exactly (venue → account →
``balance_total`` with ``initial_balance`` fallbacks) so the two curves
are identical when both actors are attached.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Currency

from src.lab.portfolio_equity import (
    read_account_balance,
    read_unrealized_pnl,
)


class EquityRecorderActorConfig(ActorConfig, frozen=True):
    """Config for :class:`EquityRecorderActor`.

    Attributes:
        initial_balance: Starting balance — the pre-fill / warm-up
            fallback when the portfolio has no account or balance yet.
        bar_type: ``BarType`` to subscribe to on start. ``None`` skips
            the subscription (unit-test path — the actor is driven via
            its public methods instead).
        venue: Venue whose account the equity is read from. ``None``
            makes ``on_bar`` a no-op (unit-test path).
        currency: Account currency for ``balance_total``.
    """

    initial_balance: Decimal
    bar_type: BarType | None = None
    venue: Venue | None = None
    currency: Currency = USD


class EquityRecorderActor(Actor):
    """Records ``(ts_utc, equity)`` per bar from the Nautilus portfolio."""

    def __init__(self, config: EquityRecorderActorConfig) -> None:
        super().__init__(config=config)
        self._config = config
        self._equity_curve: list[tuple[datetime, Decimal]] = []

    # ---- Public seams ------------------------------------------------------

    @property
    def equity_curve(self) -> list[tuple[datetime, Decimal]]:
        """Defensive copy of the recorded curve."""
        return list(self._equity_curve)

    def record_equity(self, *, ts: datetime, equity: Decimal) -> None:
        """Append a point to the equity curve."""
        self._equity_curve.append((ts, equity))

    # ---- Nautilus Actor lifecycle -----------------------------------------

    def on_start(self) -> None:
        """Subscribe to bars so Nautilus dispatches ``on_bar``."""
        if self._config.bar_type is not None:
            self.subscribe_bars(self._config.bar_type)

    def on_stop(self) -> None:
        """Unsubscribe cleanly.

        Catches only ``RuntimeError`` from ``unsubscribe_bars`` —
        Nautilus raises it when the actor is stopped before it fully
        subscribed (same guard as ``PropFirmComplianceActor``).
        """
        if self._config.bar_type is not None:
            try:
                self.unsubscribe_bars(self._config.bar_type)
            except RuntimeError:
                pass

    def on_bar(self, bar: Bar) -> None:
        """Per-bar hook — read portfolio equity and append to the curve."""
        equity = self._read_equity()
        if equity is None:
            return
        ts = datetime.fromtimestamp(bar.ts_init // 1_000_000_000, tz=UTC)
        self.record_equity(ts=ts, equity=equity)

    def _read_equity(self) -> Decimal | None:
        """Read true mark-to-market equity from the Nautilus portfolio.

        ``equity = realized balance + Σ unrealized PnL of open positions``.

        The balance read shares :func:`read_account_balance` with the
        prop-firm actor's venue branch (same warm-up fallbacks, no
        drift); the unrealized term makes intra-trade drawdown visible
        on the recorded curve — ``balance_total`` alone never moves
        while a position is open. Unrealized lookup failures degrade to
        the balance-only value (never crash the bar stream).

        No venue configured → ``None`` (unit-test path; ``on_bar``
        becomes a no-op).
        """
        if self._config.venue is None:
            return None
        balance = read_account_balance(
            self.portfolio,
            self._config.venue,
            self._config.currency,
            self._config.initial_balance,
        )
        return balance + read_unrealized_pnl(
            self.portfolio, self._config.venue, self._config.currency
        )
