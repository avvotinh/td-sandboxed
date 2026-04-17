"""BacktestRunner — thin façade over ``nautilus_trader.backtest.BacktestEngine``.

The runner's job is to compose a backtest in a way that keeps the rest of
our stack (rule engine, strategies, FTMO metrics) independent of Nautilus
internals. Composition order matters — ``add_venue`` must precede
``add_instrument``, and the FTMO actor must be attached before ``run()``.

For unit-level tests the underlying engine is mocked. End-to-end
correctness is covered by ``tests/integration/test_backtest_smoke.py``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Currency
from pydantic import BaseModel, ConfigDict, Field

from src.backtesting.ftmo_actor import FtmoComplianceActor, FtmoComplianceActorConfig
from src.backtesting.metrics.calculator import calculate_metrics
from src.backtesting.result import BacktestResult

if TYPE_CHECKING:
    from nautilus_trader.model.identifiers import Venue

    from src.rules.engine import RuleEngine


class BacktestRunnerConfig(BaseModel):
    """Configuration for a single backtest run."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    strategy_name: str
    initial_balance: Decimal = Field(..., gt=0)
    currency: str = "USD"
    profit_target_pct: float = 10.0
    max_dd_pct: float = 10.0
    min_trading_days: int = 4


class BacktestRunner:
    """Façade orchestrating a Nautilus backtest with FTMO compliance."""

    def __init__(self, config: BacktestRunnerConfig) -> None:
        self.config = config
        self._engine: BacktestEngine = BacktestEngine(config=BacktestEngineConfig())
        self._ftmo_actor: FtmoComplianceActor | None = None
        self._start: datetime | None = None
        self._end: datetime | None = None

    @property
    def engine(self) -> BacktestEngine:
        return self._engine

    @property
    def ftmo_actor(self) -> FtmoComplianceActor | None:
        return self._ftmo_actor

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

    def attach_ftmo_compliance(
        self,
        *,
        rule_engine: RuleEngine,
        account_id: str,
        daily_session_tz: str = "UTC",
        bar_type: Any = None,
        venue: Venue | None = None,
        currency: Currency = USD,
    ) -> FtmoComplianceActor:
        """Build + register an ``FtmoComplianceActor`` against this engine.

        ``bar_type`` is the ``BarType`` the actor should subscribe to on
        start — pass the same ``BarType`` you used for ``add_data``. When
        omitted the actor still registers but won't receive on_bar events;
        useful when tests exercise the actor via its public methods only.

        ``venue`` + ``currency`` let the actor read real equity from the
        portfolio. When omitted (unit-test path) equity reads return
        ``None`` and ``on_bar`` is a no-op.
        """
        actor_config = FtmoComplianceActorConfig(
            account_id=account_id,
            initial_balance=self.config.initial_balance,
            daily_session_tz=daily_session_tz,
            bar_type=bar_type,
            venue=venue,
            currency=currency,
        )
        actor = FtmoComplianceActor(config=actor_config, rule_engine=rule_engine)
        self._engine.add_actor(actor)
        self._ftmo_actor = actor
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
            self._ftmo_actor.equity_curve if self._ftmo_actor is not None else []
        )
        breaches = (
            self._ftmo_actor.breaches if self._ftmo_actor is not None else []
        )

        # TODO: extract TradeRecord list from engine.cache.positions_closed().
        # For now we pass [] and let metrics fall back to safe defaults. Full
        # trade extraction is wired in the integration smoke test (Task 8).
        trades = []

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

    def dispose(self) -> None:
        """Release the underlying engine's resources."""
        self._engine.dispose()
