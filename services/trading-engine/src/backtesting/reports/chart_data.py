"""Chart payload builder for the backtest chart viewer.

Transforms a finished backtest (bars + :class:`BacktestResult`) into the
JSON-ready payload the lightweight-charts HTML template consumes:

* ``candles`` — OHLCV rows keyed by epoch-second ``time`` (the format
  lightweight-charts expects).
* ``trades`` — entry/exit points plus bracket levels (initial SL, TP)
  and the SL modification path (breakeven move / trailing ratchets).
* ``indicators`` — per-strategy overlay + lower-pane series recomputed
  offline by feeding the SAME ``Bar`` stream through the SAME indicator
  classes the strategy used, so plotted lines match what the strategy
  saw bar-by-bar.

Everything here is pure transformation — no I/O, no Nautilus engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.indicators import RSI, Bollinger, Donchian
from src.indicators.adx import ADX
from src.indicators.supertrend import Supertrend

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    import pandas as pd
    from nautilus_trader.model.data import Bar

    from src.backtesting.result import BacktestResult, TradeRecord


# Panes the template knows how to lay out.
PANE_PRICE = "price"
PANE_LOWER = "lower"


@dataclass(frozen=True)
class ChartSeries:
    """One renderable line series.

    ``points`` items are ``{"time": <epoch s>, "value": <float>}``;
    a point with no ``value`` key is lightweight-charts whitespace and
    breaks the line (used for warmup gaps and trend-flip splits).
    """

    key: str
    title: str
    pane: str = PANE_PRICE
    color: str = "#2962ff"
    line_width: int = 1
    line_style: int = 0  # 0 solid, 1 dotted, 2 dashed
    points: list[dict[str, Any]] = field(default_factory=list)
    # Horizontal reference levels for lower-pane series (e.g. RSI 0.3/0.7).
    levels: tuple[float, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "pane": self.pane,
            "color": self.color,
            "lineWidth": self.line_width,
            "lineStyle": self.line_style,
            "points": self.points,
            "levels": list(self.levels),
        }


def candles_from_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    """OHLCV rows → lightweight-charts candlestick data (epoch seconds)."""
    times = (df.index.view("int64") // 1_000_000_000).tolist()
    opens = df["open"].astype(float).tolist()
    highs = df["high"].astype(float).tolist()
    lows = df["low"].astype(float).tolist()
    closes = df["close"].astype(float).tolist()
    volumes = (
        df["volume"].astype(float).tolist()
        if "volume" in df.columns
        else [0.0] * len(df)
    )
    return [
        {
            "time": t,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v,
        }
        for t, o, h, lo, c, v in zip(
            times, opens, highs, lows, closes, volumes, strict=True
        )
    ]


def _sl_path(trade: TradeRecord) -> list[dict[str, Any]]:
    """Step path of the SL level over the trade's lifetime.

    Starts at the initial bracket SL, walks each recorded modification
    (clamped into the trade window, consecutive duplicates dropped),
    and carries the final level to the exit timestamp so the step line
    spans the full trade.
    """
    if trade.sl_price is None:
        return []
    entry_t = int(trade.entry_ts.timestamp())
    exit_t = int(trade.exit_ts.timestamp())
    path: list[dict[str, Any]] = [
        {"time": entry_t, "price": float(trade.sl_price)}
    ]
    for update in trade.sl_updates:
        t = min(max(int(update.ts.timestamp()), entry_t), exit_t)
        price = float(update.price)
        if t <= path[-1]["time"]:
            # Same-bar modifications (BE move + trail ratchet on one
            # on_bar call) collapse to the last write — line-series data
            # must have strictly ascending unique times.
            path[-1] = {"time": path[-1]["time"], "price": price}
            continue
        if price == path[-1]["price"]:
            continue
        path.append({"time": t, "price": price})
    if path[-1]["time"] < exit_t:
        path.append({"time": exit_t, "price": path[-1]["price"]})
    return path


def trades_to_payload(trades: Iterable[TradeRecord]) -> list[dict[str, Any]]:
    """TradeRecord list → JSON rows sorted by entry time."""
    rows = []
    for trade in trades:
        rows.append(
            {
                "id": trade.trade_id,
                "side": trade.side,
                "entryTime": int(trade.entry_ts.timestamp()),
                "exitTime": int(trade.exit_ts.timestamp()),
                "entryPrice": float(trade.entry_price),
                "exitPrice": float(trade.exit_price),
                "quantity": float(trade.quantity),
                "pnl": float(trade.pnl),
                "sl": float(trade.sl_price) if trade.sl_price is not None else None,
                "tp": float(trade.tp_price) if trade.tp_price is not None else None,
                "slPath": _sl_path(trade),
            }
        )
    rows.sort(key=lambda r: (r["entryTime"], r["id"]))
    return rows


# --- Indicator recomputation -------------------------------------------


def _param_float(params: Mapping[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    return float(value)


def _param_int(params: Mapping[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    return int(value)


def _walk(
    bars: Sequence[Bar],
    times: Sequence[int],
    indicators: Mapping[str, Any],
    snapshot: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Feed every bar through ``indicators`` and snapshot values per bar.

    ``snapshot(indicators)`` returns ``{series_key: float | None}`` for
    the current bar; ``None`` becomes whitespace (gap) in the output so
    warmup periods and trend-flip splits render as broken lines.

    The key set is seeded from a pre-bar snapshot (all snapshot
    functions are total over uninitialized indicators), so an empty
    ``bars`` input yields every key mapped to ``[]`` instead of a
    ``KeyError`` in the caller.
    """
    out: dict[str, list[dict[str, Any]]] = {
        key: [] for key in snapshot(indicators)
    }
    for bar, t in zip(bars, times, strict=True):
        for indicator in indicators.values():
            indicator.handle_bar(bar)
        for key, value in snapshot(indicators).items():
            series = out[key]
            if value is None:
                series.append({"time": t})
            else:
                series.append({"time": t, "value": float(value)})
    return out


