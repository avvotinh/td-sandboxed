"""BacktestResult and companion dataclasses for backtest output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.lab.metrics.schema import PropFirmMetricsSchema


@dataclass(frozen=True)
class SlUpdate:
    """One stop-loss modification (breakeven move / trailing ratchet)."""

    ts: datetime
    price: Decimal


@dataclass(frozen=True)
class TradeRecord:
    """Single closed trade in backtest output.

    ``sl_price`` / ``tp_price`` are the bracket's initial stop-loss and
    take-profit levels; ``sl_updates`` is the chronological history of
    SL modifications (breakeven move, trailing ratchets). All three are
    ``None``/empty when the trade was not bracket-managed or the order
    legs could not be recovered from the engine cache — consumers must
    treat them as best-effort enrichment, not guaranteed fields.
    """

    trade_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    entry_ts: datetime
    exit_ts: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal
    sl_price: Decimal | None = None
    tp_price: Decimal | None = None
    sl_updates: tuple[SlUpdate, ...] = ()


@dataclass(frozen=True)
class IndicatorSeries:
    """One recorded indicator line series (Result Contract v2).

    ``pane`` is ``"overlay"`` for price-chart overlays or a named lower
    pane (e.g. ``"rsi"``). ``points`` are chronological ``(ts, value)``
    pairs recorded during the run by ``IndicatorRecorder`` — never
    recomputed after the fact. ``levels`` are horizontal reference
    lines for lower panes (e.g. RSI 0.3/0.7 thresholds).
    """

    key: str
    title: str
    pane: str  # "overlay" | pane name
    color: str
    points: tuple[tuple[datetime, float], ...]
    levels: tuple[float, ...] = ()


@dataclass(frozen=True)
class BreachEvent:
    """Prop-firm rule-engine breach captured during backtest."""

    ts: datetime
    rule_name: str
    current_value: float
    threshold_value: float
    message: str


@dataclass(frozen=True)
class BacktestResult:
    """Aggregated backtest output.

    ``config_snapshot`` (Epic 12 Decision §7) carries provenance the
    validation report needs to be reproducible — typically dataset
    fingerprint(s), strategy params, and venue/fee settings as captured
    at run time. The field is optional; only the validation-campaign
    harness populates it. Backtests that don't care can leave it at the
    default ``None`` and read it as such.
    """

    strategy_name: str
    start: datetime
    end: datetime
    initial_balance: Decimal
    final_balance: Decimal
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    breaches: list[BreachEvent] = field(default_factory=list)
    indicators: tuple[IndicatorSeries, ...] = ()
    metrics: PropFirmMetricsSchema | None = None
    config_snapshot: dict[str, Any] | None = None
