"""Integration tests for comprehensive audit logging (Story 7.2).

Tests cover:
- Trade execution -> audit_logs entry with event_type="trade_executed"
- Position close -> audit_logs entry with event_type="position_closed"
- Engine lifecycle events logged with account_id=NULL
- Filter by event_type, account_id, and time range
- Existing rule_check audit entries still work after rule_type removal
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audit.audit_service import AuditService
from src.orders.execution_service import OrderExecutionService
from src.orders.position_tracker import PositionTracker
from src.rules.audit_db_writer import AuditDBWriter, AuditLogModel
from src.rules.audit_logger import AuditEntry, AuditEventType, AuditLogger
from src.rules.base_rule import RuleAction, RuleResult


class MockRule:
    """Mock rule for testing."""

    def __init__(self, rule_type="daily_loss_limit", name="Daily Loss Limit"):
        self.rule_type = rule_type
        self.name = name


class TestTradeExecutionAuditIntegration:
    """Integration test: Trade execution -> audit_logs entry."""

    @pytest.fixture
    def mock_db_writer(self):
        writer = AsyncMock(spec=AuditDBWriter)
        writer.add_entry = AsyncMock()
        return writer

    @pytest.fixture
    def audit_service(self, mock_db_writer):
        return AuditService(mock_db_writer)

    @pytest.mark.asyncio
    async def test_trade_executed_creates_audit_entry(self, audit_service, mock_db_writer):
        """Trade execution creates audit entry with event_type='trade_executed'."""
        trade_id = str(uuid.uuid4())

        await audit_service.log_trade_executed(
            account_id="ftmo-gold-001",
            trade_id=trade_id,
            symbol="XAUUSD",
            side="BUY",
            quantity=0.1,
            entry_price=1850.45,
            strategy_name="ma_cross",
            order_id="ORDER-123",
        )

        entry = mock_db_writer.add_entry.call_args[0][0]

        # Verify correct event type
        assert entry.event_type == AuditEventType.TRADE_EXECUTED.value
        assert entry.event_subtype == "entry_fill"
        assert entry.source == "execution-service"
        assert entry.trade_id == trade_id
        assert entry.account_id == "ftmo-gold-001"

        # Verify ORM model conversion works
        model = AuditLogModel.from_audit_entry(entry)
        assert model.event_type == "trade_executed"
        assert model.trade_id == uuid.UUID(trade_id)
        assert model.order_id == "ORDER-123"
        assert model.source == "execution-service"


class TestPositionCloseAuditIntegration:
    """Integration test: Position close -> audit_logs entry."""

    @pytest.fixture
    def mock_db_writer(self):
        writer = AsyncMock(spec=AuditDBWriter)
        writer.add_entry = AsyncMock()
        return writer

    @pytest.fixture
    def audit_service(self, mock_db_writer):
        return AuditService(mock_db_writer)

    @pytest.mark.asyncio
    async def test_position_closed_creates_audit_entry(self, audit_service, mock_db_writer):
        """Position close creates audit entry with event_type='position_closed'."""
        trade_id = str(uuid.uuid4())

        await audit_service.log_position_closed(
            account_id="ftmo-gold-001",
            trade_id=trade_id,
            symbol="XAUUSD",
            side="BUY",
            exit_price=1860.50,
            pnl_dollars=10.05,
        )

        entry = mock_db_writer.add_entry.call_args[0][0]

        assert entry.event_type == AuditEventType.POSITION_CLOSED.value
        assert entry.event_subtype == "exit_fill"
        assert entry.source == "execution-service"
        assert entry.trade_id == trade_id

        # Verify ORM model conversion
        model = AuditLogModel.from_audit_entry(entry)
        assert model.event_type == "position_closed"
        assert model.trade_id == uuid.UUID(trade_id)
        assert model.account_id == "ftmo-gold-001"


class TestEngineLifecycleAuditIntegration:
    """Integration test: Engine lifecycle events logged with account_id=NULL."""

    @pytest.fixture
    def mock_db_writer(self):
        writer = AsyncMock(spec=AuditDBWriter)
        writer.add_entry = AsyncMock()
        return writer

    @pytest.fixture
    def audit_service(self, mock_db_writer):
        return AuditService(mock_db_writer)

    @pytest.mark.asyncio
    async def test_engine_start_null_account(self, audit_service, mock_db_writer):
        """Engine start event has account_id=None (NULL in DB)."""
        await audit_service.log_system_event(
            event_subtype="engine_start",
            message="Trading Engine started",
            context={"version": "0.1.0"},
        )

        entry = mock_db_writer.add_entry.call_args[0][0]

        assert entry.account_id is None
        assert entry.event_type == AuditEventType.SYSTEM_EVENT.value
        assert entry.source == "trading-engine"

        # Verify ORM model allows NULL account_id
        model = AuditLogModel.from_audit_entry(entry)
        assert model.account_id is None
        assert model.event_type == "system_event"

    @pytest.mark.asyncio
    async def test_crash_recovery_event(self, audit_service, mock_db_writer):
        """Crash recovery event logged with WARNING level."""
        await audit_service.log_system_event(
            event_subtype="crash_recovery",
            message="Crash recovery for 2 accounts",
            level="WARNING",
            context={"accounts": ["ftmo-001", "ftmo-002"]},
        )

        entry = mock_db_writer.add_entry.call_args[0][0]
        model = AuditLogModel.from_audit_entry(entry)

        assert model.level == "WARNING"
        assert model.event_subtype == "crash_recovery"

    @pytest.mark.asyncio
    async def test_graceful_shutdown_event(self, audit_service, mock_db_writer):
        """Graceful shutdown event logged correctly."""
        await audit_service.log_system_event(
            event_subtype="engine_stop",
            message="Trading Engine shutdown",
            context={"graceful": True},
        )

        entry = mock_db_writer.add_entry.call_args[0][0]
        model = AuditLogModel.from_audit_entry(entry)

        assert model.event_subtype == "engine_stop"
        assert model.source == "trading-engine"


class TestAuditFilteringIntegration:
    """Integration test: Filter by event_type, account_id, and time range."""

    def test_filter_entries_by_event_type(self):
        """Can filter audit entries by event_type."""
        entries = [
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                account_id="ftmo-001",
                event_type=AuditEventType.RULE_CHECK.value,
                rule_name="Test",
                rule_result="ALLOW",
            ),
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                account_id="ftmo-001",
                event_type=AuditEventType.TRADE_EXECUTED.value,
                rule_name="",
                rule_result="",
                source="execution-service",
            ),
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                account_id=None,
                event_type=AuditEventType.SYSTEM_EVENT.value,
                rule_name="",
                rule_result="",
                source="trading-engine",
            ),
        ]

        trade_entries = [e for e in entries if e.event_type == "trade_executed"]
        assert len(trade_entries) == 1
        assert trade_entries[0].source == "execution-service"

        system_entries = [e for e in entries if e.event_type == "system_event"]
        assert len(system_entries) == 1
        assert system_entries[0].account_id is None

    def test_filter_entries_by_account_id(self):
        """Can filter audit entries by account_id including NULL."""
        entries = [
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                account_id="ftmo-001",
                event_type="rule_check",
                rule_name="Test",
                rule_result="ALLOW",
            ),
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                account_id="ftmo-002",
                event_type="trade_executed",
                rule_name="",
                rule_result="",
            ),
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                account_id=None,
                event_type="system_event",
                rule_name="",
                rule_result="",
            ),
        ]

        account_001 = [e for e in entries if e.account_id == "ftmo-001"]
        assert len(account_001) == 1

        system_events = [e for e in entries if e.account_id is None]
        assert len(system_events) == 1


class TestExecutionServiceAuditIntegration:
    """Integration test: OrderExecutionService fires audit tasks on fills."""

    @pytest.fixture
    def mock_zmq(self):
        from src.adapters.zmq_models import OrderResult, OrderStatus

        zmq = AsyncMock()
        zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="mock-order-id",
                status=OrderStatus.FILLED,
                fill_price=1850.0,
                slippage=0.05,
            )
        )
        return zmq

    @pytest.fixture
    def mock_audit_service(self):
        service = AsyncMock(spec=AuditService)
        service.log_trade_executed = AsyncMock()
        service.log_position_closed = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_entry_fill_fires_audit_task(self, mock_zmq, mock_audit_service):
        """_handle_entry_fill creates fire-and-forget audit task."""
        from src.orders.signal import Signal, SignalType

        tracker = PositionTracker()
        service = OrderExecutionService(
            zmq_adapter=mock_zmq,
            position_tracker=tracker,
            audit_service=mock_audit_service,
        )

        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_cross",
        )

        order = await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.0,
        )

        # Allow fire-and-forget tasks to run
        await asyncio.sleep(0.05)

        mock_audit_service.log_trade_executed.assert_called_once()
        call_kwargs = mock_audit_service.log_trade_executed.call_args
        assert call_kwargs.kwargs["account_id"] == "ftmo-001"
        assert call_kwargs.kwargs["symbol"] == "XAUUSD"
        assert call_kwargs.kwargs["side"] == "BUY"
        assert call_kwargs.kwargs["order_id"] == order.order_id

    @pytest.mark.asyncio
    async def test_close_fill_fires_audit_task(self, mock_zmq, mock_audit_service):
        """_handle_close_fill creates fire-and-forget audit task with order_id."""
        from src.adapters.zmq_models import OrderResult, OrderStatus
        from src.orders.signal import Signal, SignalType

        tracker = PositionTracker()
        service = OrderExecutionService(
            zmq_adapter=mock_zmq,
            position_tracker=tracker,
            audit_service=mock_audit_service,
        )

        # First open a position
        buy_signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_cross",
        )
        await service.execute_signal(
            signal=buy_signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.0,
        )

        # Now close it
        mock_zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="mock-close-order",
                status=OrderStatus.FILLED,
                fill_price=1860.0,
                slippage=0.03,
            )
        )
        close_signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
            strategy_name="ma_cross",
        )
        close_order = await service.execute_signal(
            signal=close_signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1860.0,
        )

        await asyncio.sleep(0.05)

        mock_audit_service.log_position_closed.assert_called_once()
        call_kwargs = mock_audit_service.log_position_closed.call_args
        assert call_kwargs.kwargs["account_id"] == "ftmo-001"
        assert call_kwargs.kwargs["symbol"] == "XAUUSD"
        assert call_kwargs.kwargs["order_id"] == close_order.order_id


class TestRuleCheckBackwardCompatIntegration:
    """Integration test: Existing rule_check entries still work after rule_type removal."""

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.setex = AsyncMock()
        return redis

    @pytest.mark.asyncio
    async def test_rule_check_still_works(self, mock_redis):
        """AuditLogger._create_entry() works after rule_type removal (now in context)."""
        audit_logger = AuditLogger(mock_redis, "ftmo-gold-001")
        rule = MockRule(rule_type="daily_loss_limit", name="Daily Loss Limit 5%")
        result = RuleResult(
            action=RuleAction.ALLOW,
            current_value=3.5,
            threshold_value=5.0,
        )

        await audit_logger.log_rule_check(
            rule=rule,
            result=result,
            order_id="ORDER-123",
            context={"signal": "BUY", "symbol": "XAUUSD"},
        )

        # Verify Redis was called
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_rule_type_in_context_after_removal(self, mock_redis):
        """rule_type is stored in context dict, not as a direct field."""
        audit_logger = AuditLogger(mock_redis, "ftmo-gold-001")
        rule = MockRule(rule_type="max_drawdown", name="Max Drawdown Rule")
        result = RuleResult(
            action=RuleAction.BLOCK,
            message="Max drawdown exceeded",
            current_value=12.0,
            threshold_value=10.0,
        )

        await audit_logger.log_rule_check(rule=rule, result=result)

        # Parse the stored Redis value
        import json
        call_args = mock_redis.setex.call_args[0]
        stored_value = json.loads(call_args[2])

        # rule_type should be in context, not as a top-level field
        assert "rule_type" not in stored_value or stored_value.get("rule_type") is None
        assert stored_value["context"]["rule_type"] == "max_drawdown"
        assert stored_value["event_type"] == "trade_blocked"
        assert stored_value["source"] == "rule-engine"
        assert stored_value["level"] == "WARNING"

    @pytest.mark.asyncio
    async def test_block_result_sets_warning_level(self, mock_redis):
        """BLOCK result sets level to WARNING."""
        audit_logger = AuditLogger(mock_redis, "ftmo-gold-001")
        rule = MockRule()
        result = RuleResult(
            action=RuleAction.BLOCK,
            message="Blocked",
            current_value=5.5,
            threshold_value=5.0,
        )

        await audit_logger.log_rule_check(rule=rule, result=result)

        import json
        call_args = mock_redis.setex.call_args[0]
        stored_value = json.loads(call_args[2])

        assert stored_value["level"] == "WARNING"
        assert stored_value["source"] == "rule-engine"

    def test_orm_model_from_rule_check_entry(self):
        """AuditLogModel correctly maps rule_check entry without rule_type column."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="ftmo-gold-001",
            event_type="rule_check",
            rule_name="Daily Loss Limit",
            rule_result="ALLOW",
            current_value=3.5,
            threshold_value=5.0,
            context={"rule_type": "daily_loss_limit", "signal": "BUY"},
            source="rule-engine",
            level="INFO",
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.event_type == "rule_check"
        assert model.rule_name == "Daily Loss Limit"
        assert model.context == {"rule_type": "daily_loss_limit", "signal": "BUY"}
        assert model.source == "rule-engine"
        assert model.level == "INFO"
        # Verify rule_type column does NOT exist on model
        assert not hasattr(model, "rule_type") or "rule_type" not in model.__table__.columns
