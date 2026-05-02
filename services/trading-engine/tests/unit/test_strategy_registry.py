"""Unit tests for StrategyRegistry."""

import pytest
from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import BarType

from src.regime.states import RegimeState
from src.strategies.registry import StrategyRegistry, register_strategy
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig
from src.orders.signal import SignalType


class MockStrategy(BaseStrategy):
    """Mock strategy for registry tests."""

    def generate_signal(self, bar) -> SignalType:
        return SignalType.NONE


class AnotherMockStrategy(BaseStrategy):
    """Another mock strategy for registry tests."""

    def generate_signal(self, bar) -> SignalType:
        return SignalType.BUY


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the registry before and after each test."""
    StrategyRegistry.clear()
    yield
    StrategyRegistry.clear()


class TestStrategyRegistryRegister:
    """Tests for StrategyRegistry.register."""

    def test_register_strategy(self):
        """Should register a strategy class."""
        StrategyRegistry.register("test_strategy", MockStrategy)

        assert StrategyRegistry.is_registered("test_strategy")

    def test_register_multiple_strategies(self):
        """Should register multiple strategies."""
        StrategyRegistry.register("test", MockStrategy)
        StrategyRegistry.register("another", AnotherMockStrategy)

        assert StrategyRegistry.is_registered("test")
        assert StrategyRegistry.is_registered("another")

    def test_register_empty_name_raises(self):
        """Should raise ValueError for empty name."""
        with pytest.raises(ValueError, match="cannot be empty"):
            StrategyRegistry.register("", MockStrategy)

    def test_register_duplicate_raises(self):
        """Should raise ValueError for duplicate registration."""
        StrategyRegistry.register("test", MockStrategy)

        with pytest.raises(ValueError, match="already registered"):
            StrategyRegistry.register("test", AnotherMockStrategy)


class TestStrategyRegistryGet:
    """Tests for StrategyRegistry.get."""

    def test_get_registered_strategy(self):
        """Should return registered strategy class."""
        StrategyRegistry.register("test", MockStrategy)

        result = StrategyRegistry.get("test")

        assert result is MockStrategy

    def test_get_unregistered_raises(self):
        """Should raise ValueError for unregistered strategy."""
        with pytest.raises(ValueError, match="not registered"):
            StrategyRegistry.get("nonexistent")

    def test_get_error_message_lists_available(self):
        """Error message should list available strategies."""
        StrategyRegistry.register("available_one", MockStrategy)
        StrategyRegistry.register("available_two", AnotherMockStrategy)

        with pytest.raises(ValueError) as exc_info:
            StrategyRegistry.get("nonexistent")

        assert "available_one" in str(exc_info.value)
        assert "available_two" in str(exc_info.value)

    def test_get_returns_correct_class(self):
        """Should return the correct strategy class."""
        StrategyRegistry.register("test", MockStrategy)
        StrategyRegistry.register("another", AnotherMockStrategy)

        assert StrategyRegistry.get("test") is MockStrategy
        assert StrategyRegistry.get("another") is AnotherMockStrategy


class TestStrategyRegistryListAvailable:
    """Tests for StrategyRegistry.list_available."""

    def test_list_empty_when_no_strategies(self):
        """Should return empty list when no strategies registered."""
        result = StrategyRegistry.list_available()

        assert result == []

    def test_list_registered_strategies(self):
        """Should return list of registered strategy names."""
        StrategyRegistry.register("alpha", MockStrategy)
        StrategyRegistry.register("beta", AnotherMockStrategy)

        result = StrategyRegistry.list_available()

        assert "alpha" in result
        assert "beta" in result
        assert len(result) == 2


class TestStrategyRegistryIsRegistered:
    """Tests for StrategyRegistry.is_registered."""

    def test_returns_true_for_registered(self):
        """Should return True for registered strategy."""
        StrategyRegistry.register("test", MockStrategy)

        assert StrategyRegistry.is_registered("test") is True

    def test_returns_false_for_unregistered(self):
        """Should return False for unregistered strategy."""
        assert StrategyRegistry.is_registered("nonexistent") is False


class TestStrategyRegistryUnregister:
    """Tests for StrategyRegistry.unregister."""

    def test_unregister_removes_strategy(self):
        """Should remove registered strategy."""
        StrategyRegistry.register("test", MockStrategy)

        result = StrategyRegistry.unregister("test")

        assert result is True
        assert StrategyRegistry.is_registered("test") is False

    def test_unregister_returns_false_if_not_found(self):
        """Should return False if strategy not found."""
        result = StrategyRegistry.unregister("nonexistent")

        assert result is False


class TestStrategyRegistryClear:
    """Tests for StrategyRegistry.clear."""

    def test_clear_removes_all_strategies(self):
        """Should remove all registered strategies."""
        StrategyRegistry.register("one", MockStrategy)
        StrategyRegistry.register("two", AnotherMockStrategy)

        StrategyRegistry.clear()

        assert StrategyRegistry.list_available() == []


class TestRegisterStrategyDecorator:
    """Tests for register_strategy decorator."""

    def test_decorator_registers_strategy(self):
        """Decorator should register the strategy class."""

        @register_strategy("decorated")
        class DecoratedStrategy(BaseStrategy):
            def generate_signal(self, bar):
                return SignalType.NONE

        assert StrategyRegistry.is_registered("decorated")
        assert StrategyRegistry.get("decorated") is DecoratedStrategy

    def test_decorator_returns_class(self):
        """Decorator should return the original class."""

        @register_strategy("returned")
        class ReturnedStrategy(BaseStrategy):
            def generate_signal(self, bar):
                return SignalType.NONE

        # Should be able to use the class normally
        config = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        )
        instance = ReturnedStrategy(config)
        assert isinstance(instance, BaseStrategy)


class TestStrategyInstantiation:
    """Tests for instantiating strategies from registry."""

    def test_instantiate_from_registry(self):
        """Should be able to instantiate strategy from registry."""
        StrategyRegistry.register("test", MockStrategy)

        config = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            trade_size=Decimal("0.1"),
            account_id="ftmo-main",
        )

        strategy_class = StrategyRegistry.get("test")
        strategy = strategy_class(config)

        assert isinstance(strategy, MockStrategy)
        assert strategy.config.account_id == "ftmo-main"


# ---------------------------------------------------------------------------
# Regime mapping (Epic 11 story 11.6)
# ---------------------------------------------------------------------------


class TestStrategyRegimeRegistration:
    """Tests for regime-aware registration extensions (story 11.6)."""

    def test_register_without_regimes_kwarg_defaults_to_none(self):
        # Backwards compat: every call site shipped before story 11.6
        # passed only (name, cls). Those entries must keep working and
        # land in the regime map as None (always-allow).
        StrategyRegistry.register("legacy", MockStrategy)
        assert StrategyRegistry.get_regimes("legacy") is None

    def test_register_with_regimes_kwarg_stores_frozenset(self):
        StrategyRegistry.register(
            "trender",
            MockStrategy,
            regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
        )
        regs = StrategyRegistry.get_regimes("trender")
        assert isinstance(regs, frozenset)
        assert regs == frozenset(
            {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}
        )

    def test_empty_regimes_list_means_never_route(self):
        # ORB Phase 1 ships with `regimes=[]` — explicit opt-out: the
        # router must distinguish this from "missing kwarg" (None).
        StrategyRegistry.register("orb", MockStrategy, regimes=[])
        regs = StrategyRegistry.get_regimes("orb")
        assert regs == frozenset()
        assert regs is not None

    def test_unknown_state_in_regimes_rejected(self):
        # UNKNOWN is the warmup-only sentinel; declaring a strategy as
        # "trades during UNKNOWN" would let it run on undefined indicator
        # state. Reject at registration time so the failure surfaces at
        # import.
        with pytest.raises(ValueError, match="UNKNOWN"):
            StrategyRegistry.register(
                "broken",
                MockStrategy,
                regimes=[RegimeState.TRENDING_UP, RegimeState.UNKNOWN],
            )

    def test_get_regimes_for_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="not registered"):
            StrategyRegistry.get_regimes("never_registered")

    def test_decorator_with_regimes_kwarg(self):
        @register_strategy(
            "decorated_trender",
            regimes=[RegimeState.TRENDING_UP],
        )
        class DecoratedStrategy(BaseStrategy):
            def generate_signal(self, bar) -> SignalType:
                return SignalType.NONE

        assert StrategyRegistry.is_registered("decorated_trender")
        assert StrategyRegistry.get_regimes("decorated_trender") == frozenset(
            {RegimeState.TRENDING_UP}
        )

    def test_decorator_without_regimes_kwarg_is_always_allow(self):
        # Backwards compat at the decorator surface.
        @register_strategy("decorated_legacy")
        class DecoratedLegacy(BaseStrategy):
            def generate_signal(self, bar) -> SignalType:
                return SignalType.NONE

        assert StrategyRegistry.get_regimes("decorated_legacy") is None

    def test_get_all_regime_maps_returns_immutable_view(self):
        StrategyRegistry.register(
            "t",
            MockStrategy,
            regimes=[RegimeState.TRENDING_UP],
        )
        StrategyRegistry.register("legacy2", AnotherMockStrategy)
        m = StrategyRegistry.get_all_regime_maps()
        assert m["t"] == frozenset({RegimeState.TRENDING_UP})
        assert m["legacy2"] is None
        # Caller mutating the returned mapping must not corrupt registry.
        with pytest.raises(TypeError):
            m["hacked"] = frozenset()  # type: ignore[index]

    def test_unregister_clears_regime_entry(self):
        StrategyRegistry.register(
            "to_remove",
            MockStrategy,
            regimes=[RegimeState.RANGING],
        )
        assert StrategyRegistry.unregister("to_remove") is True
        with pytest.raises(ValueError, match="not registered"):
            StrategyRegistry.get_regimes("to_remove")

    def test_clear_clears_regime_map(self):
        StrategyRegistry.register(
            "x",
            MockStrategy,
            regimes=[RegimeState.RANGING],
        )
        StrategyRegistry.clear()
        assert StrategyRegistry.get_all_regime_maps() == {}

    def test_iterable_regimes_dedupes(self):
        # The decorator accepts list/tuple/set; duplicates collapse via
        # frozenset, no error.
        StrategyRegistry.register(
            "dedup",
            MockStrategy,
            regimes=[RegimeState.RANGING, RegimeState.RANGING],
        )
        assert StrategyRegistry.get_regimes("dedup") == frozenset(
            {RegimeState.RANGING}
        )
