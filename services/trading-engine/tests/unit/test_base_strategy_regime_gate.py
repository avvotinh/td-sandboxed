"""Unit tests for BaseStrategy regime entry-gate (Epic 15 story 15.7).

The regime pipeline (RegimeActor, story 15.5) publishes the confirmed regime
into a shared ``RegimeStateStore``; the strategy reads it at its **entry-only**
order seam and suppresses disallowed entries. This file pins the gate contract:

- ``_regime_admits`` decision logic (carries the gate semantics the retired
  Epic-11 router once applied at dispatch): store None → allow (default-off
  parity), snapshot None → suppress (warmup, R-H), HIGH_VOLATILITY → suppress
  before the allow-list (kill-switch precedence), allow-list match/miss.
- The gate is wired into ``_go_long``/``_go_short`` themselves (R-B
  safe-by-default) and runs only when flat (after the ``is_flat`` guard).
- Exits are **never** gated (R-A / R-C): a CLOSE routes to ``_close_position``
  regardless of regime, so risk can always be closed in HIGH_VOLATILITY.
- Default-OFF parity: a freshly constructed strategy admits everything (R8 —
  the store/allow-list are runtime attributes injected later by 15.8/15.10).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.regime.decision import RegimeDecision
from src.regime.state_store import RegimeStateStore
from src.regime.states import RegimeState
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig

pytestmark = pytest.mark.unit

BAR_TYPE_STR = "XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"


class _ConcreteStrategy(BaseStrategy):
    """Minimal concrete strategy for exercising the gate."""

    def generate_signal(self, bar) -> SignalType:
        return SignalType.NONE


@pytest.fixture
def config() -> BaseStrategyConfig:
    return BaseStrategyConfig(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str(BAR_TYPE_STR),
        trade_size=Decimal("0.1"),
        account_id="ftmo-main",
    )


@pytest.fixture
def strategy(config: BaseStrategyConfig) -> _ConcreteStrategy:
    return _ConcreteStrategy(config)


def _store_with(state: RegimeState) -> RegimeStateStore:
    """A store whose only snapshot (for BAR_TYPE_STR) is ``state``.

    ``features`` is a placeholder — the gate never reads it; it only consults
    ``snapshot.current_state``.
    """
    store = RegimeStateStore()
    store.publish(
        RegimeDecision(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bar_type=BAR_TYPE_STR,
            current_state=state,
            raw_state=state,
            pending_state=None,
            bars_in_pending=0,
            features=Mock(),
            confidence=0.9,
        )
    )
    return store


# ---------------------------------------------------------------------------
# _regime_admits decision logic
# ---------------------------------------------------------------------------


class TestRegimeAdmitsLogic:
    def test_store_none_admits(self, strategy: _ConcreteStrategy) -> None:
        # Default-off: no store injected ⇒ allow (byte-identical to today).
        assert strategy._regime_state is None
        assert strategy._regime_admits(SignalType.BUY) is True

    def test_snapshot_none_suppresses_warmup(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # Store injected but no confirmed regime yet (warmup) ⇒ suppress (R-H).
        strategy._regime_state = RegimeStateStore()  # empty
        strategy._allowed_regimes = None  # always-allow strategy
        assert strategy._regime_admits(SignalType.BUY) is False

    def test_high_volatility_suppresses_even_when_always_allow(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # Kill-switch fires before the allow-list, so even an always-allow
        # (allowed=None) strategy is suppressed in HIGH_VOLATILITY.
        strategy._regime_state = _store_with(RegimeState.HIGH_VOLATILITY)
        strategy._allowed_regimes = None
        assert strategy._regime_admits(SignalType.BUY) is False

    def test_high_volatility_precedes_allow_list(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # Even if a strategy somehow declared HIGH_VOLATILITY in its allow-list,
        # the kill-switch check comes first and suppresses.
        strategy._regime_state = _store_with(RegimeState.HIGH_VOLATILITY)
        strategy._allowed_regimes = frozenset({RegimeState.HIGH_VOLATILITY})
        assert strategy._regime_admits(SignalType.SELL) is False

    def test_unknown_suppresses_even_when_always_allow(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # UNKNOWN is the warmup/unsettled sentinel (the hysteresis filter
        # publishes it for its first confirmation_bars-1 post-warmup bars).
        # It is non-tradeable and suppressed before the allow-list, so even an
        # always-allow strategy skips it — consistent with the registry already
        # rejecting UNKNOWN from every declared allow-list.
        strategy._regime_state = _store_with(RegimeState.UNKNOWN)
        strategy._allowed_regimes = None
        assert strategy._regime_admits(SignalType.BUY) is False

    def test_always_allow_admits_normal_state(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._regime_state = _store_with(RegimeState.RANGING)
        strategy._allowed_regimes = None
        assert strategy._regime_admits(SignalType.BUY) is True

    def test_state_in_allow_list_admits(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._regime_state = _store_with(RegimeState.TRENDING_UP)
        strategy._allowed_regimes = frozenset(
            {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}
        )
        assert strategy._regime_admits(SignalType.BUY) is True

    def test_state_not_in_allow_list_suppresses(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._regime_state = _store_with(RegimeState.RANGING)
        strategy._allowed_regimes = frozenset(
            {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}
        )
        assert strategy._regime_admits(SignalType.BUY) is False

    def test_empty_allow_list_never_routes(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # ``regimes=[]`` (e.g. ORB Phase-1 opt-out) suppresses in every regime.
        strategy._allowed_regimes = frozenset()
        for state in (
            RegimeState.TRENDING_UP,
            RegimeState.TRENDING_DOWN,
            RegimeState.RANGING,
        ):
            strategy._regime_state = _store_with(state)
            assert strategy._regime_admits(SignalType.BUY) is False


# ---------------------------------------------------------------------------
# Gate wiring in _go_long / _go_short (R-B safe-by-default)
# ---------------------------------------------------------------------------


class TestEntryGateWiring:
    def test_go_long_consults_gate_and_suppresses(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # Flat + gate denies ⇒ _go_long short-circuits before the (Cython)
        # order seam, so no exception and no order is built.
        strategy._position = None
        strategy._regime_admits = Mock(return_value=False)
        strategy._go_long()
        strategy._regime_admits.assert_called_once_with(SignalType.BUY)

    def test_go_short_consults_gate_and_suppresses(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._position = None
        strategy._regime_admits = Mock(return_value=False)
        strategy._go_short()
        strategy._regime_admits.assert_called_once_with(SignalType.SELL)

    def test_go_long_skips_gate_when_not_flat(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # is_flat is checked first — an occupied position returns before the
        # regime gate, so behaviour for held positions is unchanged.
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy._regime_admits = Mock()
        strategy._go_long()
        strategy._regime_admits.assert_not_called()

    def test_go_short_skips_gate_when_not_flat(
        self, strategy: _ConcreteStrategy
    ) -> None:
        pos = Mock()
        pos.side = PositionSide.SHORT
        strategy._position = pos
        strategy._regime_admits = Mock()
        strategy._go_short()
        strategy._regime_admits.assert_not_called()


# ---------------------------------------------------------------------------
# Exits are never gated (R-A / R-C)
# ---------------------------------------------------------------------------


class TestExitsNeverGated:
    def test_close_routed_even_under_high_volatility(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # A CLOSE in HIGH_VOLATILITY must still close the position: risk
        # reduction is never gated (FTMO-critical).
        strategy._regime_state = _store_with(RegimeState.HIGH_VOLATILITY)
        strategy._allowed_regimes = frozenset()  # never-route entries
        strategy._close_position = Mock()
        strategy._execute_signal(SignalType.CLOSE)
        strategy._close_position.assert_called_once()

    def test_execute_signal_close_does_not_consult_regime(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._regime_admits = Mock()
        strategy._close_position = Mock()
        strategy._execute_signal(SignalType.CLOSE)
        strategy._regime_admits.assert_not_called()


# ---------------------------------------------------------------------------
# Default-OFF parity + injection mechanism (R8)
# ---------------------------------------------------------------------------


class TestDefaultOffParity:
    def test_runtime_attributes_default_to_none(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # Injected after construction (not config fields) so default-OFF is the
        # construction default.
        assert strategy._regime_state is None
        assert strategy._allowed_regimes is None

    def test_default_admits_both_directions(
        self, strategy: _ConcreteStrategy
    ) -> None:
        assert strategy._regime_admits(SignalType.BUY) is True
        assert strategy._regime_admits(SignalType.SELL) is True
