"""Nautilus :class:`LiveMarketDataClient` reading bars from Redis Pub/Sub.

Story 10.5b — strategies running on a per-account ``LiveNode`` get
their bar feed from this client. Each instance subscribes to one
account's filtered set of ``bars:{symbol}:{timeframe}`` channels (the
shape produced by ``tv-api``) and emits parsed bars into the engine's
data path.

The listener loop is split off as
:func:`run_redis_bar_listener` so it can be exercised against a fake
Redis pub/sub object without instantiating Nautilus's Cython base.

10.5e will:

- mount this client onto the per-account ``LiveNode`` built by
  :class:`~src.engine.live_orchestrator.LiveOrchestrator`,
- update the ``last_bar_received_at`` health field per account.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Awaitable, Callable

from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import ClientId, Venue

from ...adapters.redis_models import Bar as InternalBar
from .bar_translator import make_bar_type, to_nautilus_bar

if TYPE_CHECKING:
    from nautilus_trader.cache.cache import Cache
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.common.config import NautilusConfig
    from nautilus_trader.common.providers import InstrumentProvider
    from nautilus_trader.model.data import Bar as NautilusBar
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


BarSubscription = tuple[str, str]
"""``(symbol, timeframe)`` pair — e.g. ``("XAUUSD", "1m")``."""


BarHandler = Callable[["NautilusBar"], None] | Callable[["NautilusBar"], Awaitable[None]]


async def run_redis_bar_listener(
    *,
    pubsub: object,
    subscriptions: list[BarSubscription],
    venue: Venue,
    on_bar: BarHandler,
    price_precision: int = 5,
    size_precision: int = 2,
    price_type: PriceType = PriceType.LAST,
) -> None:
    """Drain ``bars:{symbol}:{tf}`` messages until the task is cancelled.

    Pure-async helper extracted from :class:`RedisDataClient` so it can
    be unit-tested with a fake pubsub. Production usage runs this as a
    background task off ``LiveMarketDataClient.create_task``.

    Args:
        pubsub: A subscribed pubsub object exposing
            ``async listen()`` (yielding messages with ``type`` /
            ``channel`` / ``data`` keys, mirroring
            ``redis.asyncio.client.PubSub``).
        subscriptions: ``(symbol, timeframe)`` pairs already passed
            into :meth:`pubsub.subscribe`. Used to pre-build
            :class:`BarType` once per channel rather than on every
            message.
        venue: Venue handle used in :class:`BarType`.
        on_bar: Callback for each parsed Nautilus bar. Sync or async.
        price_precision: Decimal places for OHLC prices.
        size_precision: Decimal places for volume.
        price_type: Bar price type (LAST / MID / BID / ASK).

    Notes
    -----
    Malformed messages are logged and skipped. Cancellation of the
    surrounding task propagates cleanly — pubsub teardown is the
    caller's responsibility.
    """
    bar_types = {
        f"bars:{symbol}:{tf}": make_bar_type(
            symbol, tf, venue, price_type=price_type
        )
        for symbol, tf in subscriptions
    }

    try:
        async for message in pubsub.listen():
            mtype = message.get("type") if isinstance(message, dict) else None
            if mtype != "message":
                # Skip non-data frames ("subscribe" / "psubscribe" / "pong")
                continue

            channel = _decode(message.get("channel"))
            payload = message.get("data")
            if not channel or payload is None:
                continue

            bar_type = bar_types.get(channel)
            if bar_type is None:
                logger.debug(
                    "RedisDataClient: ignoring unsolicited channel %s",
                    channel,
                )
                continue

            try:
                internal = InternalBar.from_json(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "RedisDataClient: malformed bar on %s: %s",
                    channel,
                    exc,
                )
                continue

            try:
                nautilus = to_nautilus_bar(
                    internal,
                    bar_type=bar_type,
                    price_precision=price_precision,
                    size_precision=size_precision,
                )
            except Exception:
                logger.exception(
                    "RedisDataClient: failed to translate bar on %s",
                    channel,
                )
                continue

            try:
                result = on_bar(nautilus)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "RedisDataClient: on_bar handler raised for %s",
                    channel,
                )
    except asyncio.CancelledError:
        raise


def _decode(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class RedisDataClient(LiveMarketDataClient):
    """Live market-data client whose feed is Redis Pub/Sub bars.

    Parameters
    ----------
    loop : asyncio.AbstractEventLoop
        Engine event loop.
    client_id : ClientId
        Nautilus client identifier.
    venue : Venue
        Venue (typically ``MT5``).
    instrument_provider : InstrumentProvider
        Nautilus instrument provider.
    msgbus : MessageBus
        Engine message bus.
    cache : Cache
        Engine cache.
    clock : LiveClock
        Engine clock.
    redis_client : redis.asyncio.Redis
        Connected async Redis client (typically reused from
        :class:`~src.state.redis_state.RedisStateManager.client` so we
        do not double-connect).
    account_id : str
        Sandboxed account this client serves.
    bar_subscriptions : list[tuple[str, str]]
        ``(symbol, timeframe)`` pairs to subscribe to. Built by the
        orchestrator from ``account.signal_filter.symbols`` and the
        firm/strategy timeframes.
    price_precision : int, default 5
        Decimal places for OHLC.
    size_precision : int, default 2
        Decimal places for volume.
    price_type : PriceType, default LAST
        Bar price type.
    config : NautilusConfig | None, optional

    Notes
    -----
    Cancel/pause subscription operations (Nautilus
    ``_unsubscribe_bars``) are deferred to 10.5e — strategies in
    Sandboxed today never unsubscribe mid-session.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        venue: Venue,
        instrument_provider: "InstrumentProvider",
        msgbus: "MessageBus",
        cache: "Cache",
        clock: "LiveClock",
        redis_client: "Redis",
        account_id: str,
        bar_subscriptions: list[BarSubscription],
        price_precision: int = 5,
        size_precision: int = 2,
        price_type: PriceType = PriceType.LAST,
        config: "NautilusConfig | None" = None,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=venue,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            config=config,
        )
        self._redis = redis_client
        self._account_id = account_id
        self._bar_subscriptions = list(bar_subscriptions)
        self._price_precision = price_precision
        self._size_precision = size_precision
        self._price_type = price_type
        self._pubsub: object | None = None
        self._listener_task: asyncio.Task | None = None

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def bar_subscriptions(self) -> list[BarSubscription]:
        return list(self._bar_subscriptions)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _connect(self) -> None:  # noqa: D401 — Nautilus contract
        if not self._bar_subscriptions:
            logger.warning(
                "RedisDataClient[%s]: no bar subscriptions — connect is a no-op",
                self._account_id,
            )
            return

        pubsub = self._redis.pubsub()
        channels = [
            f"bars:{symbol}:{tf}" for symbol, tf in self._bar_subscriptions
        ]
        await pubsub.subscribe(*channels)
        self._pubsub = pubsub

        self._listener_task = self._loop.create_task(
            run_redis_bar_listener(
                pubsub=pubsub,
                subscriptions=self._bar_subscriptions,
                venue=self.venue,
                on_bar=self._handle_data_py,
                price_precision=self._price_precision,
                size_precision=self._size_precision,
                price_type=self._price_type,
            ),
            name=f"redis_bar_listener:{self._account_id}",
        )
        logger.info(
            "RedisDataClient[%s] subscribed to %d channels",
            self._account_id,
            len(channels),
        )

    # ------------------------------------------------------------------
    # Subscription requests from strategies
    # ------------------------------------------------------------------

    async def _subscribe_bars(self, command) -> None:  # noqa: D401
        """Acknowledge ``subscribe_bars`` from a strategy.

        ``RedisDataClient`` already psubscribes its full ``bar_subscriptions``
        set at :meth:`_connect`, so this is a no-op rather than a
        per-bar-type subscribe. The override exists because the
        :class:`LiveMarketDataClient` base class's default implementation
        raises ``NotImplementedError`` — without this override, every
        strategy's ``on_start`` ``subscribe_bars`` call would crash the
        data engine before the first bar arrived.

        We log a WARNING when the requested ``bar_type`` was not in the
        ``bar_subscriptions`` we psubscribed at connect time. Without
        the warning, an orchestrator/strategy timeframe mismatch would
        silently starve the strategy — bars would be filtered out by
        :func:`run_redis_bar_listener`'s channel filter without any
        observable signal at the subscription seam.
        """
        bar_type = getattr(command, "bar_type", None)
        if bar_type is None:
            return
        symbol = str(bar_type.instrument_id.symbol)
        configured = {sym for sym, _ in self._bar_subscriptions}
        if symbol not in configured:
            logger.warning(
                "RedisDataClient[%s]: strategy subscribed to %s but its "
                "symbol is not in bar_subscriptions=%s — bars will be "
                "silently dropped",
                self._account_id,
                bar_type,
                sorted(configured),
            )
        return

    async def _unsubscribe_bars(self, command) -> None:  # noqa: D401
        """Acknowledge ``unsubscribe_bars`` from a strategy.

        Symmetric with :meth:`_subscribe_bars` — the lifetime of the
        underlying psubscribe is bound to ``_connect`` / ``_disconnect``,
        not to per-strategy subscription state.
        """
        return

    async def _disconnect(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "RedisDataClient[%s] listener task raised on shutdown",
                    self._account_id,
                )
            self._listener_task = None

        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe()
                # ``aclose`` is the canonical name (redis-py >=5.0); fall back
                # to ``close`` for older clients.
                close = getattr(
                    self._pubsub, "aclose", None
                ) or getattr(self._pubsub, "close", None)
                if close is not None:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception:
                logger.exception(
                    "RedisDataClient[%s] failed to close pubsub cleanly",
                    self._account_id,
                )
            self._pubsub = None
