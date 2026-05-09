"""Unit tests for BracketStrategyMixin (Story 8.9)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

from src.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
)


class _Host(BracketStrategyMixin):
    """Minimal host that stubs the Nautilus attributes the mixin reads."""

    def __init__(self, *, cache=None, portfolio=None, bar_type=None):
        self.cache = cache
        self.portfolio = portfolio
        self.config = MagicMock(bar_type=bar_type)


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
        money.as_double.return_value = 120_500.50
        account.balance_total.return_value = money
        portfolio.account.return_value = account
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        # Decimal(str(float)) is a controlled conversion; this proves the
        # mixin plumbs the money all the way through.
        assert host._read_account_balance() == Decimal("120500.5")

    def test_zero_when_balance_is_none(self) -> None:
        portfolio = MagicMock()
        account = MagicMock()
        account.balance_total.return_value = None
        portfolio.account.return_value = account
        host = _Host(portfolio=portfolio, bar_type=self._bar_type())
        assert host._read_account_balance() == Decimal("0")


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
            ("pip_size", Decimal("0")),
            ("pip_value_per_lot", Decimal("0")),
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

    def test_trailing_requires_scale_out(self) -> None:
        # Trail applies only to the remaining 50% after partial close
        # (implementation plan §1) — enabling trail without scale-out is
        # a configuration error.
        with pytest.raises(ValueError, match="trailing_enabled"):
            _bracket_config(
                scale_out_enabled=False,
                trailing_enabled=True,
            )

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
