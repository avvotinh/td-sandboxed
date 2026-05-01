"""Prop-firm compliance actor for backtest.

The actor wires the Epic 4 rule engine into a Nautilus backtest via the
``Actor`` extension point — no modifications to strategies or to the rule
engine itself. Per epic-8-context.md decision #2: placing compliance
inside strategies would violate SRP and force every new strategy to
re-wire the rules; using an Actor mirrors the live ``signal_router`` →
``RuleEngine`` → ``mt5-bridge`` path.

In backtest we cannot prevent a fill once Nautilus has accepted the order
(the engine is synchronous in its event loop). Instead, the actor is a
**reactive compliance tracker**: on each bar it computes equity from the
portfolio snapshot, invokes the rule engine, and records breach events
(deduplicated by ``(date, rule_name)``). Downstream metrics reflect what
*would* have been blocked in live trading.

Epic 9 rename: ``FtmoComplianceActor`` → ``PropFirmComplianceActor``. The
actor itself is firm-agnostic; specific prop-firm thresholds come from
the rule engine it was constructed with.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Currency

from src.backtesting.account_state_builder import build_account_state
from src.backtesting.result import BreachEvent
from src.rules.base_rule import RuleAction
from src.rules.engine import RuleEngine
from src.snapshots.daily_profit_history import DailyProfitHistory
from src.strategies.mixins.session_filter_mixin import SessionFilterMixin

# Story 10.5d — live mode pulls equity from the engine's per-account
# state (``PnLTrackerRegistry`` / ``RiskStateRegistry``), not from the
# Nautilus ``Portfolio``. The orchestrator wires a closure of this
# shape; ``None`` return means "no equity yet" and the actor skips the
# tick (same as the warm-up branch in backtest).
LiveEquityProvider = Callable[[str], Decimal | None]


class PropFirmComplianceActorConfig(ActorConfig, frozen=True):
    """Config for ``PropFirmComplianceActor``.

    Attributes:
        account_id: Identifier passed into the rule engine context.
        initial_balance: Starting balance of the backtest (for DD
            calculations and prop-firm percentage metrics).
        daily_session_tz: IANA timezone whose midnight marks a new
            trading day for daily-loss deduplication.
        bar_type: Optional ``BarType`` to subscribe to on_start. When
            ``None`` the actor does not subscribe — used for unit tests
            where the actor is exercised via its public methods directly.
    """

    account_id: str
    initial_balance: Decimal
    daily_session_tz: str = "UTC"
    bar_type: BarType | None = None
    venue: Venue | None = None
    currency: Currency = USD


class PropFirmComplianceActor(Actor):
    """Reactive prop-firm compliance tracker subscribed to bars + order events."""

    def __init__(
        self,
        config: PropFirmComplianceActorConfig,
        rule_engine: RuleEngine,
        equity_provider: LiveEquityProvider | None = None,
    ) -> None:
        super().__init__(config=config)
        self._config = config
        self._rule_engine = rule_engine
        # Story 10.5d — when wired by :class:`LiveOrchestrator` the
        # provider is a closure over :class:`PnLTrackerRegistry`. Backtest
        # leaves it ``None`` and falls back to the Nautilus portfolio.
        self._equity_provider = equity_provider
        self._breaches: list[BreachEvent] = []
        # Dedup keyed by the trading-day *session id* (local date in
        # ``daily_session_tz``) — so broker rollover at 22:00 UTC with a
        # CET session groups correctly instead of splitting across two
        # UTC dates.
        self._dedup: set[tuple[str, str]] = set()
        self._equity_curve: list[tuple[datetime, Decimal]] = []
        self._peak_balance: Decimal = config.initial_balance
        # Per-day open balance — resets when the UTC date rolls over so the
        # rule engine sees *today's* P&L, not cumulative since inception.
        self._current_day: date | None = None
        self._day_open_balance: Decimal = config.initial_balance
        # Last per-bar daily P&L, used at day-rollover to record the just-
        # ended day into _profit_history (Epic 9 P0.7 — consistency rule).
        self._last_daily_pnl: Decimal = Decimal("0")
        self._profit_history = DailyProfitHistory()

    # ---- Public test seams -------------------------------------------------

    @property
    def breaches(self) -> list[BreachEvent]:
        return list(self._breaches)

    @property
    def equity_curve(self) -> list[tuple[datetime, Decimal]]:
        return list(self._equity_curve)

    @property
    def peak_balance(self) -> Decimal:
        return self._peak_balance

    def record_equity(self, *, ts: datetime, equity: Decimal) -> None:
        """Append a point to the equity curve and update the high-water mark."""
        self._equity_curve.append((ts, equity))
        if equity > self._peak_balance:
            self._peak_balance = equity

    def register_completed_day(self, day: date, daily_pnl: Decimal) -> None:
        """Record a finished day's P&L into the rolling profit history.

        Called by ``on_bar`` at day rollover, and exposed publicly for tests
        and for callers that drive the actor without a Nautilus event loop.
        """
        self._profit_history.record(self._config.account_id, day, daily_pnl)

    @property
    def daily_profits_history(self) -> dict[date, float]:
        """Snapshot of completed prior days' P&L for context injection.

        Returns a defensive copy keyed by date.
        """
        return self._profit_history.get_history(self._config.account_id)

    def evaluate_compliance(
        self,
        account_state: Mapping[str, Any],
        ts: datetime,
    ) -> list[BreachEvent]:
        """Invoke the rule engine and return newly-blocked results as breaches.

        Does NOT apply deduplication or append to ``self._breaches`` — that
        happens in :meth:`record_compliance_check`. This split makes the
        rule-engine invocation independently testable.
        """
        signal = _BarSignal()
        context = {
            "account_id": self._config.account_id,
            "timestamp": ts,
            "signal": signal,
            "symbol": None,
            "side": None,
            "quantity": 0,
            "current_balance": account_state.get("balance", Decimal("0")),
            "current_equity": account_state.get("equity", Decimal("0")),
            **account_state,
        }
        result = self._rule_engine.validate(context, continue_after_block=True)
        breaches: list[BreachEvent] = []
        for rule, rule_result in result.all_results:
            if rule_result.action != RuleAction.BLOCK:
                continue
            breaches.append(
                BreachEvent(
                    ts=ts,
                    rule_name=getattr(rule, "name", rule.rule_type),
                    current_value=float(rule_result.current_value or 0.0),
                    threshold_value=float(rule_result.threshold_value or 0.0),
                    message=rule_result.message or "rule blocked",
                )
            )
        return breaches

    def record_compliance_check(
        self,
        account_state: Mapping[str, Any],
        ts: datetime,
    ) -> None:
        """Evaluate rules and dedupe-append breaches to the actor's log.

        Deduplication buckets by the **session id** in
        ``config.daily_session_tz`` so a daily-loss breach registers once
        per prop-firm trading day, not once per UTC date.
        """
        new_breaches = self.evaluate_compliance(account_state, ts)
        session_id = SessionFilterMixin.session_id(ts, self._config.daily_session_tz)
        for event in new_breaches:
            key = (session_id, event.rule_name)
            if key in self._dedup:
                continue
            self._dedup.add(key)
            self._breaches.append(event)

    # ---- Nautilus Actor lifecycle -----------------------------------------

    def on_start(self) -> None:
        """Subscribe to bars so Nautilus will dispatch ``on_bar``."""
        if self._config.bar_type is not None:
            self.subscribe_bars(self._config.bar_type)

    def on_stop(self) -> None:
        """Unsubscribe cleanly and flush the final trading day.

        Without the flush, the last day of a backtest never reaches the
        rolling profit history (rollover only fires on the next day's
        first bar). This would silently drop the final day from
        ``daily_profits_history``.

        Catches only ``RuntimeError`` from ``unsubscribe_bars`` — Nautilus
        raises this when the actor is stopped before it fully subscribed
        (e.g. immediate shutdown). Any other exception is a programming
        error and propagates.
        """
        if self._current_day is not None:
            self.register_completed_day(self._current_day, self._last_daily_pnl)
            self._current_day = None
            self._last_daily_pnl = Decimal("0")
        if self._config.bar_type is not None:
            try:
                self.unsubscribe_bars(self._config.bar_type)
            except RuntimeError:
                pass

    def on_bar(self, bar: Bar) -> None:
        """Per-bar hook wired by ``subscribe_bars`` in ``on_start``."""
        ts = datetime.fromtimestamp(bar.ts_init // 1_000_000_000, tz=UTC)
        equity = self._read_equity()
        if equity is None:
            return
        self.record_equity(ts=ts, equity=equity)

        # Reset day-open balance on UTC date change for proper daily_pnl.
        # On rollover, persist the day that just ended into the rolling
        # profit history so the consistency rule sees it on subsequent ticks.
        bar_date = ts.date()
        if self._current_day is None:
            self._current_day = bar_date
            self._day_open_balance = equity
        elif bar_date != self._current_day:
            self.register_completed_day(self._current_day, self._last_daily_pnl)
            self._current_day = bar_date
            self._day_open_balance = equity
            self._last_daily_pnl = Decimal("0")

        daily_pnl = equity - self._day_open_balance
        self._last_daily_pnl = daily_pnl
        snapshot = {
            "balance": equity,
            "equity": equity,
            "open_positions": 0,
            "total_exposure": 0,
        }
        account_state = build_account_state(
            portfolio_snapshot=snapshot,
            initial_balance=self._config.initial_balance,
            peak_balance=self._peak_balance,
            daily_pnl=daily_pnl,
        )
        # Inject consistency-rule context (Epic 9 P0.7).
        account_state["current_day_pnl"] = daily_pnl
        account_state["daily_profits_history"] = self.daily_profits_history
        self.record_compliance_check(account_state, ts)

    def _read_equity(self) -> Decimal | None:
        """Read current equity for the rule-engine context.

        Resolution order:

        1. ``equity_provider`` — live mode (story 10.5d). The orchestrator
           passes a closure over :class:`PnLTrackerRegistry` so the actor
           sees the same equity the rest of the engine acts on. The
           provider may return ``None`` during warm-up (no tracker yet);
           we skip the tick rather than substituting a stale fallback.
           **Note:** the provider, once set, fully shadows the venue
           branch even when it returns ``None``. This is intentional —
           live mode must never silently read the Nautilus portfolio
           (which can drift from MT5 mid-reconciliation).
        2. Nautilus ``Portfolio`` keyed by ``config.venue`` — backtest
           path. Pre-fill bars or missing ``balance_total`` fall back to
           ``config.initial_balance`` so the equity curve still populates.
        3. ``None`` — no live provider and no venue (unit-test path); the
           caller (``on_bar``) skips the rule check.
        """
        if self._equity_provider is not None:
            return self._equity_provider(self._config.account_id)

        if self._config.venue is None:
            # Unit-test path — no portfolio wiring available.
            return None
        account = self.portfolio.account(self._config.venue)
        if account is None:
            # Pre-fill warm-up: fall back to starting balance.
            return self._config.initial_balance
        balance = account.balance_total(self._config.currency)
        if balance is None:
            return self._config.initial_balance
        return Decimal(str(balance.as_double()))


class _BarSignal:
    """Duck-typed signal object for rule-engine context (bar-driven check)."""

    symbol = None
    side = None
    quantity = 0
