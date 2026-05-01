"""EngineConfig — DI container stub for the trading engine.

Story 10.1 introduces the dataclass with the same nine optional deps the
god-object `TradingEngine.__init__` accepted today. Story 10.2 will tighten
fields, add validation, and become the single source of truth for engine
construction.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..accounts.account_manager import AccountManager
from ..accounts.pnl_registry import PnLTrackerRegistry
from ..accounts.risk_registry import RiskStateRegistry
from ..adapters.zmq_adapter import ZmqAdapter
from ..audit.audit_service import AuditService
from ..config.firm_registry import FirmRegistry
from ..state.redis_state import RedisStateManager
from ..state.snapshot_service import SnapshotService


@dataclass(frozen=True)
class EngineConfig:
    """Aggregates the dependencies needed to build a trading engine.

    All fields are optional so the existing surface — engine spun up with
    just a Redis manager, or with no deps at all in unit tests — keeps
    working until story 10.2 introduces required fields.
    """

    redis_manager: RedisStateManager | None = None
    zmq_adapter: ZmqAdapter | None = None
    db_session_factory: async_sessionmaker[AsyncSession] | None = None
    risk_registry: RiskStateRegistry | None = None
    pnl_registry: PnLTrackerRegistry | None = None
    account_manager: AccountManager | None = None
    snapshot_service: SnapshotService | None = None
    database_url: str | None = None
    audit_service: AuditService | None = None
    firm_registry: FirmRegistry | None = None
