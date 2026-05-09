"""BracketScaleOutMixin — Phase 1 scale-out + trail state machine.

Tracks per-trade state through the ``INITIAL → SCALED_OUT_BE → flat``
transitions described in implementation plan §1. Composes the
``_close_partial`` / ``_modify_sl`` helpers added to ``BaseStrategy`` in
story 13.3; the trail-update body is intentionally a no-op stub here
and lands in story 13.6 (Supertrend ATR(7)×2.1 trailing indicator).

The mixin is a behavior add-on: hosts that include it must wire
``_init_scale_state`` in their ``on_position_opened`` event handler,
``_clear_scale_state`` in their ``on_position_closed`` handler, and
call ``evaluate_scale_out`` from their ``on_bar`` after the existing
signal logic. Host wiring lives in story 13.5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from nautilus_trader.model.enums import OrderSide

if TYPE_CHECKING:
    from src.strategies.bracket_strategy import BracketStrategyConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ScaleOutSetup:
    """Captured-once trade entry context.

    Frozen because these five fields are baselined at
    ``_init_scale_state`` time and any later mutation would corrupt the
    R-multiple computation in ``evaluate_scale_out``. Splitting the
    captured fields into a frozen sub-record makes the immutability
    contract enforced rather than aspirational.
    """

    entry_price: Decimal
    initial_sl: Decimal
    initial_qty: Decimal
    side: OrderSide
    risk_per_unit: Decimal


@dataclass
class _ScaleOutTradeState:
    """Per-trade state while ``scale_out_enabled`` is True.

    ``setup`` is frozen (captured once, never rewritten); the three
    booleans flip during evaluation as the state machine progresses
    through ``INITIAL → SCALED_OUT_BE → flat`` transitions.
    """

    setup: _ScaleOutSetup
    scaled_out: bool = False
    breakeven_moved: bool = False
    trail_active: bool = False


class BracketScaleOutMixin:
    """Phase 1 scale-out + trail state machine.

    Host requirements (duck-typed contract — the mixin uses ``Any`` on
    helper signatures because the host type is composed at MRO time
    and concrete types depend on which strategy is mixed in):

    - ``self.config``: a ``BracketStrategyConfig`` exposing
      ``scale_out_enabled``, ``scale_out_r_trigger``,
      ``scale_out_close_fraction``, ``breakeven_at_r``, and
      ``trailing_enabled`` (story 13.2).
    - ``self._close_partial(fraction)`` returning ``Order | None``
      (story 13.3 on ``BaseStrategy``).
    - ``self._modify_sl(price)`` returning ``bool`` (story 13.3).
    - ``self._log``: a Nautilus logger surface (provided by
      ``Strategy`` parent).

    Lifecycle (driven by host strategy in story 13.5):

        host.on_position_opened(event) → self._init_scale_state(...)
        host.on_bar(bar)               → self.evaluate_scale_out(close)
        host.on_position_closed(event) → self._clear_scale_state()
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._scale_state: _ScaleOutTradeState | None = None

    def _init_scale_state(
        self,
        *,
        side: OrderSide,
        entry_price: Decimal,
        sl_price: Decimal,
        qty: Decimal,
    ) -> None:
        """Capture trade entry context. No-op when ``scale_out_enabled`` is False.

        Must be called by the host immediately after the bracket entry
        fills (story 13.5 wires this into ``on_position_opened``). Calling
        a second time without an intervening ``_clear_scale_state`` will
        overwrite the previous state — the host is expected to clear on
        position-close events.
        """
        cfg = self._cfg()
        if not cfg.scale_out_enabled:
            return
        self._scale_state = _ScaleOutTradeState(
            setup=_ScaleOutSetup(
                entry_price=entry_price,
                initial_sl=sl_price,
                initial_qty=qty,
                side=side,
                risk_per_unit=abs(entry_price - sl_price),
            ),
        )

    def _clear_scale_state(self) -> None:
        """Reset state on position close. Idempotent — safe to call when flat."""
        self._scale_state = None

    def evaluate_scale_out(self, current_price: Decimal) -> None:
        """Evaluate state-machine transitions for the latest bar close.

        Idempotent: each transition guard is gated by the corresponding
        ``scaled_out`` / ``breakeven_moved`` / ``trail_active`` flag, so
        calling once per bar is safe even when several bars sit at the
        same price.

        Transitions (in order, single bar):

            1. partial close at +``scale_out_r_trigger``R
               (sets ``scaled_out`` to True)
            2. SL → breakeven at +``breakeven_at_r``R, only if config
               is not None (sets ``breakeven_moved`` to True)
            3. activate trail after BE move, only if
               ``trailing_enabled`` (sets ``trail_active`` to True)
            4. update trail SL each bar while ``trail_active``
        """
        st = self._scale_state
        if st is None or st.setup.risk_per_unit <= 0:
            # st is None means we're flat or scale_out is disabled.
            # risk_per_unit <= 0 is a degenerate entry (entry == SL):
            # division would either zero out or raise; skip cleanly.
            return

        cfg = self._cfg()
        setup = st.setup

        if setup.side == OrderSide.BUY:
            unrealized_r = (current_price - setup.entry_price) / setup.risk_per_unit
        else:
            unrealized_r = (setup.entry_price - current_price) / setup.risk_per_unit

        # Step 1: partial close at +scale_out_r_trigger × R.
        if (
            not st.scaled_out
            and unrealized_r >= cfg.scale_out_r_trigger
        ):
            self._close_partial(cfg.scale_out_close_fraction)
            st.scaled_out = True
            # Nautilus Logger.info takes a single str message; f-string
            # is the only option (no lazy %-style formatting). The
            # branch fires at most once per trade so eager formatting
            # cost is bounded.
            self._log.info(
                f"Scale-out triggered at R={float(unrealized_r):.2f}, "
                f"closed {float(cfg.scale_out_close_fraction * 100):.0f}% "
                "of position"
            )

        # Step 2: SL → breakeven (only after partial close fired).
        # The 13.2 invariant guarantees breakeven_at_r ≤ scale_out_r_trigger,
        # so this branch is reachable on the same bar that fires Step 1.
        if (
            st.scaled_out
            and not st.breakeven_moved
            and cfg.breakeven_at_r is not None
            and unrealized_r >= cfg.breakeven_at_r
        ):
            self._modify_sl(setup.entry_price)
            st.breakeven_moved = True
            self._log.info(f"SL moved to breakeven at {setup.entry_price}")

        # Step 3: activate trail (only after BE move; trailing_enabled
        # requires scale_out_enabled per 13.2 invariant).
        if (
            st.breakeven_moved
            and not st.trail_active
            and cfg.trailing_enabled
        ):
            st.trail_active = True
            self._log.info("Trailing activated")

        # Step 4: update trail SL each bar while active. Body lands in
        # story 13.6 — until then the call is a no-op stub.
        if st.trail_active:
            self._update_trailing_sl(st)

    def _update_trailing_sl(self, state: _ScaleOutTradeState) -> None:
        """Tighten SL via Supertrend trail line. Body in story 13.6.

        Story 13.6 will:
        - Read ``self._supertrend_trail.value`` (Supertrend instance
          configured with ``trailing_atr_period`` / ``trailing_atr_multiplier``
          per 13.2 config).
        - Compute the candidate SL price from the trail line, side-aware.
        - Call ``self._modify_sl(new_price)`` ONLY if it tightens vs the
          current SL (no loosening — implementation plan §1 invariant).

        Until 13.6 lands, this stub is a deliberate no-op so 13.4 can
        ship the state machine in isolation. Tests in 13.4 verify the
        delegation (called when ``trail_active``, not called otherwise);
        the actual tightening logic is exercised in 13.6 tests.
        """
        # Intentional no-op — see docstring. Story 13.6 fills the body.
        return

    def _cfg(self) -> "BracketStrategyConfig":
        """Typed alias for ``self.config``.

        TODO(mypy): drop the ignore once mypy is wired into CI and
        the host strategy class is annotated to expose ``config``.
        """
        return self.config  # type: ignore[attr-defined,no-any-return]
