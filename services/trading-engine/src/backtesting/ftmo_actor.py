"""FTMO compliance actor for backtest.

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
"""

from __future__ import annotations

from collections.abc import Mapping
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
from src.strategies.mixins.session_filter_mixin import SessionFilterMixin


class FtmoComplianceActorConfig(ActorConfig, frozen=True):
    """Config for ``FtmoComplianceActor``.

    Attributes:
        account_id: Identifier passed into the rule engine context.
        initial_balance: Starting balance of the backtest (for DD
            calculations and FTMO-percentage metrics).
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


class FtmoComplianceActor(Actor):
    """Reactive FTMO compliance tracker subscribed to bars + order events."""

    def __init__(
        self,
        config: FtmoComplianceActorConfig,
        rule_engine: RuleEngine,
    ) -> None:
        super().__init__(config=config)
        self._config = config
        self._rule_engine = rule_engine
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
        per FTMO trading day, not once per UTC date.
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
        """Unsubscribe cleanly to suppress Nautilus warnings.

        Catches only ``RuntimeError`` — Nautilus raises this when the
        actor is stopped before it fully subscribed (e.g. immediate
        shutdown). Any other exception is a programming error and
        propagates.
        """
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
        bar_date = ts.date()
        if self._current_day is None or bar_date != self._current_day:
            self._current_day = bar_date
            self._day_open_balance = equity

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
            daily_pnl=equity - self._day_open_balance,
        )
        self.record_compliance_check(account_state, ts)

    def _read_equity(self) -> Decimal | None:
        """Read current equity from the attached Nautilus ``Portfolio``.

        Returns the live ``balance_total`` from the account attached to the
        configured venue. During the first bars of a backtest — before any
        fill has registered the account — the portfolio returns ``None``,
        in which case we fall back to the configured ``initial_balance`` so
        the equity curve remains populated. Returns ``None`` only when
        the actor was configured without a ``venue`` (unit-test path).
        """
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
