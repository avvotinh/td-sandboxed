"""Shared bracket-order helpers for ATR-based bracket strategies.

The five bracket strategies (Supertrend, Donchian Breakout, RSI MR,
Bollinger MR, ORB) all build identical market brackets from an ATR
reading, a risk-percent target, and the live account balance. Pulling
that boilerplate up into one mixin removes ~60 LoC per strategy and
keeps the sizing/balance contract in one auditable place.

Strategy subclasses still own their signal generation and their
reversal policy (e.g., Supertrend reverses on flip; Donchian doesn't;
mean-reversion exits at the middle band). The mixin covers the parts
that were provably duplicated: the last-bar read, the balance read,
the SL/TP/qty math, and the bracket submission call.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import OrderSide

from src.strategies.config import BaseStrategyConfig

if TYPE_CHECKING:
    from nautilus_trader.model.data import Bar

    from src.orders.signal import SignalType


logger = logging.getLogger(__name__)


def is_atr_unsafe(atr_raw: float | None) -> bool:
    """Return True when ATR is None, non-finite, or non-positive.

    Centralised so every bracket strategy shares the same definition of
    "ATR cannot be passed to the bracket helper" — covers NaN, +/-inf,
    None (early warmup), 0 (flat-bar H=L=C), and negative (synthetic
    rollover gaps) in one predicate. Without this guard,
    :meth:`ATRStopMixin._validated_offset` rejects the value with
    ``ValueError`` and the exception unwinds through the bar callback,
    halting the engine on a single noisy bar.
    """
    if atr_raw is None:
        return True
    if isinstance(atr_raw, float) and not math.isfinite(atr_raw):
        return True
    return atr_raw <= 0


class BracketStrategyConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    """Shared config fields for ATR-bracket strategies.

    Each concrete ``*Config`` subclasses this to inherit the common
    bracket fields (ATR, risk, pip, sl/tp multipliers). Nautilus
    ``StrategyConfig`` is msgspec-backed, so this must be a proper
    subclass — a plain Python mixin won't surface the fields into the
    msgspec schema.
    """

    atr_period: int = 14
    sl_atr_mult: Decimal = Decimal("1.5")
    tp_atr_mult: Decimal = Decimal("3.0")
    risk_percent: Decimal = Decimal("1.0")
    pip_size: Decimal = Decimal("0.01")
    pip_value_per_lot: Decimal = Decimal("1.0")

    # Phase 1 — scale-out + trail tactics (Epic 13).
    # Both flags default False so legacy strategies keep single-fill +
    # hard-TP behaviour. When scale_out_enabled flips True, the bracket
    # helper closes ``scale_out_close_fraction`` at +``scale_out_r_trigger``R,
    # moves SL to BE if ``breakeven_at_r`` is not None, and (when
    # trailing_enabled) tightens SL on the remainder via the Supertrend
    # ATR trail. ``safety_tp_atr_mult`` is the runaway-protection cap
    # used by the strategy as a TP ceiling regardless of mode (see
    # implementation plan §1).
    scale_out_enabled: bool = False
    scale_out_r_trigger: Decimal = Decimal("1.0")
    scale_out_close_fraction: Decimal = Decimal("0.5")
    breakeven_at_r: Decimal | None = Decimal("1.0")
    trailing_enabled: bool = False
    trailing_method: str = "supertrend"
    trailing_atr_period: int = 7
    trailing_atr_multiplier: Decimal = Decimal("2.1")
    safety_tp_atr_mult: Decimal = Decimal("6.0")

    def __post_init__(self) -> None:
        if self.atr_period <= 0:
            raise ValueError(
                f"atr_period must be positive, got {self.atr_period}"
            )
        for field_name in (
            "sl_atr_mult",
            "tp_atr_mult",
            "risk_percent",
            "pip_size",
            "pip_value_per_lot",
        ):
            value = getattr(self, field_name)
            if value <= 0:
                raise ValueError(
                    f"{field_name} must be > 0, got {value}"
                )
        # R:R below 1 is degenerate for ATR brackets — TP closer to entry
        # than SL implies the strategy expects to lose on average. Reject
        # equality too so 1:1 (no-edge) configs cannot ship by accident.
        if self.sl_atr_mult >= self.tp_atr_mult:
            raise ValueError(
                "sl_atr_mult must be < tp_atr_mult (R:R > 1), "
                f"got sl={self.sl_atr_mult} tp={self.tp_atr_mult}"
            )

        # Safety cap is always read by the strategy regardless of mode
        # (implementation plan §1: TP ceiling in both hard-TP and trail
        # modes). Gating this on scale_out_enabled would let a legacy
        # config ship with safety_tp_atr_mult=0 and silently break the
        # moment the operator flips the flag.
        if self.safety_tp_atr_mult <= 0:
            raise ValueError(
                f"safety_tp_atr_mult must be > 0, got {self.safety_tp_atr_mult}"
            )

        # Phase 1 invariants only fire when the relevant flag is on, so
        # operators can stage YAML defaults that pass validation while
        # the feature is still disabled.
        if self.scale_out_enabled:
            if self.scale_out_r_trigger <= 0:
                raise ValueError(
                    "scale_out_r_trigger must be > 0, "
                    f"got {self.scale_out_r_trigger}"
                )
            if not (
                Decimal("0") < self.scale_out_close_fraction < Decimal("1")
            ):
                raise ValueError(
                    "scale_out_close_fraction must be in (0, 1), "
                    f"got {self.scale_out_close_fraction}"
                )
            if self.breakeven_at_r is not None and self.breakeven_at_r <= 0:
                raise ValueError(
                    "breakeven_at_r must be > 0 when set, "
                    f"got {self.breakeven_at_r}"
                )
            # The state machine moves SL to BE at the same bar as the
            # partial close (implementation plan §1). A breakeven trigger
            # set ABOVE the partial-close trigger means the trail
            # tightens before BE ever fires — silent tactic regression.
            if (
                self.breakeven_at_r is not None
                and self.breakeven_at_r > self.scale_out_r_trigger
            ):
                raise ValueError(
                    "breakeven_at_r must be <= scale_out_r_trigger "
                    "(BE moves at the partial close, not after it), "
                    f"got be={self.breakeven_at_r} "
                    f"trigger={self.scale_out_r_trigger}"
                )

        if self.trailing_enabled:
            # Trail tightens the remaining size after partial close —
            # without scale-out there is no remainder to tighten against.
            if not self.scale_out_enabled:
                raise ValueError(
                    "trailing_enabled requires scale_out_enabled=True "
                    "(trail applies only to the remainder after partial close)"
                )
            if self.trailing_method != "supertrend":
                raise ValueError(
                    "trailing_method must be 'supertrend' in Phase 1, "
                    f"got {self.trailing_method!r}"
                )
            if self.trailing_atr_period <= 0:
                raise ValueError(
                    "trailing_atr_period must be > 0, "
                    f"got {self.trailing_atr_period}"
                )
            if self.trailing_atr_multiplier <= 0:
                raise ValueError(
                    "trailing_atr_multiplier must be > 0, "
                    f"got {self.trailing_atr_multiplier}"
                )


class BracketStrategyMixin:
    """Reusable bracket-order machinery.

    Requires the host to provide:
    - ``self.cache`` (Nautilus cache, for last-bar reads)
    - ``self.portfolio`` (Nautilus portfolio, for balance reads)
    - ``self.config`` with ``bar_type``, ``sl_atr_mult``, ``tp_atr_mult``,
      ``pip_size``, ``pip_value_per_lot``
    - ``self.calculate_atr_stop`` / ``calculate_atr_take_profit`` (from
      ``ATRStopMixin``)
    - ``self.size_from_risk`` (from ``RiskSizedMixin``)
    - ``self._submit_bracket_order`` (from ``BaseStrategy``)
    """

    def _last_bar(self) -> Bar | None:
        """Retrieve the most recent bar from the Nautilus cache.

        Narrows the catch to ``IndexError`` / ``KeyError`` / ``LookupError``
        — the three cases Nautilus can reasonably raise on an empty
        cache. Programming errors (missing cache, wrong args) propagate
        so they surface as loud test failures rather than silent
        zero-signal runs.
        """
        try:
            return self.cache.bar(self.config.bar_type, index=0)  # type: ignore[attr-defined]
        except (IndexError, KeyError, LookupError):
            return None

    def _read_account_balance(self) -> Decimal:
        """Return live account equity, or ``Decimal("0")`` when unavailable.

        A zero balance propagates through ``RiskBasedPositionSizer`` as
        "insufficient capital", which makes the bracket helper skip the
        trade. Returning a hardcoded fallback here would invent capital
        that doesn't exist — misconfigured backtests would silently
        produce phantom-balance runs instead of the loud zero-trade
        signal we want.
        """
        venue = self.config.bar_type.instrument_id.venue  # type: ignore[attr-defined]
        try:
            account = self.portfolio.account(venue)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("portfolio.account(%s) raised; treating as $0", venue)
            return Decimal("0")
        if account is None:
            logger.warning("portfolio has no account for %s; treating as $0", venue)
            return Decimal("0")
        balance = account.balance_total(USD)
        if balance is None:
            logger.warning("balance_total is None for %s; treating as $0", venue)
            return Decimal("0")
        # str(float) round-trip is deliberate: ``Decimal(float)`` picks
        # up the binary-representation noise (e.g. 0.1 → 0.1000000000...);
        # str() gives a clean repr capped at ~15 significant digits,
        # which is sufficient for balance math.
        return Decimal(str(balance.as_double()))

    def _compute_bracket_params(
        self,
        *,
        side: OrderSide,
        entry_price: Decimal,
        atr_value: Decimal,
        account_balance: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Return ``(qty, sl_price, tp_price)`` from ATR + risk sizing."""
        cfg = self.config  # type: ignore[attr-defined]
        sl_price = self.calculate_atr_stop(  # type: ignore[attr-defined]
            side=side,
            entry_price=entry_price,
            atr_value=atr_value,
            multiplier=cfg.sl_atr_mult,
        )
        tp_price = self.calculate_atr_take_profit(  # type: ignore[attr-defined]
            side=side,
            entry_price=entry_price,
            atr_value=atr_value,
            multiplier=cfg.tp_atr_mult,
        )
        qty = self.size_from_risk(  # type: ignore[attr-defined]
            account_balance=account_balance,
            entry_price=entry_price,
            stop_price=sl_price,
            pip_value_per_lot=cfg.pip_value_per_lot,
            pip_size=cfg.pip_size,
        )
        return qty, sl_price, tp_price

    def _submit_bracket_for_entry(
        self, signal: SignalType, atr_value: Decimal
    ) -> None:
        """Build + submit a market bracket for a BUY/SELL signal.

        Expects the caller to have already handled position-reversal or
        CLOSE semantics — this helper only dispatches new entries when
        ``self.is_flat`` is True. A ``NONE`` signal is a no-op.
        """
        from src.orders.signal import SignalType as _SignalType

        if signal == _SignalType.NONE:
            return
        if not self.is_flat:  # type: ignore[attr-defined]
            return

        side = OrderSide.BUY if signal == _SignalType.BUY else OrderSide.SELL
        last_bar = self._last_bar()
        if last_bar is None:
            return
        entry_price = Decimal(str(last_bar.close.as_double()))
        balance = self._read_account_balance()
        qty, sl, tp = self._compute_bracket_params(
            side=side,
            entry_price=entry_price,
            atr_value=atr_value,
            account_balance=balance,
        )
        self._submit_bracket_order(  # type: ignore[attr-defined]
            side=side, quantity=qty, sl_price=sl, tp_price=tp
        )
