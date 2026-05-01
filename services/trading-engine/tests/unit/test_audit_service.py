"""Unit tests for AuditService facade.

Tests cover:
- AuditService.log_trade_executed() creates correct AuditEntry
- AuditService.log_position_closed() creates correct AuditEntry
- AuditService.log_system_event() with account_id=None
- AuditEventType new values serialize correctly
- AuditEntry backward compatibility (rule_type in context dict)
- AuditLogModel new columns mapped correctly
- from_audit_entry() maps all new fields including trade_id UUID
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.audit.audit_service import AuditService
from src.rules.audit_db_writer import AuditLogModel
from src.rules.audit_logger import AuditEntry, AuditEventType


class TestAuditEventTypeNewValues:
    """Tests for new AuditEventType enum values."""

    def test_trade_executed_value(self):
        assert AuditEventType.TRADE_EXECUTED.value == "trade_executed"

    def test_position_closed_value(self):
        assert AuditEventType.POSITION_CLOSED.value == "position_closed"

    def test_system_event_value(self):
        assert AuditEventType.SYSTEM_EVENT.value == "system_event"

    def test_existing_values_unchanged(self):
        assert AuditEventType.RULE_CHECK.value == "rule_check"
        assert AuditEventType.TRADE_BLOCKED.value == "trade_blocked"
        assert AuditEventType.WARNING_TRIGGERED.value == "warning_triggered"


class TestAuditEntryBackwardCompat:
    """Tests for AuditEntry backward compatibility after rule_type removal."""

    def test_existing_rule_check_callers_work_with_rule_type_in_context(self):
        """Existing _create_entry() callers put rule_type in context dict."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="ftmo-gold-001",
            event_type=AuditEventType.RULE_CHECK.value,
            rule_name="Daily Loss Limit 5%",
            rule_result="ALLOW",
            current_value=3.5,
            threshold_value=5.0,
            context={"rule_type": "daily_loss_limit"},
            source="rule-engine",
        )

        assert entry.context["rule_type"] == "daily_loss_limit"
        assert entry.source == "rule-engine"
        assert entry.level == "INFO"

    def test_new_fields_have_defaults(self):
        """All new fields have defaults so existing callers work unchanged."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="ftmo-gold-001",
            event_type="rule_check",
            rule_name="Test",
            rule_result="ALLOW",
        )

        assert entry.event_subtype is None
        assert entry.source == "rule-engine"
        assert entry.level == "INFO"
        assert entry.message is None
        assert entry.trade_id is None

    def test_account_id_none_for_system_events(self):
        """System events can have account_id=None."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=None,
            event_type=AuditEventType.SYSTEM_EVENT.value,
            rule_name="",
            rule_result="",
            source="trading-engine",
        )

        assert entry.account_id is None

    def test_to_dict_includes_new_fields(self):
        """to_dict() includes all new fields."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="trade_executed",
            rule_name="",
            rule_result="",
            event_subtype="entry_fill",
            source="execution-service",
            level="INFO",
            message="Trade executed",
            trade_id=str(uuid.uuid4()),
        )

        d = entry.to_dict()
        assert "event_subtype" in d
        assert "source" in d
        assert "level" in d
        assert "message" in d
        assert "trade_id" in d
        assert d["event_subtype"] == "entry_fill"
        assert d["source"] == "execution-service"

    def test_from_dict_handles_new_fields(self):
        """from_dict() correctly deserializes new fields."""
        trade_id = str(uuid.uuid4())
        data = {
            "timestamp": "2025-12-03T14:32:15+00:00",
            "account_id": "test",
            "event_type": "system_event",
            "rule_name": "",
            "rule_result": "",
            "event_subtype": "engine_start",
            "source": "trading-engine",
            "level": "INFO",
            "message": "Engine started",
            "trade_id": trade_id,
        }

        entry = AuditEntry.from_dict(data)

        assert entry.event_subtype == "engine_start"
        assert entry.source == "trading-engine"
        assert entry.level == "INFO"
        assert entry.message == "Engine started"
        assert entry.trade_id == trade_id

    def test_from_dict_defaults_for_missing_new_fields(self):
        """from_dict() uses defaults when new fields are missing (backward compat)."""
        data = {
            "timestamp": "2025-12-03T14:32:15+00:00",
            "account_id": "test",
            "event_type": "rule_check",
            "rule_name": "Test",
            "rule_result": "ALLOW",
        }

        entry = AuditEntry.from_dict(data)

        assert entry.event_subtype is None
        assert entry.source == "rule-engine"
        assert entry.level == "INFO"
        assert entry.message is None
        assert entry.trade_id is None

    def test_to_redis_key_with_none_account(self):
        """to_redis_key() handles None account_id for system events."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=None,
            event_type="system_event",
            rule_name="",
            rule_result="",
        )

        key = entry.to_redis_key()
        assert key.startswith("audit:system:")