def _supertrend_series(
    params: Mapping[str, Any], bars: Sequence[Bar], times: Sequence[int]
) -> list[ChartSeries]:
    indicators = {
        "st": Supertrend(
            period=_param_int(params, "period", 10),
            multiplier=_param_float(params, "multiplier", 3.0),
        )
    }

    def snap(ind: Mapping[str, Any]) -> dict[str, float | None]:
        st = ind["st"]
        if not st.initialized or st.value is None:
            return {"up": None, "down": None}
        return {
            "up": st.value if st.trend == 1 else None,
            "down": st.value if st.trend == -1 else None,
        }

    walked = _walk(bars, times, indicators, snap)
    return [
        ChartSeries(
            key="supertrend_up",
            title="Supertrend (up)",
            color="#26a69a",
            line_width=2,
            points=walked["up"],
        ),
        ChartSeries(
            key="supertrend_down",
            title="Supertrend (down)",
            color="#ef5350",
            line_width=2,
            points=walked["down"],
        ),
    ]


def _donchian_series(
    params: Mapping[str, Any], bars: Sequence[Bar], times: Sequence[int]
) -> list[ChartSeries]:
    indicators = {"dc": Donchian(_param_int(params, "channel_period", 20))}

    def snap(ind: Mapping[str, Any]) -> dict[str, float | None]:
        dc = ind["dc"]
        if not dc.initialized:
            return {"upper": None, "lower": None}
        return {"upper": dc.upper, "lower": dc.lower}

    walked = _walk(bars, times, indicators, snap)
    return [
        ChartSeries(
            key="donchian_upper",
            title="Donchian upper",
            color="#2962ff",
            points=walked["upper"],
        ),
        ChartSeries(
            key="donchian_lower",
            title="Donchian lower",
            color="#f57c00",
            points=walked["lower"],
        ),
    ]


def _mean_reversion_series(
    params: Mapping[str, Any], bars: Sequence[Bar], times: Sequence[int]
) -> list[ChartSeries]:
    indicators = {
        "bb": Bollinger(
            period=_param_int(params, "bb_period", 20),
            k=_param_float(params, "num_std", 2.0),
        ),
        "rsi": RSI(_param_int(params, "rsi_period", 14)),
    }

    def snap(ind: Mapping[str, Any]) -> dict[str, float | None]:
        bb, rsi = ind["bb"], ind["rsi"]
        return {
            "bb_upper": bb.upper if bb.initialized else None,
            "bb_middle": bb.middle if bb.initialized else None,
            "bb_lower": bb.lower if bb.initialized else None,
            "rsi": rsi.value if rsi.initialized else None,
        }

    walked = _walk(bars, times, indicators, snap)
    oversold = _param_float(params, "oversold", 0.3)
    overbought = _param_float(params, "overbought", 0.7)
    return [
        ChartSeries(
            key="bb_upper",
            title="BB upper",
            color="#2962ff",
            points=walked["bb_upper"],
        ),
        ChartSeries(
            key="bb_middle",
            title="BB middle",
            color="#9e9e9e",
            line_style=2,
            points=walked["bb_middle"],
        ),
        ChartSeries(
            key="bb_lower",
            title="BB lower",
            color="#2962ff",
            points=walked["bb_lower"],
        ),
        ChartSeries(
            key="rsi",
            title=f"RSI ({_param_int(params, 'rsi_period', 14)})",
            pane=PANE_LOWER,
            color="#ab47bc",
            points=walked["rsi"],
            levels=(oversold, overbought),
        ),
    ]


