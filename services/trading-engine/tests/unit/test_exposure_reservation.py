"""Unit tests for :class:`ExposureReservation` (story 10.4).

The ``atomic_reserve.lua`` / ``atomic_release.lua`` scripts close the
validate↔send race window by serialising in-flight reservations on Redis.
These tests use a small Python ``_FakeRedis`` that re-implements the same
Lua semantics so we exercise the full reserve/release/get_reserved flow
without needing a live Redis. End-to-end testing against real Redis
belongs in ``tests/integration/``.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

import pytest

from src.execution.exposure_reservation import (
    ExposureReservation,
    ReservationResult,
)


class _FakeRedis:
    """Minimal async Redis double for the two Lua scripts under test."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._scripts: dict[str, str] = {}

    async def script_load(self, source: str) -> str:
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()
        self._scripts[digest] = source
        return digest

    async def evalsha(
        self, sha: str, numkeys: int, *args: Any
    ) -> list[Any]:
        source = self._scripts[sha]
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])
        # Match on the unique error-message marker each script uses so a
        # comment cross-reference (e.g. "companion to atomic_reserve.lua")
        # cannot route to the wrong handler.
        if "atomic_release:" in source:
            return self._release(keys, argv)
        if "atomic_reserve:" in source:
            return self._reserve(keys, argv)
        raise NotImplementedError(f"Unknown script for sha {sha}")

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                removed += 1
        return removed

    # --- Python re-impl of the Lua scripts ---------------------------------

    @staticmethod
    def _fmt(value: float) -> str:
        # Lua's default tostring for numbers uses %.14g. Mirroring that here
        # keeps the fake faithful to real Redis double-precision behaviour.
        return "{:.14g}".format(value)

    def _reserve(self, keys: list[str], argv: list[str]) -> list[Any]:
        key = keys[0]
        requested = float(argv[0])
        max_total = float(argv[1])
        # ttl ignored in the fake
        if requested < 0:
            raise ValueError("requested must be non-negative")
        current = float(self._store.get(key, "0"))
        new = current + requested
        if new > max_total:
            return [0, self._fmt(current), self._fmt(current)]
        self._store[key] = self._fmt(new)
        return [1, self._fmt(new), self._fmt(current)]

    def _release(self, keys: list[str], argv: list[str]) -> list[Any]:
        key = keys[0]
        amount = float(argv[0])
        # argv[1] is the TTL; ignored in the fake (kept faithful to Lua signature)
        if amount < 0:
            raise ValueError("amount must be non-negative")
        current = float(self._store.get(key, "0"))
        new = current - amount
        if new < 0:
            new = 0
        if new == 0:
            self._store.pop(key, None)
        else:
            self._store[key] = self._fmt(new)
        return [self._fmt(new), self._fmt(current)]


# --------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------


@pytest.fixture
async def reservation() -> ExposureReservation:
    redis = _FakeRedis()
    res = ExposureReservation(redis)
    await res.start()
    return res


class TestReserveAccepts:
    @pytest.mark.asyncio
    async def test_accept_when_under_limit(
        self, reservation: ExposureReservation
    ) -> None:
        result = await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.5"),
            max_total_lots=Decimal("2.0"),
        )
        assert result.accepted is True
        assert result.new_reserved == Decimal("0.5")
        assert result.previous_reserved == Decimal("0")

    @pytest.mark.asyncio
    async def test_accept_at_exact_limit(
        self, reservation: ExposureReservation
    ) -> None:
        result = await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("1.0"),
            max_total_lots=Decimal("1.0"),
        )
        assert result.accepted is True
        assert result.new_reserved == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_zero_request_accepted(
        self, reservation: ExposureReservation
    ) -> None:
        result = await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0"),
            max_total_lots=Decimal("1.0"),
        )
        assert result.accepted is True
        assert result.new_reserved == Decimal("0")


class TestReserveRejects:
    @pytest.mark.asyncio
    async def test_reject_when_over_limit(
        self, reservation: ExposureReservation
    ) -> None:
        result = await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("1.5"),
            max_total_lots=Decimal("1.0"),
        )
        assert result.accepted is False
        assert result.new_reserved == Decimal("0")
        assert result.previous_reserved == Decimal("0")

    @pytest.mark.asyncio
    async def test_reject_when_existing_reservation_pushes_over(
        self, reservation: ExposureReservation
    ) -> None:
        first = await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.6"),
            max_total_lots=Decimal("1.0"),
        )
        assert first.accepted is True

        second = await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.5"),
            max_total_lots=Decimal("1.0"),
        )
        assert second.accepted is False
        assert second.previous_reserved == Decimal("0.6")
        # Counter unchanged after rejection
        assert second.new_reserved == Decimal("0.6")

    @pytest.mark.asyncio
    async def test_reject_does_not_mutate_state(
        self, reservation: ExposureReservation
    ) -> None:
        await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.6"),
            max_total_lots=Decimal("1.0"),
        )
        await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.5"),
            max_total_lots=Decimal("1.0"),
        )
        assert await reservation.get_reserved("acct-1") == Decimal("0.6")


