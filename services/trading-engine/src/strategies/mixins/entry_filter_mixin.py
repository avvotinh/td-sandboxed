"""Track 5.1 entry filters — ADX trend-strength gate + session window.

Both filters are config-driven off :class:`BracketStrategyConfig`
(``adx_gate_min`` / ``session_filter_tz``, default-OFF) and target the
Phase 12.A diagnosis: the trend-followers' problem is the *volume of
low-quality entries*, not the entry sign (epic-12a-rerun-2y-verdict.md
§2.5, entry-exit-trailing analysis §"#1").

The mixin owns the lifecycle of the gate's ADX indicator and the
session predicate; each strategy wires four one-liners:

* ``__init__``      → ``self._init_entry_filters()``
* ``on_start``      → ``self._register_entry_filter_indicators()``
* ``on_reset``      → ``self._reset_entry_filters()``
* ``generate_signal`` top → early-return on ``self._session_gate(bar)``;
  entry branches guarded by ``self._adx_gate_blocks()``.

Host contract (satisfied by the standard ``BaseStrategy`` composition):
``self.config`` (a ``BracketStrategyConfig``), ``self.is_flat``,
``self.register_indicator_for_bars``, and ``self._in_session`` (the
``SessionFilterMixin`` delegate on ``BaseStrategy``).
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Any

from src.indicators import ADX
from src.orders.signal import SignalType

if TYPE_CHECKING:
    from nautilus_trader.model.data import Bar


# Host members the mixin's methods rely on — enforced at class-definition
# time by __init_subclass__ (same fail-fast pattern as BracketStrategyMixin).
_ENTRY_FILTER_HOST_REQUIRED: tuple[str, ...] = (
    "register_indicator_for_bars",
    "_in_session",
    "is_flat",
)


class EntryFilterMixin:
    """ADX gate + session-window filter for bracket strategies."""

    _entry_adx: ADX | None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Fail a mis-composed concrete strategy at definition time.

        Mirrors ``BracketStrategyMixin.__init_subclass__``: a strategy
        missing the ``BaseStrategy`` surface this mixin calls would
        otherwise fail only on its first gated signal, deep inside a
        backtest. (Calling ``_init_entry_filters`` in ``__init__`` is
        still the host's responsibility — the ``AttributeError`` on
        ``_entry_adx`` is loud and immediate if forgotten.)
        """
        super().__init_subclass__(**kwargs)
        from src.strategies.base_strategy import BaseStrategy

        if not issubclass(cls, BaseStrategy):
            return
        missing = [
            name for name in _ENTRY_FILTER_HOST_REQUIRED if not hasattr(cls, name)
        ]
        if missing:
            raise TypeError(
                f"{cls.__name__} composes EntryFilterMixin but is missing "
                f"host member(s): {', '.join(missing)}."
            )

    def _init_entry_filters(self) -> None:
        """Create the gate's ADX indicator iff the gate is enabled."""
        cfg = self.config
        self._entry_adx = (
            ADX(cfg.adx_gate_period) if cfg.adx_gate_min is not None else None
        )

    def _register_entry_filter_indicators(self) -> None:
        if self._entry_adx is not None:
            self.register_indicator_for_bars(self.config.bar_type, self._entry_adx)

    def _reset_entry_filters(self) -> None:
        if self._entry_adx is not None:
            self._entry_adx.reset()

    def _adx_gate_blocks(self) -> bool:
        """True while the ADX gate is enabled and not showing trend strength.

        Warmup counts as blocked (~2×period bars): entering before the
        gate can measure trend strength would silently disable the
        filter exactly at backtest start / after a reset.
        """
        adx = self._entry_adx
        if adx is None:
            return False
        value = adx.value
        return (
            not adx.initialized
            or value is None
            or value < float(self.config.adx_gate_min)
        )

    def _session_gate(self, bar: Bar) -> SignalType | None:
        """Session-window decision for this bar. ``None`` = proceed.

        In-session (or filter off) → ``None``: the strategy evaluates
        its signal normally. Out-of-session:

        * policy ``"flatten"``  → ``CLOSE`` while a position is open,
          else ``NONE`` (trend shape: no unrewarded overnight risk).
        * policy ``"block_entry"`` → ``NONE`` when flat (blocks fresh
          entries); ``None`` (pass) when a position is open so the
          strategy's own exit logic keeps managing the trade — entry
          branches are unreachable with an open position, all roster
          strategies guard entries on ``is_flat``.
        """
        cfg = self.config
        if cfg.session_filter_tz is None:
            return None
        ts = datetime.fromtimestamp(bar.ts_init // 1_000_000_000, tz=UTC)
        in_session = self._in_session(
            ts,
            session_start=time(
                cfg.session_filter_open_hour, cfg.session_filter_open_minute
            ),
            session_end=time(
                cfg.session_filter_close_hour, cfg.session_filter_close_minute
            ),
            tz=cfg.session_filter_tz,
        )
        if in_session:
            return None
        if cfg.session_filter_exit_policy == "flatten":
            return SignalType.NONE if self.is_flat else SignalType.CLOSE
        # block_entry
        return SignalType.NONE if self.is_flat else None
