"""BacktestRunner — thin façade over ``nautilus_trader.backtest.BacktestEngine``.

The runner's job is to compose a backtest in a way that keeps the rest of
our stack (rule engine, strategies, prop-firm metrics) independent of
Nautilus internals. Composition order matters — ``add_venue`` must precede
``add_instrument``, and the prop-firm compliance actor must be attached
before ``run()``.

For unit-level tests the underlying engine is mocked. End-to-end
correctness is covered by ``tests/integration/test_backtest_smoke.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.objects import Currency
from pydantic import BaseModel, ConfigDict, Field

from src.backtesting.prop_firm_actor import (
    PropFirmComplianceActor,
    PropFirmComplianceActorConfig,
)
from src.backtesting.prop_firm_preset import PropFirmPreset
from src.backtesting.metrics.calculator import calculate_metrics
from src.backtesting.result import BacktestResult, TradeRecord

if TYPE_CHECKING:
    from nautilus_trader.model.identifiers import Venue

    from src.rules.engine import RuleEngine


class BacktestRunnerConfig(BaseModel):
    """Configuration for a single backtest run.

    Prefer :meth:`from_preset` over passing prop-firm threshold fields
    directly so the backtest shares the same compliance numbers the
    live rule engine enforces (see
    ``.claude/rules/common/sandboxed-domain.md``).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    strategy_name: str
    initial_balance: Decimal = Field(..., gt=0)
    currency: str = "USD"
    profit_target_pct: float = 10.0
    max_dd_pct: float = 10.0
    min_trading_days: int = 4

    @classmethod
    def from_preset(
        cls,
        *,
        strategy_name: str,
        initial_balance: Decimal,
        preset: PropFirmPreset,
        currency: str = "USD",
    ) -> BacktestRunnerConfig:
        """Build a config whose prop-firm thresholds come from ``preset``."""
        return cls(
            strategy_name=strategy_name,
            initial_balance=initial_balance,
            currency=currency,
            profit_target_pct=preset.profit_target_pct,
            max_dd_pct=preset.max_drawdown_pct,
            min_trading_days=preset.min_trading_days,
        )


class BacktestRunner:
    """Façade orchestrating a Nautilus backtest with prop-firm compliance."""

    def __init__(self, config: BacktestRunnerConfig) -> None:
        self.config = config
        self._engine: BacktestEngine = BacktestEngine(config=BacktestEngineConfig())
        self._prop_firm_actor: PropFirmComplianceActor | None = None
        self._start: datetime | None = None
        self._end: datetime | None = None

    @property
    def engine(self) -> BacktestEngine:
        return self._engine

    @property
    def prop_firm_actor(self) -> PropFirmComplianceActor | None:
        return self._prop_firm_actor

    # ---- Composition ------------------------------------------------------

    def add_venue(self, **kwargs: Any) -> None:
        """Add a simulated venue. Must be called before ``add_instrument``."""
        self._engine.add_venue(**kwargs)

    def add_instrument(self, instrument: Any) -> None:
        self._engine.add_instrument(instrument)

    def add_data(self, data: Any) -> None:
        self._engine.add_data(data)

    def add_strategy(self, strategy: Any) -> None:
        self._engine.add_strategy(strategy)

    def attach_prop_firm_compliance(
        self,
        *,
        rule_engine: RuleEngine,
        account_id: str,
        daily_session_tz: str = "UTC",
        bar_type: Any = None,
        venue: Venue | None = None,
        currency: Currency = USD,
    ) -> PropFirmComplianceActor:
        """Build + register an ``PropFirmComplianceActor`` against this engine.

        ``bar_type`` is the ``BarType`` the actor should subscribe to on
        start — pass the same ``BarType`` you used for ``add_data``. When
        omitted the actor still registers but won't receive on_bar events;
        useful when tests exercise the actor via its public methods only.

        ``venue`` + ``currency`` let the actor read real equity from the
        portfolio. When omitted (unit-test path) equity reads return
        ``None`` and ``on_bar`` is a no-op.
        """
        actor_config = PropFirmComplianceActorConfig(
            account_id=account_id,
            initial_balance=self.config.initial_balance,
            daily_session_tz=daily_session_tz,
            bar_type=bar_type,
            venue=venue,
            currency=currency,
        )
        actor = PropFirmComplianceActor(config=actor_config, rule_engine=rule_engine)
        self._engine.add_actor(actor)
        self._prop_firm_actor = actor
        return actor

    # ---- Execution --------------------------------------------------------

    def run(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        """Run the backtest. ``start``/``end`` forwarded to Nautilus."""
        self._start = start
        self._end = end
        kwargs: dict[str, Any] = {}
        if start is not None:
            kwargs["start"] = start
        if end is not None:
            kwargs["end"] = end
        self._engine.run(**kwargs)

    def get_result(self, *, final_balance: Decimal) -> BacktestResult:
        """Assemble a ``BacktestResult`` from engine + actor state."""
        equity_curve = (
            self._prop_firm_actor.equity_curve if self._prop_firm_actor is not None else []
        )
        breaches = (
            self._prop_firm_actor.breaches if self._prop_firm_actor is not None else []
        )
        trades = self._extract_trades()

        start = self._start or (
            equity_curve[0][0] if equity_curve else datetime.now()
        )
        end = self._end or (
            equity_curve[-1][0] if equity_curve else start
        )

        metrics = calculate_metrics(
            strategy_name=self.config.strategy_name,
            initial_balance=self.config.initial_balance,
            final_balance=final_balance,
            equity_curve=equity_curve,
            trades=trades,
            breaches=breaches,
            profit_target_pct=self.config.profit_target_pct,
            max_dd_pct=self.config.max_dd_pct,
            min_trading_days=self.config.min_trading_days,
        )

        return BacktestResult(
            strategy_name=self.config.strategy_name,
            start=start,
            end=end,
            initial_balance=self.config.initial_balance,
            final_balance=final_balance,
            equity_curve=equity_curve,
            trades=trades,
            breaches=breaches,
            metrics=metrics,
        )

    def _extract_trades(self) -> list[TradeRecord]:
        """Convert Nautilus closed positions into our ``TradeRecord`` list.

        Only fully-closed positions contribute — open positions have no
        ``avg_px_close`` or ``realized_pnl`` yet. Ns timestamps are
        converted to UTC-aware datetimes via ``datetime.fromtimestamp`` so
        TradeRecord.entry_ts / exit_ts stay tz-aware.
        """
        try:
            positions = self._engine.cache.positions_closed()
        except Exception:
            # Cache may be empty or unavailable mid-construction — return [].
            return []

        records: list[TradeRecord] = []
        for pos in positions:
            side = "BUY" if pos.side == PositionSide.LONG else "SELL"
            entry_ts = datetime.fromtimestamp(
                pos.ts_opened // 1_000_000_000, tz=UTC
            )
            exit_ts = datetime.fromtimestamp(
                (pos.ts_closed or pos.ts_last) // 1_000_000_000, tz=UTC
            )
            records.append(
                TradeRecord(
                    trade_id=str(pos.id),
                    symbol=str(pos.instrument_id),
                    side=side,
                    entry_ts=entry_ts,
                    exit_ts=exit_ts,
                    entry_price=Decimal(str(pos.avg_px_open)),
                    exit_price=Decimal(str(pos.avg_px_close or pos.avg_px_open)),
                    quantity=Decimal(str(pos.quantity)),
                    pnl=Decimal(str(pos.realized_pnl)) if pos.realized_pnl else Decimal("0"),
                )
            )
        return records

    def dispose(self) -> None:
        """Release the underlying engine's resources."""
        self._engine.dispose()