class TestAuditLogModelNewColumns:
    """Tests for extended AuditLogModel."""

    def test_from_audit_entry_maps_all_new_fields(self):
        """from_audit_entry() correctly maps all 5 new fields."""
        trade_id = str(uuid.uuid4())
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="ftmo-gold-001",
            event_type="trade_executed",
            rule_name="",
            rule_result="",
            event_subtype="entry_fill",
            source="execution-service",
            level="INFO",
            message="Trade executed: BUY 0.1 XAUUSD @ 1850.0",
            trade_id=trade_id,
            order_id="ORDER-123",
            current_value=1850.0,
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.event_subtype == "entry_fill"
        assert model.source == "execution-service"
        assert model.level == "INFO"
        assert model.message == "Trade executed: BUY 0.1 XAUUSD @ 1850.0"
        assert model.trade_id == uuid.UUID(trade_id)
        assert model.order_id == "ORDER-123"
        assert model.current_value == Decimal("1850.0")

    def test_from_audit_entry_account_id_nullable(self):
        """account_id can be None for system events."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=None,
            event_type="system_event",
            rule_name="",
            rule_result="",
            source="trading-engine",
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.account_id is None

    def test_from_audit_entry_trade_id_none(self):
        """trade_id is None when not provided."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="rule_check",
            rule_name="Test",
            rule_result="ALLOW",
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.trade_id is None

    def test_from_audit_entry_order_id_as_string(self):
        """order_id stored as String, not UUID."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="rule_check",
            rule_name="Test",
            rule_result="ALLOW",
            order_id="ORDER-ABC-123",
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.order_id == "ORDER-ABC-123"

    def test_from_audit_entry_empty_rule_fields_become_none(self):
        """Empty string rule_name/rule_result become None in model."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="trade_executed",
            rule_name="",
            rule_result="",
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.rule_name is None
        assert model.rule_result is None


class TestAuditServiceLogTradeExecuted:
    """Tests for AuditService.log_trade_executed()."""

    @pytest.fixture
    def mock_db_writer(self):
        writer = AsyncMock()
        writer.log_async = AsyncMock()
        writer.log_sync = AsyncMock()
        return writer

    @pytest.fixture
    def audit_service(self, mock_db_writer):
        return AuditService(mock_db_writer)

    @pytest.mark.asyncio
    async def test_creates_correct_entry(self, audit_service, mock_db_writer):
        """log_trade_executed() creates AuditEntry with correct fields."""
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

        mock_db_writer.log_async.assert_called_once()
        entry = mock_db_writer.log_async.call_args[0][0]

        assert entry.account_id == "ftmo-gold-001"
        assert entry.event_type == "trade_executed"
        assert entry.event_subtype == "entry_fill"
        assert entry.source == "execution-service"
        assert entry.level == "INFO"
        assert entry.trade_id == trade_id
        assert entry.order_id == "ORDER-123"
        assert "BUY" in entry.message
        assert "XAUUSD" in entry.message
        assert entry.current_value == 1850.45

    @pytest.mark.asyncio
    async def test_default_context(self, audit_service, mock_db_writer):
        """Default context includes trade details."""
        await audit_service.log_trade_executed(
            account_id="test",
            trade_id=str(uuid.uuid4()),
            symbol="EURUSD",
            side="SELL",
            quantity=0.5,
            entry_price=1.0850,
            strategy_name="rsi_bounce",
        )

        entry = mock_db_writer.log_async.call_args[0][0]
        assert entry.context["symbol"] == "EURUSD"
        assert entry.context["side"] == "SELL"
        assert entry.context["quantity"] == 0.5
        assert entry.context["strategy"] == "rsi_bounce"

    @pytest.mark.asyncio
    async def test_custom_context(self, audit_service, mock_db_writer):
        """Custom context overrides default."""
        custom = {"custom_key": "custom_value"}

        await audit_service.log_trade_executed(
            account_id="test",
            trade_id=str(uuid.uuid4()),
            symbol="EURUSD",
            side="BUY",
            quantity=0.1,
            entry_price=1.0850,
            strategy_name="test",
            context=custom,
        )

        entry = mock_db_writer.log_async.call_args[0][0]
        assert entry.context == custom


