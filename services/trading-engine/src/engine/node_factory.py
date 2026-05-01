"""Per-account Nautilus :class:`TradingNode` factory.

Story 10.5e2 — :class:`LiveOrchestrator` calls
:func:`build_account_trading_node` once per active account. The factory
constructs a real Nautilus :class:`TradingNode` and registers
per-account ``RedisDataClient`` + ``ZmqExecutionClient`` factories that
close over the account-specific spec (``redis_client``,
``validated_adapter``, ``account_id``, ``bar_subscriptions``).

Why per-account nodes? See the story doc — risk isolation, per-firm
venue/commission divergence, and phase-transition restart granularity.
The factory keeps every account-scoped object in one place so a session
crash cannot leak data into another account's node.

The factory accepts ``trading_node_cls`` so unit tests can pass a stub
recording calls without standing up the Cython :class:`TradingNode`
base. Production callers leave it at the default.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.live.config import (
    LiveDataClientConfig,
    LiveExecClientConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.factories import (
    LiveDataClientFactory,
    LiveExecClientFactory,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import (
    ClientId,
    InstrumentId,
    Symbol,
    TraderId,
    Venue,
)

from ..backtesting.strategy_registry import resolve_strategy
from .clients.bar_translator import make_bar_type
from .clients.redis_data_client import RedisDataClient
from .clients.zmq_execution_client import ZmqExecutionClient

if TYPE_CHECKING:
    from nautilus_trader.common.actor import Actor
    from nautilus_trader.trading.strategy import Strategy
    from redis.asyncio import Redis

    from ..accounts.models import AccountConfig
    from ..execution.validated_adapter import ValidatedZmqAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults — Sandboxed runs against MT5 only today; bar timeframe defaults
# to 1m to match :data:`live_orchestrator.DEFAULT_BAR_TIMEFRAMES`.
# ---------------------------------------------------------------------------

DEFAULT_VENUE_NAME = "MT5"
DEFAULT_BAR_TIMEFRAME = "1m"
DEFAULT_PRICE_PRECISION = 5
DEFAULT_SIZE_PRECISION = 2
DEFAULT_TRADER_ID_PREFIX = "TRADER"


@dataclass(frozen=True)
class AccountNodeSpec:
    """Per-account inputs needed to construct a :class:`TradingNode`.

    The spec is the seam between :class:`LiveOrchestrator` (which owns
    cross-account collaborators like the shared Redis client and
    :class:`ValidatedZmqAdapter`) and the factory (which owns Nautilus
    construction). Keeping it ``frozen`` makes it safe to share between
    the closure-based client factories without any aliasing concerns.

    Attributes:
        account_id: Sandboxed account identifier — also used as the
            data/exec client name on the Nautilus side.
        venue: Nautilus venue (typically ``MT5``).
        bar_subscriptions: ``(symbol, timeframe)`` pairs the data client
            subscribes to on connect.
        redis_client: Connected ``redis.asyncio.Redis`` shared with the
            engine's :class:`RedisStateManager`.
        validated_adapter: Per-account view onto the rule-checked ZMQ
            adapter (Epic 9 P0.12 + 10.4 atomic gate).
        strategy_name: Strategy registry key from ``account.strategy``.
        strategy_params: Extra kwargs merged into the strategy config.
        compliance_actor: Optional pre-built actor (10.5e1). When set,
            the factory attaches it to the trader.
    """

    account_id: str
    venue: Venue
    bar_subscriptions: tuple[tuple[str, str], ...]
    redis_client: "Redis"
    validated_adapter: "ValidatedZmqAdapter"
    strategy_name: str
    strategy_params: dict[str, Any]
    compliance_actor: "Actor | None" = None


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_account_trading_node(
    *,
    account: "AccountConfig",
    spec: AccountNodeSpec,
    trading_node_cls: type[TradingNode] = TradingNode,
) -> TradingNode:
    """Construct + build a per-account :class:`TradingNode`.

    The returned node is **already built** (``node.build()`` has been
    called) but **not yet started**. The orchestrator owns the
    ``run_async`` / ``stop_async`` lifecycle so a node start failure can
    be isolated to its session (AC8) without raising through the
    factory.

    Args:
        account: Account whose strategy + signal_filter drive the
            instrument + bar_type for the strategy config.
        spec: Per-account inputs (see :class:`AccountNodeSpec`).
        trading_node_cls: Override for unit tests — supply a stub that
            records ``add_data_client_factory`` / ``add_exec_client_factory``
            / ``build`` / ``trader.add_strategy`` / ``trader.add_actor``
            calls. Defaults to the real :class:`TradingNode`.

    Raises:
        ValueError: ``spec.bar_subscriptions`` is empty (the strategy
            cannot start without at least one subscription).
        UnknownStrategyError: ``spec.strategy_name`` is not registered.
    """
    if not spec.bar_subscriptions:
        raise ValueError(
            f"Account {spec.account_id!r}: bar_subscriptions is empty; "
            "cannot build live trading node without at least one subscription"
        )

    client_name = _client_name_for(spec.account_id)
    config = _build_trading_node_config(spec=spec, client_name=client_name)
    node = trading_node_cls(config=config)

    # Closure-based factories — each factory class encloses ``spec`` so
    # the per-account ``RedisDataClient`` / ``ZmqExecutionClient`` can be
    # constructed from inside Nautilus's static-method create() contract.
    node.add_data_client_factory(
        client_name, _make_data_client_factory(spec)
    )
    node.add_exec_client_factory(
        client_name, _make_exec_client_factory(spec)
    )

    node.build()

    primary_symbol, primary_tf = spec.bar_subscriptions[0]
    instrument_id = _build_instrument_id(primary_symbol, spec.venue)
    bar_type = _build_bar_type(primary_symbol, primary_tf, spec.venue)

    strategy = _resolve_and_build_strategy(
        account=account,
        spec=spec,
        instrument_id=instrument_id,
        bar_type=bar_type,
    )
    node.trader.add_strategy(strategy)

    if spec.compliance_actor is not None:
        node.trader.add_actor(spec.compliance_actor)

    logger.info(
        "TradingNode built for account %s (strategy=%s, subscriptions=%d)",
        spec.account_id,
        spec.strategy_name,
        len(spec.bar_subscriptions),
    )
    return node


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _client_name_for(account_id: str) -> str:
    """Stable, sanitised client name used for both data + exec clients.

    Nautilus ``ClientId`` accepts ``str`` and is stricter than the rest
    of the codebase about characters. Account IDs in Sandboxed are
    already alphanumeric + dashes/underscores (validated at config
    load), so we forward verbatim — but uppercase to match the Nautilus
    convention in stock factories.
    """
    return account_id.upper()


def _build_instrument_id(symbol: str, venue: Venue) -> InstrumentId:
    return InstrumentId(Symbol(symbol), venue)


def _build_bar_type(symbol: str, timeframe: str, venue: Venue) -> BarType:
    """Build a Nautilus :class:`BarType` from ``(symbol, timeframe)``.

    Delegates to :func:`bar_translator.make_bar_type` so the data
    client's emitted bars match the strategy's subscribed bar type.
    """
    return make_bar_type(symbol, timeframe, venue)


def _build_trading_node_config(
    *, spec: AccountNodeSpec, client_name: str
) -> TradingNodeConfig:
    """Compose a ``TradingNodeConfig`` with one data + one exec client.

    Nautilus validates ``trader_id`` against
    ``"^[a-zA-Z0-9_-]+-[0-9]+$"`` — the suffix must be a digit run.
    We append ``-001`` to the sanitised account id so every Sandboxed
    account id satisfies the pattern without mutation.
    """
    trader_id = TraderId(f"{DEFAULT_TRADER_ID_PREFIX}-{client_name}-001")
    data_clients = {client_name: LiveDataClientConfig()}
    exec_clients = {client_name: LiveExecClientConfig()}
    return TradingNodeConfig(
        trader_id=trader_id,
        data_clients=data_clients,
        exec_clients=exec_clients,
    )


def _make_data_client_factory(
    spec: AccountNodeSpec,
) -> type[LiveDataClientFactory]:
    """Build a ``LiveDataClientFactory`` subclass that closes over ``spec``.

    Nautilus calls ``factory.create(...)`` with framework-supplied args
    only — there's no slot to thread per-account state. We wrap the
    factory class definition inside this builder so the static
    ``create`` body can read ``spec`` via lexical closure. The returned
    *class* (not instance) is what ``add_data_client_factory`` expects.
    """
    bar_subscriptions = list(spec.bar_subscriptions)
    redis_client = spec.redis_client
    venue = spec.venue
    account_id = spec.account_id

    class _AccountRedisDataClientFactory(LiveDataClientFactory):
        @staticmethod
        def create(
            loop, name, config, msgbus, cache, clock,
        ):
            return RedisDataClient(
                loop=loop,
                client_id=ClientId(name),
                venue=venue,
                instrument_provider=InstrumentProvider(),
                msgbus=msgbus,
                cache=cache,
                clock=clock,
                redis_client=redis_client,
                account_id=account_id,
                bar_subscriptions=bar_subscriptions,
                price_precision=DEFAULT_PRICE_PRECISION,
                size_precision=DEFAULT_SIZE_PRECISION,
                config=config,
            )

    return _AccountRedisDataClientFactory


def _make_exec_client_factory(
    spec: AccountNodeSpec,
) -> type[LiveExecClientFactory]:
    """Build a ``LiveExecClientFactory`` subclass that closes over ``spec``.

    Same pattern as :func:`_make_data_client_factory`. The closed-over
    ``ValidatedZmqAdapter`` is shared with all callers (rule engine +
    atomic gate are global), but the ``account_id`` is per-factory so
    the gate scopes the right exposure.
    """
    validated_adapter = spec.validated_adapter
    venue = spec.venue
    account_id = spec.account_id

    class _AccountZmqExecClientFactory(LiveExecClientFactory):
        @staticmethod
        def create(
            loop, name, config, msgbus, cache, clock,
        ):
            return ZmqExecutionClient(
                loop=loop,
                client_id=ClientId(name),
                venue=venue,
                instrument_provider=InstrumentProvider(),
                msgbus=msgbus,
                cache=cache,
                clock=clock,
                account_id=account_id,
                validated_adapter=validated_adapter,
                config=config,
            )

    return _AccountZmqExecClientFactory


def _resolve_and_build_strategy(
    *,
    account: "AccountConfig",
    spec: AccountNodeSpec,
    instrument_id: InstrumentId,
    bar_type: BarType,
) -> "Strategy":
    """Resolve ``account.strategy`` and instantiate with merged params.

    Reuses the backtest registry — :func:`resolve_strategy` returns
    ``(config_cls, strategy_cls)`` so we can build a config from a flat
    dict (the same pattern walk-forward uses to inject parameter
    sweeps).

    The strategy's ``account_id`` field is stamped from
    ``spec.account_id`` so per-account routing inside the strategy
    (used by ``ValidatedZmqAdapter``) sees the correct scope.
    """
    entry = resolve_strategy(spec.strategy_name)
    config_kwargs: dict[str, Any] = {
        "instrument_id": instrument_id,
        "bar_type": bar_type,
        "account_id": spec.account_id,
        **spec.strategy_params,
    }
    config = entry.config_cls(**config_kwargs)
    return entry.strategy_cls(config=config)
