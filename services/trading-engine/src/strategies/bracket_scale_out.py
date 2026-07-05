"""BracketScaleOutMixin — scale-out + trail state machine.

Tracks per-trade state through the ``INITIAL → SCALED_OUT_BE → flat``
transitions described in implementation plan §1. Composes the
``_close_partial`` / ``_modify_sl`` helpers added to ``BaseStrategy`` in
story 13.3; the trail body (story 13.6) tightens SL via a dedicated
Supertrend instance (``trailing_atr_period`` × ``trailing_atr_multiplier``).

Two modes (entry-exit-trailing analysis 2026-07-05 §3.5):

* **Scale-out** (``scale_out_enabled``): partial close at
  +``scale_out_r_trigger``R → SL to breakeven (+ optional
  ``breakeven_offset_pips`` cost-recovery offset) → trail the remainder
  when ``trailing_enabled``.
* **Trail-only** (``trailing_enabled`` without ``scale_out_enabled``):
  no partial close, no BE — the full position keeps its original hard
  SL until the trail line ratchets past it (Turtle-style).

Host wiring (``on_event`` / ``on_bar`` overrides) lives at the bottom
of this class — hosts prepend the mixin in their MRO and expose a
``_supertrend_trail`` attribute.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from nautilus_trader.core.message import Event
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.model.events import PositionClosed, PositionOpened

from src.instruments import get_contract_spec

if TYPE_CHECKING:
    from nautilus_trader.model.data import Bar

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
    # Price the BE move targets: entry ± breakeven_offset_pips×pip_size
    # (cost recovery). ``None`` → exact entry (legacy behaviour, and the
    # fallback when pip economics are unavailable at init time).
    be_price: Decimal | None = None


@dataclass
class _ScaleOutTradeState:
    """Per-trade state while ``scale_out_enabled`` is True.

    ``setup`` is frozen (captured once, never rewritten); the three
    booleans + ``current_sl`` mutate as the state machine progresses
    through ``INITIAL → SCALED_OUT_BE → flat`` transitions.

    ``current_sl`` tracks the live SL trigger price so the trail body
    in story 13.6 can compare candidate trail lines against the
    last-known SL — only tighten, never loosen.
    """

    setup: _ScaleOutSetup
    current_sl: Decimal
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
        pip_size: Decimal | None = None,
    ) -> None:
        """Capture trade entry context.

        No-op unless ``scale_out_enabled`` or ``trailing_enabled`` is on
        (trail-only mode also needs the setup baseline for tighten-only
        comparisons). Must be called by the host immediately after the
        bracket entry fills. Calling a second time without an intervening
        ``_clear_scale_state`` will overwrite the previous state — the
        host is expected to clear on position-close events.

        ``pip_size`` feeds the ``breakeven_offset_pips`` → price
        conversion; when omitted (synthetic instruments, direct test
        calls) the BE move falls back to the exact entry price.
        """
        cfg = self._cfg()
        if not (cfg.scale_out_enabled or cfg.trailing_enabled):
            return
        risk_per_unit = abs(entry_price - sl_price)
        self._scale_state = _ScaleOutTradeState(
            setup=_ScaleOutSetup(
                entry_price=entry_price,
                initial_sl=sl_price,
                initial_qty=qty,
                side=side,
                risk_per_unit=risk_per_unit,
                be_price=self._compute_be_price(
                    side=side,
                    entry_price=entry_price,
                    risk_per_unit=risk_per_unit,
                    pip_size=pip_size,
                ),
            ),
            current_sl=sl_price,
        )

    def _compute_be_price(
        self,
        *,
        side: OrderSide,
        entry_price: Decimal,
        risk_per_unit: Decimal,
        pip_size: Decimal | None,
    ) -> Decimal | None:
        """Breakeven target = entry ± cost-recovery offset, or None (=entry).

        Falls back to ``None`` (exact-entry BE) when the offset is zero,
        pip economics are unavailable, or the offset would eat the whole
        BE-trigger cushion (SL at/above the market on the BE bar → the
        remainder would be stopped instantly).
        """
        cfg = self._cfg()
        offset_pips = cfg.breakeven_offset_pips
        if offset_pips is None or offset_pips <= 0:
            return None
        # BE only ever fires in scale-out mode with a BE trigger set —
        # computing an offset price outside that is dead state.
        if not cfg.scale_out_enabled or cfg.breakeven_at_r is None:
            return None
        if pip_size is None:
            logger.warning(
                "breakeven_offset_pips=%s configured but pip_size "
                "unavailable at trade init — falling back to exact-entry BE",
                offset_pips,
            )
            return None
        offset = offset_pips * pip_size
        # breakeven_at_r is not None here (early return above).
        cushion = cfg.breakeven_at_r * risk_per_unit
        if offset >= cushion:
            logger.warning(
                "breakeven offset %s >= BE-trigger cushion %s "
                "(offset would stop the remainder instantly) — "
                "falling back to exact-entry BE",
                offset,
                cushion,
            )
            return None
        if side == OrderSide.BUY:
            return entry_price + offset
        return entry_price - offset

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

            1. partial close at +``scale_out_r_trigger``R, scale-out
               mode only (sets ``scaled_out`` to True)
            2. SL → breakeven target (entry + cost-recovery offset) at
               +``breakeven_at_r``R, only if config is not None
               (sets ``breakeven_moved`` to True)
            3. activate trail — after the BE move in scale-out mode,
               or immediately in trail-only mode (sets ``trail_active``)
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

        # Step 1: partial close at +scale_out_r_trigger × R (scale-out
        # mode only — trail-only mode never reduces the position).
        if (
            cfg.scale_out_enabled
            and not st.scaled_out
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
            be_price = (
                setup.be_price if setup.be_price is not None
                else setup.entry_price
            )
            # Only advance state when the broker-side modify succeeds —
            # a failed modify (SL leg not found) leaves breakeven_moved
            # False so the next bar retries instead of desyncing
            # current_sl from the live order.
            if self._modify_sl(be_price):
                st.breakeven_moved = True
                st.current_sl = be_price
                self._log.info(f"SL moved to breakeven at {be_price}")

        # Step 3: activate trail. Scale-out mode: after the BE move —
        # or after the partial close when BE is deliberately disabled
        # (breakeven_at_r=None). Trail-only mode: immediately — the
        # trail ratchets from the original hard SL, no BE anchor exists.
        if (
            not st.trail_active
            and cfg.trailing_enabled
            and (
                st.breakeven_moved
                or not cfg.scale_out_enabled
                or (st.scaled_out and cfg.breakeven_at_r is None)
            )
        ):
            st.trail_active = True
            self._log.info("Trailing activated")

        # Step 4: update trail SL each bar while active (tighten-only
        # Supertrend line — see _update_trailing_sl).
        if st.trail_active:
            self._update_trailing_sl(st)

    def _update_trailing_sl(self, state: _ScaleOutTradeState) -> None:
        """Tighten SL via the Supertrend trail line. Tightens-only.

        Reads ``self._supertrend_trail`` (Supertrend instance configured
        with the Phase 1 ``trailing_atr_period`` / ``trailing_atr_multiplier``
        — separate instance from the signal-generating Supertrend so the
        host can pick distinct params). The Supertrend ``value`` IS the
        trail line: ``final_lower`` in uptrend, ``final_upper`` in
        downtrend (see ``src/indicators/supertrend.py:64-66``).

        Skip conditions (each silent):

        - ``_supertrend_trail`` missing — host wiring failure; defensive.
        - Trail not yet ``initialized`` — ATR warmup not complete.
        - Trail ``value`` is None — belt-and-braces (initialized=True
          but value not yet computed on the boundary bar).
        - Trail trend mismatches position side — when the trail's own
          Supertrend flips against the position, ``value`` jumps to the
          opposite band (above price for LONG → invalid SL). Side-check
          filters that out before the loosen-check could ever trigger
          a wrong-direction modify.
        - New SL would loosen vs ``state.current_sl`` (LONG: ≤; SHORT: ≥).
          Strict inequality so equal-value bars don't burn a redundant
          modify call.
        """
        trail = getattr(self, "_supertrend_trail", None)
        if trail is None or not trail.initialized:
            return

        new_line = trail.value
        if new_line is None:
            return

        new_sl = Decimal(str(new_line))
        setup = state.setup

        if setup.side == OrderSide.BUY:
            # LONG: trail must be in uptrend AND tighten toward price.
            if trail.trend != 1 or new_sl <= state.current_sl:
                return
        else:
            # SHORT: trail must be in downtrend AND tighten toward price.
            if trail.trend != -1 or new_sl >= state.current_sl:
                return

        # Advance the tracked SL only on a successful modify — keeps
        # current_sl in sync with the live order so a transient failure
        # is retried on the next bar instead of silently skipped.
        if self._modify_sl(new_sl):
            state.current_sl = new_sl

    def _cfg(self) -> "BracketStrategyConfig":
        """Typed alias for ``self.config``.

        TODO(mypy): drop the ignore once mypy is wired into CI and
        the host strategy class is annotated to expose ``config``.
        """
        return self.config  # type: ignore[attr-defined,no-any-return]

    # --- Host wiring ------------------------------------------------------
    #
    # Stories 13.5 / 13.10 / 13.11 each shipped copy-equivalent versions
    # of the five methods below directly on their host strategy class
    # (Supertrend, Donchian, MA crossover). Once the third user landed,
    # the rule of three hit and the methods were lifted here so the
    # mixin is the single source of truth for the scale-out lifecycle.
    # Hosts only need to (a) prepend ``BracketScaleOutMixin`` in their
    # MRO, (b) expose a ``_supertrend_trail`` attribute (set in their
    # own ``__init__``), and (c) optionally override these methods if
    # they need behaviour beyond the standard wiring.

    def on_event(self, event: "Event") -> None:
        """Extend the host's ``on_event`` to feed the scale-out mixin.

        ``super().on_event`` updates ``self._position`` from the cache;
        we then dispatch the event into the scale-out state machine.
        """
        super().on_event(event)  # type: ignore[misc]
        self._dispatch_scale_out_event(event)

    def _dispatch_scale_out_event(self, event: "Event") -> None:
        """Forward position lifecycle events into the state machine.

        Handles ``PositionOpened`` (best-effort init — the bracket's
        SL leg may still be in PENDING state at that exact tick, in
        which case ``_try_init_scale_state`` no-ops cleanly and the
        bar evaluator retries) and ``PositionClosed`` (clear state).
        Unrelated events are ignored.
        """
        cfg = self._cfg()
        if not (cfg.scale_out_enabled or cfg.trailing_enabled):
            return
        if isinstance(event, PositionOpened):
            self._try_init_scale_state()
        elif isinstance(event, PositionClosed):
            self._clear_scale_state()

    def _try_init_scale_state(self) -> None:
        """Best-effort scale-out init from the live position + SL leg.

        Returns silently when ``_scale_state`` is already set, the host
        has no ``_position``, or the bracket's SL is not yet in cache
        (PENDING after a fresh ``PositionOpened``). Retried each bar
        by ``_evaluate_scale_out_for_bar`` until the bracket's SL is
        visible — at which point init completes and the state machine
        becomes active for the rest of the trade.
        """
        if self._scale_state is not None:
            return
        position = self._position  # type: ignore[attr-defined]
        if position is None:
            return
        sl_order = self._find_active_sl_order()  # type: ignore[attr-defined]
        if sl_order is None:
            return
        side = (
            OrderSide.BUY
            if position.side == PositionSide.LONG
            else OrderSide.SELL
        )
        # Pip economics only matter when the BE offset can actually
        # fire (scale-out mode + BE trigger set + offset > 0); skip the
        # fail-loud contract-spec lookup in every other mode so
        # synthetic instruments (smoke tests) and trail-only configs
        # with a stray offset never crash the event path.
        cfg = self._cfg()
        pip_size: Decimal | None = None
        if (
            cfg.scale_out_enabled
            and cfg.breakeven_at_r is not None
            and cfg.breakeven_offset_pips > 0
        ):
            pip_size = get_contract_spec(
                str(position.instrument_id)
            ).pip_size
        self._init_scale_state(
            side=side,
            entry_price=Decimal(str(position.avg_px_open)),
            sl_price=Decimal(str(sl_order.trigger_price.as_double())),
            qty=Decimal(str(position.quantity.as_double())),
            pip_size=pip_size,
        )

    def on_bar(self, bar: "Bar") -> None:
        """Extend the host's ``on_bar`` to drive the scale-out evaluator.

        ``super().on_bar`` runs the existing signal logic (generate +
        execute). The scale-out evaluator runs AFTER signals so a flip
        signal that closes the position clears state via the resulting
        ``PositionClosed`` event before the next bar's evaluator runs.
        """
        super().on_bar(bar)  # type: ignore[misc]
        self._evaluate_scale_out_for_bar(bar)

    def _evaluate_scale_out_for_bar(self, bar: "Bar") -> None:
        """Drive the scale-out state machine off the latest bar close.

        No-op when both scale-out and trailing are disabled, or the
        host is flat. When in position but ``_scale_state`` is None,
        retry init — covers the PositionOpened-vs-SL-leg race
        documented in Story 13.7.
        """
        cfg = self._cfg()
        if not (cfg.scale_out_enabled or cfg.trailing_enabled):
            return
        if self.is_flat:  # type: ignore[attr-defined]
            return
        if self._scale_state is None:
            self._try_init_scale_state()
            if self._scale_state is None:
                return
        self.evaluate_scale_out(Decimal(str(bar.close.as_double())))