class TestAuditServiceLogPositionClosed:
    """Tests for AuditService.log_position_closed()."""

    @pytest.fixture
    def mock_db_writer(self):
        writer = AsyncMock()
        writer.log_async = AsyncMock()
        writer.log_sync = AsyncMock()
        return writer

    @pytest.fixture
    def audit_service(self, mock_db_writer):
        return AuditService(mock_db_writer)

    @pytest.mark.asyncio
    async def test_creates_correct_entry(self, audit_service, mock_db_writer):
        """log_position_closed() creates AuditEntry with correct fields."""
        trade_id = str(uuid.uuid4())

        await audit_service.log_position_closed(
            account_id="ftmo-gold-001",
            trade_id=trade_id,
            symbol="XAUUSD",
            side="BUY",
            exit_price=1860.50,
            pnl_dollars=10.05,
        )

        mock_db_writer.log_async.assert_called_once()
        entry = mock_db_writer.log_async.call_args[0][0]

        assert entry.account_id == "ftmo-gold-001"
        assert entry.event_type == "position_closed"
        assert entry.event_subtype == "exit_fill"
        assert entry.source == "execution-service"
        assert entry.level == "INFO"
        assert entry.trade_id == trade_id
        assert entry.current_value == 1860.50
        assert "XAUUSD" in entry.message

    @pytest.mark.asyncio
    async def test_negative_pnl_warning_level(self, audit_service, mock_db_writer):
        """Negative PnL sets level to WARNING."""
        await audit_service.log_position_closed(
            account_id="test",
            trade_id=str(uuid.uuid4()),
            symbol="XAUUSD",
            side="BUY",
            exit_price=1840.0,
            pnl_dollars=-10.50,
        )

        entry = mock_db_writer.log_async.call_args[0][0]
        assert entry.level == "WARNING"

    @pytest.mark.asyncio
    async def test_positive_pnl_info_level(self, audit_service, mock_db_writer):
        """Positive PnL keeps level at INFO."""
        await audit_service.log_position_closed(
            account_id="test",
            trade_id=str(uuid.uuid4()),
            symbol="XAUUSD",
            side="BUY",
            exit_price=1860.0,
            pnl_dollars=10.0,
        )

        entry = mock_db_writer.log_async.call_args[0][0]
        assert entry.level == "INFO"


class TestAuditServiceLogSystemEvent:
    """Tests for AuditService.log_system_event()."""

    @pytest.fixture
    def mock_db_writer(self):
        writer = AsyncMock()
        writer.log_async = AsyncMock()
        writer.log_sync = AsyncMock()
        return writer

    @pytest.fixture
    def audit_service(self, mock_db_writer):
        return AuditService(mock_db_writer)

    @pytest.mark.asyncio
    async def test_engine_start_event(self, audit_service, mock_db_writer):
        """log_system_event() for engine start with None account_id."""
        await audit_service.log_system_event(
            event_subtype="engine_start",
            message="Trading Engine started",
            context={"version": "0.1.0"},
        )

        mock_db_writer.log_async.assert_called_once()
        entry = mock_db_writer.log_async.call_args[0][0]

        assert entry.account_id is None
        assert entry.event_type == "system_event"
        assert entry.event_subtype == "engine_start"
        assert entry.source == "trading-engine"
        assert entry.level == "INFO"
        assert entry.message == "Trading Engine started"
        assert entry.context == {"version": "0.1.0"}

    @pytest.mark.asyncio
    async def test_crash_recovery_event(self, audit_service, mock_db_writer):
        """log_system_event() for crash recovery with WARNING level."""
        await audit_service.log_system_event(
            event_subtype="crash_recovery",
            message="Crash recovery initiated",
            level="WARNING",
            context={"accounts": ["ftmo-001"]},
        )

        entry = mock_db_writer.log_async.call_args[0][0]

        assert entry.level == "WARNING"
        assert entry.event_subtype == "crash_recovery"

    @pytest.mark.asyncio
    async def test_engine_stop_event(self, audit_service, mock_db_writer):
        """log_system_event() for engine stop."""
        await audit_service.log_system_event(
            event_subtype="engine_stop",
            message="Trading Engine shutdown",
            context={"graceful": True},
        )

        entry = mock_db_writer.log_async.call_args[0][0]

        assert entry.event_subtype == "engine_stop"
        assert entry.context == {"graceful": True}

    @pytest.mark.asyncio
    async def test_null_rule_fields_for_system_events(self, audit_service, mock_db_writer):
        """System events have empty rule_name and rule_result."""
        await audit_service.log_system_event(
            event_subtype="engine_start",
            message="Started",
        )

        entry = mock_db_writer.log_async.call_args[0][0]

        assert entry.rule_name == ""
        assert entry.rule_result == ""
        assert entry.trade_id is None
        assert entry.order_id is None


class TestAuditServiceStop:
    """Tests for AuditService.stop()."""

    @pytest.fixture
    def mock_db_writer(self):
        writer = AsyncMock()
        writer.stop = AsyncMock()
        return writer

    @pytest.fixture
    def audit_service(self, mock_db_writer):
        return AuditService(mock_db_writer)

    @pytest.mark.asyncio
    async def test_stop_delegates_to_db_writer(self, audit_service, mock_db_writer):
        """stop() calls db_writer.stop() to flush and shutdown."""
        await audit_service.stop()
        mock_db_writer.stop.assert_called_once()


class TestFromAuditEntryContextHandling:
    """Tests for from_audit_entry() context None vs empty dict handling."""

    def test_empty_context_preserved_as_empty_dict(self):
        """Empty dict context is preserved, not converted to None."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="system_event",
            rule_name="",
            rule_result="",
            context={},
        )

        model = AuditLogModel.from_audit_entry(entry)
        assert model.context == {}

    def test_none_context_stays_none(self):
        """None context is stored as None."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="system_event",
            rule_name="",
            rule_result="",
            context=None,
        )

        model = AuditLogModel.from_audit_entry(entry)
        assert model.context is None
