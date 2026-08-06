"""Unit tests for BracketStrategyMixin (Story 8.9)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

from src.kernel.signal import SignalType
from src.kernel.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
)


class _Host(BracketStrategyMixin):
    """Minimal host that stubs the Nautilus attributes the mixin reads."""

    def __init__(self, *, cache=None, portfolio=None, bar_type=None):
        self.cache = cache
        self.portfolio = portfolio
        self.config = MagicMock(bar_type=bar_type)
        # In production the regime gate lives on BaseStrategy; here the host
        # is a bare mixin, so stub it open (story 15.7). Gate tests override it.
        self._regime_admits = MagicMock(return_value=True)


@pytest.mark.unit
class TestLastBar:
    def test_returns_cached_bar(self) -> None:
        cache = MagicMock()
        bar = object()
        cache.bar.return_value = bar
        host = _Host(cache=cache, bar_type="bt")
        assert host._last_bar() is bar

    def test_none_when_cache_reports_empty(self) -> None:
        """Nautilus cache raises ``KeyError`` / ``IndexError`` / ``LookupError``
        when the requested bar isn't populated yet. Programming errors
        (``RuntimeError``, etc.) must propagate so misconfiguration surfaces
        loudly instead of silently producing zero signals.
        """
        for exc_cls in (KeyError, IndexError, LookupError):
            cache = MagicMock()
            cache.bar.side_effect = exc_cls("empty")
            host = _Host(cache=cache, bar_type="bt")
            assert host._last_bar() is None

    def test_programmer_errors_propagate(self) -> None:
        cache = MagicMock()
        cache.bar.side_effect = RuntimeError("broken cache")
        host = _Host(cache=cache, bar_type="bt")
        with pytest.raises(RuntimeError):
            host._last_bar()


@pytest.mark.unit
class TestReadAccountBalance:
    def _bar_type(self):
        bar_type = MagicMock()
        bar_type.instrument_id.venue = "SIM"
        return bar_type

    def test_zero_when_portfolio_missing_account(self) -> None:
        portfolio = MagicMock()
        portfolio.account.return_value = None
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        assert host._read_account_balance() == Decimal("0")

    def test_zero_when_portfolio_raises(self) -> None:
        portfolio = MagicMock()
        portfolio.account.side_effect = RuntimeError("boom")
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        assert host._read_account_balance() == Decimal("0")

    def test_reads_balance_when_available(self) -> None:
        portfolio = MagicMock()
        account = MagicMock()
        money = MagicMock()
        money.as_decimal.return_value = Decimal("120500.50")
        account.balance_total.return_value = money
        portfolio.account.return_value = account
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        # Track 2.3: Money.as_decimal() end-to-end — no float round-trip.
        assert host._read_account_balance() == Decimal("120500.50")

    def test_zero_when_balance_is_none(self) -> None:
        portfolio = MagicMock()
        account = MagicMock()
        account.balance_total.return_value = None
        portfolio.account.return_value = account
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        assert host._read_account_balance() == Decimal("0")


# ---------------------------------------------------------------------------
# BracketHost composition guard (Track 2.3 — review 2026-05-02 refactor #1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBracketHostCompositionGuard:
    """Mis-composed concrete strategies must fail at class DEFINITION,
    not at their first signal mid-backtest."""

    def test_missing_risk_sized_mixin_fails_at_definition(self) -> None:
        from src.kernel.strategies.base_strategy import BaseStrategy
        from src.kernel.strategies.mixins.atr_stop_mixin import ATRStopMixin

        with pytest.raises(TypeError, match="size_from_risk"):

            class _Incomplete(  # noqa: F811 — never bound on raise
                BaseStrategy, ATRStopMixin, BracketStrategyMixin
            ):
                def generate_signal(self, bar):  # pragma: no cover
                    ...

    def test_missing_atr_stop_mixin_fails_at_definition(self) -> None:
        from src.kernel.strategies.base_strategy import BaseStrategy
        from src.kernel.strategies.mixins.risk_sized_mixin import RiskSizedMixin

        with pytest.raises(TypeError, match="calculate_atr_stop"):

            class _Incomplete(
                BaseStrategy, RiskSizedMixin, BracketStrategyMixin
            ):
                def generate_signal(self, bar):  # pragma: no cover
                    ...

    def test_complete_composition_passes(self) -> None:
        from src.kernel.strategies.base_strategy import BaseStrategy
        from src.kernel.strategies.mixins.atr_stop_mixin import ATRStopMixin
        from src.kernel.strategies.mixins.risk_sized_mixin import RiskSizedMixin

        class _Complete(
            BaseStrategy, ATRStopMixin, RiskSizedMixin, BracketStrategyMixin
        ):
            def generate_signal(self, bar):  # pragma: no cover
                ...

        assert _Complete is not None

    def test_bare_test_hosts_are_exempt(self) -> None:
        # _Host at the top of this file subclasses only the mixin —
        # non-BaseStrategy hosts stub the contract per-instance and must
        # keep working (the guard scopes to concrete strategies).
        assert _Host is not None


# ---------------------------------------------------------------------------
# BracketStrategyConfig — cross-cutting R:R guard (review 2026-05-02 priority 1)
# ---------------------------------------------------------------------------


def _bracket_config(**overrides):
    base = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
    )
    base.update(overrides)
    return BracketStrategyConfig(**base)


@pytest.mark.unit
class TestBracketStrategyConfigValidation:
    def test_defaults_pass(self) -> None:
        cfg = _bracket_config()
        assert cfg.sl_atr_mult == Decimal("1.5")
        assert cfg.tp_atr_mult == Decimal("3.0")

    @pytest.mark.parametrize("bad", [0, -1, -14])
    def test_atr_period_must_be_positive(self, bad: int) -> None:
        with pytest.raises(ValueError, match="atr_period"):
            _bracket_config(atr_period=bad)

    @pytest.mark.parametrize(
        "field, bad_value",
        [
            ("sl_atr_mult", Decimal("0")),
            ("sl_atr_mult", Decimal("-0.5")),
            ("tp_atr_mult", Decimal("0")),
            ("tp_atr_mult", Decimal("-1.0")),
            ("risk_percent", Decimal("0")),
            ("risk_percent", Decimal("-0.1")),
        ],
    )
    def test_decimal_fields_must_be_positive(
        self, field: str, bad_value: Decimal
    ) -> None:
        with pytest.raises(ValueError, match=field):
            _bracket_config(**{field: bad_value})

    def test_sl_must_be_strictly_less_than_tp(self) -> None:
        # R:R below 1 is degenerate for ATR brackets — TP closer to entry
        # than SL implies the strategy expects to lose on average.
        with pytest.raises(ValueError, match="sl_atr_mult"):
            _bracket_config(
                sl_atr_mult=Decimal("3.0"),
                tp_atr_mult=Decimal("1.0"),
            )

    def test_sl_equal_to_tp_is_rejected(self) -> None:
        # 1:1 R:R is the boundary; reject it explicitly so backtest
        # operators can't ship a no-edge config by accident.
        with pytest.raises(ValueError, match="sl_atr_mult"):
            _bracket_config(
                sl_atr_mult=Decimal("2.0"),
                tp_atr_mult=Decimal("2.0"),
            )


# ---------------------------------------------------------------------------
# BracketStrategyConfig — Phase 1 scale-out + trail fields (Epic 13 story 13.2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBracketScaleOutConfigDefaults:
    def test_scale_out_default_off(self) -> None:
        # Existing strategies must not be affected — both feature flags
        # default False so a config that omits them keeps the legacy
        # single-fill + hard-TP behaviour.
        cfg = _bracket_config()
        assert cfg.scale_out_enabled is False
        assert cfg.trailing_enabled is False

    def test_phase1_field_defaults(self) -> None:
        cfg = _bracket_config()
        assert cfg.scale_out_r_trigger == Decimal("1.0")
        assert cfg.scale_out_close_fraction == Decimal("0.5")
        assert cfg.breakeven_at_r == Decimal("1.0")
        assert cfg.trailing_method == "supertrend"
        assert cfg.trailing_atr_period == 7
        assert cfg.trailing_atr_multiplier == Decimal("2.1")
        assert cfg.safety_tp_atr_mult == Decimal("6.0")

    def test_disabled_fields_inert(self) -> None:
        # When scale-out + trailing are off, invalid Phase 1 inputs must
        # not gate construction — operator may set them speculatively in
        # YAML before flipping the flag, and the inert path stays usable.
        cfg = _bracket_config(
            scale_out_enabled=False,
            scale_out_close_fraction=Decimal("1.5"),  # invalid if enabled
            trailing_enabled=False,
            trailing_method="chandelier",  # invalid if enabled
            trailing_atr_period=0,  # invalid if enabled
        )
        assert cfg.scale_out_enabled is False


@pytest.mark.unit
class TestBracketScaleOutConfigInvariants:
    @pytest.mark.parametrize(
        "bad",
        [Decimal("0"), Decimal("1.0"), Decimal("-0.1"), Decimal("1.5")],
    )
    def test_scale_out_close_fraction_must_be_strict_open_unit(
        self, bad: Decimal
    ) -> None:
        # Fraction must be in (0, 1): 0 closes nothing, 1 closes the whole
        # trade (defeats scale-out), >1 over-closes.
        with pytest.raises(ValueError, match="scale_out_close_fraction"):
            _bracket_config(
                scale_out_enabled=True,
                scale_out_close_fraction=bad,
            )

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.5")])
    def test_scale_out_r_trigger_must_be_positive(self, bad: Decimal) -> None:
        with pytest.raises(ValueError, match="scale_out_r_trigger"):
            _bracket_config(
                scale_out_enabled=True,
                scale_out_r_trigger=bad,
            )

    def test_breakeven_at_r_none_is_valid(self) -> None:
        # ``None`` means "do not move SL to BE" — the partial close still
        # fires at scale_out_r_trigger but the remaining 50% keeps the
        # original hard SL.
        cfg = _bracket_config(scale_out_enabled=True, breakeven_at_r=None)
        assert cfg.breakeven_at_r is None

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1.0")])
    def test_breakeven_at_r_when_set_must_be_positive(
        self, bad: Decimal
    ) -> None:
        with pytest.raises(ValueError, match="breakeven_at_r"):
            _bracket_config(
                scale_out_enabled=True,
                breakeven_at_r=bad,
            )

    def test_breakeven_above_scale_out_trigger_rejected(self) -> None:
        # State machine moves SL to BE at the same bar as the partial
        # close — BE > trigger means BE never fires, silent regression.
        with pytest.raises(ValueError, match="breakeven_at_r"):
            _bracket_config(
                scale_out_enabled=True,
                scale_out_r_trigger=Decimal("1.0"),
                breakeven_at_r=Decimal("2.0"),
            )

    def test_breakeven_equal_to_scale_out_trigger_accepted(self) -> None:
        # The == case is the canonical Phase 1 layout (BE at +1R, partial
        # close at +1R). Must not be rejected by the new invariant.
        cfg = _bracket_config(
            scale_out_enabled=True,
            scale_out_r_trigger=Decimal("1.0"),
            breakeven_at_r=Decimal("1.0"),
        )
        assert cfg.breakeven_at_r == cfg.scale_out_r_trigger

    def test_trailing_method_supertrend_only(self) -> None:
        # Phase 1 only supports the Supertrend trail; Chandelier and
        # other methods are deferred to Phase 2.
        with pytest.raises(ValueError, match="trailing_method"):
            _bracket_config(
                scale_out_enabled=True,
                trailing_enabled=True,
                trailing_method="chandelier",
            )

    @pytest.mark.parametrize("bad", [0, -7])
    def test_trailing_atr_period_must_be_positive(self, bad: int) -> None:
        with pytest.raises(ValueError, match="trailing_atr_period"):
            _bracket_config(
                scale_out_enabled=True,
                trailing_enabled=True,
                trailing_atr_period=bad,
            )

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-2.1")])
    def test_trailing_atr_multiplier_must_be_positive(
        self, bad: Decimal
    ) -> None:
        with pytest.raises(ValueError, match="trailing_atr_multiplier"):
            _bracket_config(
                scale_out_enabled=True,
                trailing_enabled=True,
                trailing_atr_multiplier=bad,
            )

    def test_trailing_without_scale_out_is_valid(self) -> None:
        # Trail-only mode (entry-exit-trailing analysis §3.5): full
        # position keeps its original hard SL until the trail line
        # tightens past it — no partial close, no BE. The Phase 1
        # "trailing requires scale_out" invariant was implementation
        # coupling, not an evidence-backed constraint.
        cfg = _bracket_config(
            scale_out_enabled=False,
            trailing_enabled=True,
        )
        assert cfg.trailing_enabled is True
        assert cfg.scale_out_enabled is False

    def test_trail_only_still_validates_trailing_params(self) -> None:
        # Trailing param validation must fire in trail-only mode too,
        # not just when scale-out is on.
        with pytest.raises(ValueError, match="trailing_method"):
            _bracket_config(
                scale_out_enabled=False,
                trailing_enabled=True,
                trailing_method="chandelier",
            )
        with pytest.raises(ValueError, match="trailing_atr_period"):
            _bracket_config(
                scale_out_enabled=False,
                trailing_enabled=True,
                trailing_atr_period=0,
            )

    @pytest.mark.parametrize("bad", [Decimal("-1"), Decimal("-0.01")])
    def test_breakeven_offset_pips_negative_rejected(
        self, bad: Decimal
    ) -> None:
        # Offset is a cost-recovery constant (spread + commission in
        # pips) — negative would place BE below entry, i.e. a
        # guaranteed-loss "breakeven".
        with pytest.raises(ValueError, match="breakeven_offset_pips"):
            _bracket_config(breakeven_offset_pips=bad)

    def test_breakeven_offset_pips_defaults_to_zero(self) -> None:
        # Zero offset = legacy exact-entry BE; existing YAMLs unaffected.
        cfg = _bracket_config(scale_out_enabled=True)
        assert cfg.breakeven_offset_pips == Decimal("0")

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-6.0")])
    def test_safety_tp_atr_mult_must_be_positive(self, bad: Decimal) -> None:
        # Safety cap protects against runaway trades when trailing logic
        # has a bug or a bar gaps through the trail line; must be > 0
        # regardless of whether scale_out is enabled (always read by
        # the bracket helper as a sanity ceiling).
        with pytest.raises(ValueError, match="safety_tp_atr_mult"):
            _bracket_config(safety_tp_atr_mult=bad)

    def test_full_phase1_config_valid(self) -> None:
        cfg = _bracket_config(
            scale_out_enabled=True,
            scale_out_r_trigger=Decimal("1.0"),
            scale_out_close_fraction=Decimal("0.5"),
            breakeven_at_r=Decimal("1.0"),
            trailing_enabled=True,
            trailing_method="supertrend",
            trailing_atr_period=7,
            trailing_atr_multiplier=Decimal("2.1"),
            safety_tp_atr_mult=Decimal("6.0"),
        )
        assert cfg.scale_out_enabled is True
        assert cfg.trailing_enabled is True


@pytest.mark.unit
class TestSubmitBracketForEntryGuards:
    """Story 12.8: bracket-execution coverage for the position-reversal
    guard. _submit_bracket_for_entry must short-circuit BEFORE building
    bracket params when the host already holds a position — bracket
    strategies are not designed to reverse on opposing signals (the
    breakout / mean-reversion thesis assumes the existing position will
    flatten via SL/TP first). A premature opposing entry would produce
    a hedged book the FTMO compliance rules don't model.
    """

    def _entry_host(self, *, is_flat: bool, last_bar: object | None) -> "_Host":
        host = _Host(cache=MagicMock(), portfolio=MagicMock(), bar_type=MagicMock())
        host.is_flat = is_flat
        host._last_bar = MagicMock(return_value=last_bar)
        host._read_account_balance = MagicMock(return_value=Decimal("100000"))
        host._compute_bracket_params = MagicMock(
            return_value=(Decimal("1.0"), Decimal("2390"), Decimal("2420"))
        )
        host._submit_bracket_order = MagicMock()
        return host

    def test_skips_when_position_already_open(self) -> None:
        bar = MagicMock()
        bar.close.as_double.return_value = 2400.0
        host = self._entry_host(is_flat=False, last_bar=bar)
        host._submit_bracket_for_entry(SignalType.BUY, Decimal("5"))
        host._submit_bracket_order.assert_not_called()
        host._compute_bracket_params.assert_not_called()

    def test_skips_on_none_signal(self) -> None:
        bar = MagicMock()
        bar.close.as_double.return_value = 2400.0
        host = self._entry_host(is_flat=True, last_bar=bar)
        host._submit_bracket_for_entry(SignalType.NONE, Decimal("5"))
        host._submit_bracket_order.assert_not_called()

    def test_skips_when_last_bar_missing(self) -> None:
        # Cache miss between subscribe + first bar — no entry price to
        # anchor sizing, so the helper bails out without crashing.
        host = self._entry_host(is_flat=True, last_bar=None)
        host._submit_bracket_for_entry(SignalType.BUY, Decimal("5"))
        host._submit_bracket_order.assert_not_called()

    def test_submits_when_flat_with_buy_signal(self) -> None:
        from nautilus_trader.model.enums import OrderSide

        bar = MagicMock()
        bar.close.as_double.return_value = 2400.0
        host = self._entry_host(is_flat=True, last_bar=bar)
        host._submit_bracket_for_entry(SignalType.BUY, Decimal("5"))
        host._submit_bracket_order.assert_called_once()
        kwargs = host._submit_bracket_order.call_args.kwargs
        assert kwargs["side"] == OrderSide.BUY
        assert kwargs["sl_price"] == Decimal("2390")
        assert kwargs["tp_price"] == Decimal("2420")


@pytest.mark.unit
class TestSubmitBracketForEntryRegimeGate:
    """Story 15.7: the bracket entry seam is gated by the regime admit-check.

    All six production bracket strategies funnel new entries through
    ``_submit_bracket_for_entry``, so this is the single seam that suppresses
    disallowed entries when regime gating is enabled. The gate is consulted
    only after the NONE + ``is_flat`` guards (entry-only) and never on exits.
    """

    def _entry_host(self, *, regime_admits: bool, last_bar: object) -> "_Host":
        host = _Host(cache=MagicMock(), portfolio=MagicMock(), bar_type=MagicMock())
        host.is_flat = True
        host._regime_admits = MagicMock(return_value=regime_admits)
        host._last_bar = MagicMock(return_value=last_bar)
        host._read_account_balance = MagicMock(return_value=Decimal("100000"))
        host._compute_bracket_params = MagicMock(
            return_value=(Decimal("1.0"), Decimal("2390"), Decimal("2420"))
        )
        host._submit_bracket_order = MagicMock()
        return host

    def test_suppressed_when_regime_denies(self) -> None:
        bar = MagicMock()
        bar.close.as_double.return_value = 2400.0
        host = self._entry_host(regime_admits=False, last_bar=bar)
        host._submit_bracket_for_entry(SignalType.BUY, Decimal("5"))
        host._regime_admits.assert_called_once_with(SignalType.BUY)
        host._submit_bracket_order.assert_not_called()
        # Order-of-operations guard (not the semantic contract): the gate fires
        # before bracket-param computation, so a denied entry costs nothing.
        host._compute_bracket_params.assert_not_called()

    def test_submits_when_regime_admits(self) -> None:
        bar = MagicMock()
        bar.close.as_double.return_value = 2400.0
        host = self._entry_host(regime_admits=True, last_bar=bar)
        host._submit_bracket_for_entry(SignalType.SELL, Decimal("5"))
        host._regime_admits.assert_called_once_with(SignalType.SELL)
        host._submit_bracket_order.assert_called_once()

    def test_gate_skipped_for_none_signal(self) -> None:
        # NONE bails before the regime gate — nothing to admit.
        bar = MagicMock()
        bar.close.as_double.return_value = 2400.0
        host = self._entry_host(regime_admits=False, last_bar=bar)
        host._submit_bracket_for_entry(SignalType.NONE, Decimal("5"))
        host._regime_admits.assert_not_called()
        host._submit_bracket_order.assert_not_called()
