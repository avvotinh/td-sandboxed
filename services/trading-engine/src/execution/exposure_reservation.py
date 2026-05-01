"""Atomic in-flight exposure reservation, backed by Redis Lua scripts.

Story 10.4 — closes the validate↔send race window (D6). When two signals
for the same account validate concurrently, both can read an identical
in-memory snapshot, both can pass the rule engine, and both can hit MT5
before either fill comes back; combined exposure can then exceed the
configured limit.

This module wraps two Lua scripts (``atomic_reserve.lua`` /
``atomic_release.lua``) so the *reservation step* runs as a single atomic
Redis operation. The contract:

- :meth:`reserve` increments a per-account counter only if the new total
  would still be <= ``max_total_lots``; otherwise rejects without
  mutating state.
- :meth:`release` decrements that counter (saturating at zero) — must be
  called from the order's terminal handler regardless of fill status, so
  the counter does not pile up.

The counter is intentionally *separate* from the persisted
``snapshot:{id}:latest`` HASH (which serves crash recovery): mixing
in-flight reservations into the snapshot would couple two different
durability models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# Default TTL on the reservation counter — long enough to span any single
# order's round-trip, short enough that a stuck reservation auto-clears.
DEFAULT_RESERVATION_TTL_SECONDS = 60 * 15  # 15 minutes


class _RedisLike(Protocol):
    """Subset of redis.asyncio.Redis we depend on."""

    async def script_load(self, source: str) -> str: ...  # noqa: D401
    async def evalsha(self, sha: str, numkeys: int, *args: Any) -> Any: ...
    async def get(self, key: str) -> str | None: ...
    async def delete(self, *keys: str) -> int: ...


@dataclass(frozen=True)
class ReservationResult:
    """Outcome of a :meth:`ExposureReservation.reserve` call.

    Attributes:
        accepted: ``True`` when the reservation succeeded; ``False`` when
            ``new total > max_total_lots`` and no state was mutated.
        new_reserved: Counter value AFTER this call. Equal to
            ``previous_reserved`` on rejection.
        previous_reserved: Counter value BEFORE this call.
    """

    accepted: bool
    new_reserved: Decimal
    previous_reserved: Decimal


class ExposureReservation:
    """Atomic per-account in-flight lots reservation via Redis Lua.

    Args:
        redis_client: An async Redis client (``redis.asyncio.Redis``-like).
        ttl_seconds: TTL applied on each accepted reservation. Defends
            against a process death between ``reserve`` and ``release``
            leaking a permanent reservation. Set to 0 to disable.

    Lifecycle:
        Call :meth:`start` once after Redis is connected to load the Lua
        scripts. Subsequent ``reserve``/``release`` calls use ``EVALSHA``.
    """

    KEY_PREFIX = "account"
    KEY_SUFFIX = "reserved_lots"

    def __init__(
        self,
        redis_client: _RedisLike,
        *,
        ttl_seconds: int = DEFAULT_RESERVATION_TTL_SECONDS,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._reserve_sha: str | None = None
        self._release_sha: str | None = None

    async def start(self) -> None:
        """Load the Lua scripts into Redis. Idempotent.

        Skipping this and calling :meth:`reserve` directly raises
        :class:`RuntimeError`; callers can therefore detect mis-wiring.
        """
        if self._reserve_sha is not None and self._release_sha is not None:
            return
        reserve_src = self._load_script("atomic_reserve.lua")
        release_src = self._load_script("atomic_release.lua")
        self._reserve_sha = await self._redis.script_load(reserve_src)
        self._release_sha = await self._redis.script_load(release_src)
        logger.info(
            "ExposureReservation Lua scripts loaded (reserve=%s, release=%s)",
            self._reserve_sha[:8],
            self._release_sha[:8],
        )

    async def reserve(
        self,
        account_id: str,
        requested_lots: Decimal,
        max_total_lots: Decimal,
    ) -> ReservationResult:
        """Atomically reserve ``requested_lots`` if the new total fits.

        Args:
            account_id: Account scope for the reservation counter.
            requested_lots: Lots about to be sent to MT5.
            max_total_lots: Cap on ``currently_reserved + requested_lots``.
                Caller computes this from the latest realized-position
                snapshot (e.g. ``firm_max_lots - already_open_lots``).

        Returns:
            :class:`ReservationResult`. On rejection no state changes.

        Note:
            The Redis Lua script casts both arguments through Lua's
            ``tonumber`` (64-bit double). Decimal precision beyond ~15
            significant digits is therefore lost on the round-trip. MT5
            lot sizes use 0.01 increments so this is not a concern in
            practice; do not pass values with more than 6 fractional
            digits if exact equality at the boundary matters.
        """
        if self._reserve_sha is None:
            raise RuntimeError(
                "ExposureReservation.start() must be called before reserve()"
            )
        if requested_lots < 0:
            raise ValueError("requested_lots must be non-negative")
        if max_total_lots < 0:
            # Account is already over its limit (realized > max). Reject the
            # request inline — no point burning a Redis round-trip when the
            # answer is deterministic. Read current counter for the result
            # so the caller still gets back accurate ``previous_reserved``.
            logger.warning(
                "ExposureReservation: account %s has max_total_lots=%s < 0 — "
                "rejecting reservation without contacting Redis",
                account_id,
                max_total_lots,
            )
            current = await self.get_reserved(account_id)
            return ReservationResult(
                accepted=False,
                new_reserved=current,
                previous_reserved=current,
            )

        key = self._key(account_id)
        result = await self._redis.evalsha(
            self._reserve_sha,
            1,
            key,
            str(requested_lots),
            str(max_total_lots),
            str(self._ttl_seconds),
        )
        accepted_flag, new_str, prev_str = result
        return ReservationResult(
            accepted=int(accepted_flag) == 1,
            new_reserved=_to_decimal(new_str),
            previous_reserved=_to_decimal(prev_str),
        )

    async def release(self, account_id: str, amount: Decimal) -> Decimal:
        """Decrement the per-account reservation by ``amount``.

        Idempotent at the floor — releasing more than is reserved
        saturates to zero rather than going negative.

        Returns:
            The counter value AFTER the release (Decimal).
        """
        if self._release_sha is None:
            raise RuntimeError(
                "ExposureReservation.start() must be called before release()"
            )
        if amount < 0:
            raise ValueError("amount must be non-negative")

        key = self._key(account_id)
        result = await self._redis.evalsha(
            self._release_sha,
            1,
            key,
            str(amount),
            str(self._ttl_seconds),
        )
        new_str, _prev = result
        return _to_decimal(new_str)

    async def get_reserved(self, account_id: str) -> Decimal:
        """Return the current reservation counter for an account."""
        raw = await self._redis.get(self._key(account_id))
        return _to_decimal(raw) if raw is not None else Decimal("0")

    async def clear(self, account_id: str) -> None:
        """Force-clear an account's reservation counter.

        Used for recovery and tests. Production code should prefer
        :meth:`release` so the counter reflects actual in-flight lots.
        """
        await self._redis.delete(self._key(account_id))

    def _key(self, account_id: str) -> str:
        return f"{self.KEY_PREFIX}:{account_id}:{self.KEY_SUFFIX}"

    @staticmethod
    def _load_script(name: str) -> str:
        return (
            resources.files("src.execution.lua_scripts")
            .joinpath(name)
            .read_text(encoding="utf-8")
        )


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return Decimal(str(value))