_STRATEGY_SERIES_BUILDERS = {
    "supertrend": _supertrend_series,
    "donchian_breakout": _donchian_series,
    "mean_reversion": _mean_reversion_series,
}


def _trail_series(
    params: Mapping[str, Any], bars: Sequence[Bar], times: Sequence[int]
) -> list[ChartSeries]:
    """Supertrend trail line — only when the tactic is enabled."""
    if not params.get("trailing_enabled"):
        return []
    indicators = {
        "trail": Supertrend(
            period=_param_int(params, "trailing_atr_period", 7),
            multiplier=_param_float(params, "trailing_atr_multiplier", 2.1),
        )
    }

    def snap(ind: Mapping[str, Any]) -> dict[str, float | None]:
        trail = ind["trail"]
        if not trail.initialized or trail.value is None:
            return {"trail": None}
        return {"trail": trail.value}

    walked = _walk(bars, times, indicators, snap)
    return [
        ChartSeries(
            key="supertrend_trail",
            title=(
                f"Trail ST({_param_int(params, 'trailing_atr_period', 7)}, "
                f"{_param_float(params, 'trailing_atr_multiplier', 2.1)})"
            ),
            color="#ffb74d",
            line_style=1,
            points=walked["trail"],
        ),
    ]


def _adx_gate_series(
    params: Mapping[str, Any], bars: Sequence[Bar], times: Sequence[int]
) -> list[ChartSeries]:
    """ADX gate pane — only when the entry filter is configured."""
    adx_min = params.get("adx_gate_min")
    if adx_min is None:
        return []
    period = _param_int(params, "adx_gate_period", 14)
    indicators = {"adx": ADX(period)}

    def snap(ind: Mapping[str, Any]) -> dict[str, float | None]:
        adx = ind["adx"]
        return {"adx": adx.value if adx.initialized else None}

    walked = _walk(bars, times, indicators, snap)
    return [
        ChartSeries(
            key="adx",
            title=f"ADX ({period})",
            pane=PANE_LOWER,
            color="#26c6da",
            points=walked["adx"],
            levels=(float(adx_min),),
        ),
    ]


def compute_indicator_series(
    strategy_name: str,
    params: Mapping[str, Any],
    bars: Sequence[Bar],
    times: Sequence[int],
) -> list[ChartSeries]:
    """Recompute the strategy's indicator lines over ``bars``.

    Unknown strategies (archived roster entries) degrade to just the
    generic tactic overlays — the chart still renders candles + trades.
    """
    builder = _STRATEGY_SERIES_BUILDERS.get(strategy_name)
    series: list[ChartSeries] = []
    if builder is not None:
        series.extend(builder(params, bars, times))
    series.extend(_trail_series(params, bars, times))
    series.extend(_adx_gate_series(params, bars, times))
    return series


# --- Top-level payload --------------------------------------------------


def build_chart_payload(
    *,
    df: pd.DataFrame,
    bars: Sequence[Bar],
    result: BacktestResult,
    strategy_name: str,
    params: Mapping[str, Any],
    symbol: str,
    timeframe: str,
    window_label: str,
    display_label: str | None = None,
) -> dict[str, Any]:
    """Assemble the full JSON payload for the HTML template.

    ``df`` and ``bars`` must describe the same slice of market data the
    backtest consumed (same rows, same order) — indicator series are
    aligned to candles positionally via the shared timestamp column.
    """
    if len(df) != len(bars):
        raise ValueError(
            f"df has {len(df)} rows but bars has {len(bars)} — candles and "
            "indicator series would misalign"
        )
    candles = candles_from_dataframe(df)
    times = [c["time"] for c in candles]
    indicator_series = compute_indicator_series(
        strategy_name, params, bars, times
    )
    trades = trades_to_payload(result.trades)
    pnl = float(result.final_balance - result.initial_balance)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return {
        "meta": {
            "strategy": display_label or strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "window": window_label,
            "start": result.start.isoformat(),
            "end": result.end.isoformat(),
            "params": dict(params),
            "initialBalance": float(result.initial_balance),
            "finalBalance": float(result.final_balance),
            "pnl": pnl,
            "tradeCount": len(trades),
            "winRate": (wins / len(trades)) if trades else None,
        },
        "candles": candles,
        "trades": trades,
        "indicators": [s.to_json_dict() for s in indicator_series],
    }
