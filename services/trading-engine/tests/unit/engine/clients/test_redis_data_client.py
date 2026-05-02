"""Smoke + listener tests for :class:`RedisDataClient` (story 10.5b).

The Nautilus base ``LiveMarketDataClient`` is Cython-compiled and
needs a fully-plumbed engine to instantiate, so we exercise:

1. The listener helper :func:`run_redis_bar_listener` against a fake
   pub/sub object — covers happy-path bar delivery, malformed payload
   skipping, ignored subscribe frames, and cancellation.
2. The class subclass invariant + constructor signature so the future
   wiring in 10.5e can rely on the keyword-only surface.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any

import pytest
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import Venue

from src.adapters.redis_models import Bar as InternalBar
from src.engine.clients.redis_data_client import (
    RedisDataClient,
    run_redis_bar_listener,
)


VENUE = Venue("MT5")


def _bar_message(*, symbol: str, timeframe: str, close: float = 1850.0) -> dict[str, Any]:
    bar = InternalBar(
        symbol=symbol,
        timeframe=timeframe,
        time=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
        open=close - 0.5,
        high=close + 0.5,
        low=close - 1.0,
        close=close,
        volume=100.0,
    )
    return {
        "type": "message",
        "channel": f"bars:{symbol}:{timeframe}",
        "data": bar.to_json(),
    }


class _FakePubSub:
    """Minimal asyncio pubsub double for the listener tests."""

    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for msg in messages or []:
            self._queue.put_nowait(msg)
        self.subscribed: tuple[str, ...] | None = None

    async def subscribe(self, *channels: str) -> None:
        self.subscribed = channels

    async def listen(self):
        while True:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                # Mimic real PubSub: a long-lived listener — sleep until cancelled.
                await asyncio.sleep(0.5)
                continue
            yield msg

    def push(self, msg: dict[str, Any]) -> None:
        self._queue.put_nowait(msg)


# -------------------------------------------------------------------------
# run_redis_bar_listener — happy path
# -------------------------------------------------------------------------


class TestListenerHappyPath:
    @pytest.mark.asyncio
    async def test_message_invokes_on_bar(self) -> None:
        msg = _bar_message(symbol="XAUUSD", timeframe="1m", close=1850.45)
        pubsub = _FakePubSub(messages=[msg])

        received = []

        def _on_bar(bar) -> None:
            received.append(bar)

        task = asyncio.create_task(
            run_redis_bar_listener(
                pubsub=pubsub,
                subscriptions=[("XAUUSD", "1m")],
                venue=VENUE,
                on_bar=_on_bar,
            )
        )

        # Wait for delivery
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.01)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(received) == 1
        bar = received[0]
        assert float(bar.close) == 1850.45
        assert "XAUUSD.MT5" in str(bar.bar_type)

    @pytest.mark.asyncio
    async def test_async_on_bar_callback_awaited(self) -> None:
        pubsub = _FakePubSub(messages=[
            _bar_message(symbol="XAUUSD", timeframe="1m"),
        ])

        received = []

        async def _on_bar(bar) -> None:
            await asyncio.sleep(0)
            received.append(bar)

        task = asyncio.create_task(
            run_redis_bar_listener(
                pubsub=pubsub,
                subscriptions=[("XAUUSD", "1m")],
                venue=VENUE,
                on_bar=_on_bar,
            )
        )
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(received) == 1


class TestListenerFiltering:
    @pytest.mark.asyncio
    async def test_unsolicited_channel_is_dropped(self) -> None:
        pubsub = _FakePubSub(messages=[
            {
                "type": "message",
                "channel": "bars:BTCUSD:1m",  # not subscribed
                "data": _bar_message(symbol="BTCUSD", timeframe="1m")["data"],
            },
        ])

        received = []

        task = asyncio.create_task(
            run_redis_bar_listener(
                pubsub=pubsub,
                subscriptions=[("XAUUSD", "1m")],
                venue=VENUE,
                on_bar=received.append,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert received == []

    @pytest.mark.asyncio
    async def test_subscribe_frame_is_skipped(self) -> None:
        pubsub = _FakePubSub(messages=[
            {"type": "subscribe", "channel": "bars:XAUUSD:1m", "data": 1},
            _bar_message(symbol="XAUUSD", timeframe="1m"),
        ])
        received = []
        task = asyncio.create_task(
            run_redis_bar_listener(
                pubsub=pubsub,
                subscriptions=[("XAUUSD", "1m")],
                venue=VENUE,
                on_bar=received.append,
            )
        )
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(received) == 1


class TestListenerErrorHandling:
    @pytest.mark.asyncio
    async def test_malformed_json_is_skipped_then_continues(self) -> None:
        pubsub = _FakePubSub(messages=[
            {
                "type": "message",
                "channel": "bars:XAUUSD:1m",
                "data": b"{not json",
            },
            _bar_message(symbol="XAUUSD", timeframe="1m"),
        ])
        received = []
        task = asyncio.create_task(
            run_redis_bar_listener(
                pubsub=pubsub,
                subscriptions=[("XAUUSD", "1m")],
                venue=VENUE,
                on_bar=received.append,
            )
        )
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(received) == 1  # only the valid message

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_kill_listener(self) -> None:
        pubsub = _FakePubSub(messages=[
            _bar_message(symbol="XAUUSD", timeframe="1m", close=1850.0),
            _bar_message(symbol="XAUUSD", timeframe="1m", close=1851.0),
        ])

        received_close: list[float] = []

        def _on_bar(bar) -> None:
            close = float(bar.close)
            if close == 1850.0:
                raise RuntimeError("handler boom")
            received_close.append(close)

        task = asyncio.create_task(
            run_redis_bar_listener(
                pubsub=pubsub,
                subscriptions=[("XAUUSD", "1m")],
                venue=VENUE,
                on_bar=_on_bar,
            )
        )
        for _ in range(50):
            if received_close:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert received_close == [1851.0]


# -------------------------------------------------------------------------
# RedisDataClient — class-level invariants
# -------------------------------------------------------------------------


class TestClassInvariants:
    def test_subclasses_live_market_data_client(self) -> None:
        assert issubclass(RedisDataClient, LiveMarketDataClient)

    def test_constructor_keyword_only_required_params(self) -> None:
        sig = inspect.signature(RedisDataClient.__init__)
        params = sig.parameters
        required = {
            "loop",
            "client_id",
            "venue",
            "instrument_provider",
            "msgbus",
            "cache",
            "clock",
            "redis_client",
            "account_id",
            "bar_subscriptions",
        }
        assert required <= set(params)
        for name in required:
            assert (
                params[name].kind is inspect.Parameter.KEYWORD_ONLY
            ), f"{name} must be keyword-only"

    def test_default_price_type_is_last(self) -> None:
        sig = inspect.signature(RedisDataClient.__init__)
        assert sig.parameters["price_type"].default is PriceType.LAST


class TestEmptySubscriptions:
    """A client with no subscriptions should connect cleanly without
    touching Redis — useful for accounts without an active strategy."""

    @pytest.mark.asyncio
    async def test_connect_with_empty_subscriptions_is_noop(
        self, monkeypatch
    ) -> None:
        # Build an instance bypassing the heavy Cython base init.
        instance = RedisDataClient.__new__(RedisDataClient)
        instance._account_id = "acct-empty"  # type: ignore[attr-defined]
        instance._redis = object()  # type: ignore[attr-defined]
        instance._bar_subscriptions = []  # type: ignore[attr-defined]
        instance._pubsub = None  # type: ignore[attr-defined]
        instance._listener_task = None  # type: ignore[attr-defined]

        await instance._connect()

        assert instance._pubsub is None  # type: ignore[attr-defined]
        assert instance._listener_task is None  # type: ignore[attr-defined]