class TestRelease:
    @pytest.mark.asyncio
    async def test_release_decrements_counter(
        self, reservation: ExposureReservation
    ) -> None:
        await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.7"),
            max_total_lots=Decimal("2.0"),
        )
        await reservation.release("acct-1", Decimal("0.3"))
        assert await reservation.get_reserved("acct-1") == Decimal("0.4")

    @pytest.mark.asyncio
    async def test_release_saturates_at_zero(
        self, reservation: ExposureReservation
    ) -> None:
        await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.2"),
            max_total_lots=Decimal("2.0"),
        )
        await reservation.release("acct-1", Decimal("1.0"))  # release more than held
        assert await reservation.get_reserved("acct-1") == Decimal("0")

    @pytest.mark.asyncio
    async def test_release_when_empty_is_noop(
        self, reservation: ExposureReservation
    ) -> None:
        await reservation.release("acct-1", Decimal("0.5"))
        assert await reservation.get_reserved("acct-1") == Decimal("0")


class TestIsolation:
    """Reservations are scoped by account_id — never bleed across accounts."""

    @pytest.mark.asyncio
    async def test_per_account_counters(
        self, reservation: ExposureReservation
    ) -> None:
        await reservation.reserve(
            account_id="acct-a",
            requested_lots=Decimal("0.6"),
            max_total_lots=Decimal("1.0"),
        )
        # Account B sees its own clean counter — limit enforced independently
        result = await reservation.reserve(
            account_id="acct-b",
            requested_lots=Decimal("0.6"),
            max_total_lots=Decimal("1.0"),
        )
        assert result.accepted is True
        assert await reservation.get_reserved("acct-a") == Decimal("0.6")
        assert await reservation.get_reserved("acct-b") == Decimal("0.6")


class TestConcurrentSerialisation:
    """Two concurrent reservations must not both pass when combined > limit.

    The fake Redis serialises evalsha calls (no parallelism inside a single
    asyncio loop), which mirrors real Redis's single-threaded execution model
    for Lua scripts. Verifies the *contract*, not the engine.
    """

    @pytest.mark.asyncio
    async def test_concurrent_reservations_do_not_both_succeed(
        self, reservation: ExposureReservation
    ) -> None:
        # Two coroutines, each requesting 0.6 against a 1.0 limit. Only one
        # should be accepted; the other rejected with previous_reserved=0.6.
        results = await asyncio.gather(
            reservation.reserve(
                account_id="acct-1",
                requested_lots=Decimal("0.6"),
                max_total_lots=Decimal("1.0"),
            ),
            reservation.reserve(
                account_id="acct-1",
                requested_lots=Decimal("0.6"),
                max_total_lots=Decimal("1.0"),
            ),
        )
        accepted = [r for r in results if r.accepted]
        rejected = [r for r in results if not r.accepted]
        assert len(accepted) == 1
        assert len(rejected) == 1
        assert await reservation.get_reserved("acct-1") == Decimal("0.6")


class TestClear:
    @pytest.mark.asyncio
    async def test_clear_removes_counter(
        self, reservation: ExposureReservation
    ) -> None:
        await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.5"),
            max_total_lots=Decimal("2.0"),
        )
        await reservation.clear("acct-1")
        assert await reservation.get_reserved("acct-1") == Decimal("0")


class TestReservationResult:
    def test_dataclass_is_frozen(self) -> None:
        result = ReservationResult(
            accepted=True,
            new_reserved=Decimal("0.5"),
            previous_reserved=Decimal("0"),
        )
        with pytest.raises(FrozenInstanceError):
            result.accepted = False  # type: ignore[misc]


class TestNegativeMaxTotalShortCircuit:
    """Negative max_total_lots ⇒ inline reject without contacting Redis."""

    @pytest.mark.asyncio
    async def test_negative_max_total_returns_rejection(
        self, reservation: ExposureReservation
    ) -> None:
        # Pre-load a counter so we can assert it stays untouched
        await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.3"),
            max_total_lots=Decimal("1.0"),
        )

        result = await reservation.reserve(
            account_id="acct-1",
            requested_lots=Decimal("0.1"),
            max_total_lots=Decimal("-0.1"),
        )
        assert result.accepted is False
        assert result.new_reserved == Decimal("0.3")
        assert result.previous_reserved == Decimal("0.3")
        # Counter remained untouched
        assert await reservation.get_reserved("acct-1") == Decimal("0.3")


class TestStartIdempotent:
    @pytest.mark.asyncio
    async def test_start_twice_uses_cached_shas(self) -> None:
        redis = _FakeRedis()
        res = ExposureReservation(redis)
        await res.start()
        first_reserve = res._reserve_sha  # type: ignore[attr-defined]
        await res.start()
        assert res._reserve_sha is first_reserve  # type: ignore[attr-defined]
