"""Unit tests for AuditLogger, AuditEntry, and AuditLoggerRegistry.

Tests cover:
- AuditEntry dataclass creation and JSON serialization
- AuditEntry helper methods (to_dict, to_redis_key, from_dict)
- AuditLogger log_rule_check() method
- Redis TTL is set to 24 hours
- ALLOW, WARN, BLOCK results are logged correctly
- Context includes order details
- Non-blocking behavior (fire-and-forget)
- AuditLoggerRegistry operations
- AuditDBWriter batch buffering and flush
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rules.audit_db_writer import AuditDBWriter, AuditLogModel
from src.rules.audit_logger import (
    AUDIT_TTL_SECONDS,
    AuditEntry,
    AuditLogger,
    audit_task_done_callback,
)
from src.rules.audit_registry import AuditLoggerRegistry
from src.rules.base_rule import RuleAction, RuleResult


class MockRule:
    """Mock rule for testing."""

    def __init__(
        self,
        rule_type: str = "test_rule",
        name: str = "Test Rule",
        priority: int = 10,
    ):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority

    def validate(self, context):
        return RuleResult(action=RuleAction.ALLOW)

    def get_current_value(self, context):
        return 0.0

    def get_threshold(self):
        return 100.0

    def get_warning_thresholds(self):
        return [70.0, 80.0, 90.0]


class TestAuditEntry:
    """Tests for AuditEntry dataclass."""

    def test_create_audit_entry(self):
        """Test creating an AuditEntry with all fields."""
        timestamp = datetime.now(timezone.utc)
        entry = AuditEntry(
            timestamp=timestamp,
            account_id="ftmo-gold-001",
            event_type="rule_check",
            rule_name="Daily Loss Limit 5%",
            rule_result="ALLOW",
            current_value=3.5,
            threshold_value=5.0,
            order_id="ORDER-123",
            context={"signal": "BUY", "symbol": "XAUUSD"},
        )

        assert entry.timestamp == timestamp
        assert entry.account_id == "ftmo-gold-001"
        assert entry.event_type == "rule_check"
        assert entry.rule_name == "Daily Loss Limit 5%"
        assert entry.rule_result == "ALLOW"
        assert entry.current_value == 3.5
        assert entry.threshold_value == 5.0
        assert entry.order_id == "ORDER-123"
        assert entry.context == {"signal": "BUY", "symbol": "XAUUSD"}

    def test_audit_entry_to_dict(self):
        """Test AuditEntry.to_dict() serialization."""
        timestamp = datetime(2025, 12, 3, 14, 32, 15, tzinfo=timezone.utc)
        entry = AuditEntry(
            timestamp=timestamp,
            account_id="ftmo-gold-001",
            event_type="rule_check",
            rule_name="Daily Loss Limit 5%",
            rule_result="ALLOW",
            current_value=3.5,
            threshold_value=5.0,
            order_id="ORDER-123",
            context={"signal": "BUY", "symbol": "XAUUSD"},
        )

        result = entry.to_dict()

        assert result["timestamp"] == "2025-12-03T14:32:15+00:00"
        assert result["account_id"] == "ftmo-gold-001"
        assert result["event_type"] == "rule_check"
        assert result["rule_name"] == "Daily Loss Limit 5%"
        assert result["rule_result"] == "ALLOW"
        assert result["current_value"] == 3.5
        assert result["threshold_value"] == 5.0
        assert result["order_id"] == "ORDER-123"
        assert result["context"] == {"signal": "BUY", "symbol": "XAUUSD"}

    def test_audit_entry_to_dict_is_json_serializable(self):
        """Test that to_dict() output is JSON serializable."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="ftmo-gold-001",
            event_type="rule_check",
            rule_name="Daily Loss Limit 5%",
            rule_result="ALLOW",
            current_value=3.5,
            threshold_value=5.0,
            order_id="ORDER-123",
            context={"signal": "BUY", "symbol": "XAUUSD", "size": 0.1},
        )

        # Should not raise
        json_str = json.dumps(entry.to_dict())
        assert isinstance(json_str, str)

        # Round-trip
        parsed = json.loads(json_str)
        assert parsed["account_id"] == "ftmo-gold-001"

    def test_audit_entry_to_redis_key(self):
        """Test AuditEntry.to_redis_key() generates correct format."""
        timestamp = datetime(2025, 12, 3, 14, 32, 15, tzinfo=timezone.utc)
        entry = AuditEntry(
            timestamp=timestamp,
            account_id="ftmo-gold-001",
            event_type="rule_check",
            rule_name="Daily Loss Limit 5%",
            rule_result="ALLOW",
        )

        key = entry.to_redis_key()

        # Key format: audit:{account_id}:{iso_timestamp}:{uuid}
        assert key.startswith("audit:ftmo-gold-001:")
        assert "2025-12-03" in key
        # The key has format: audit:account:timestamp:uuid
        # Split by ":" but account for the ":" in the timestamp
        assert key.count(":") >= 3
        # Last 8 chars should be hex (UUID fragment)
        uuid_part = key.split(":")[-1]
        assert len(uuid_part) == 8
        assert all(c in "0123456789abcdef" for c in uuid_part)

    def test_audit_entry_from_dict(self):
        """Test AuditEntry.from_dict() deserialization."""
        data = {
            "timestamp": "2025-12-03T14:32:15+00:00",
            "account_id": "ftmo-gold-001",
            "event_type": "trade_blocked",
            "rule_name": "Daily Loss Limit 5%",
            "rule_result": "BLOCK",
            "current_value": 5.5,
            "threshold_value": 5.0,
            "order_id": "ORDER-123",
            "context": {"blocking_reason": "Daily loss exceeded"},
        }

        entry = AuditEntry.from_dict(data)

        assert entry.account_id == "ftmo-gold-001"
        assert entry.event_type == "trade_blocked"
        assert entry.rule_result == "BLOCK"
        assert entry.current_value == 5.5
        assert entry.context["blocking_reason"] == "Daily loss exceeded"

    def test_audit_entry_from_dict_missing_optional_fields(self):
        """Test from_dict() handles missing optional fields."""
        data = {
            "timestamp": "2025-12-03T14:32:15+00:00",
            "account_id": "ftmo-gold-001",
            "event_type": "rule_check",
            "rule_name": "Test Rule",
            "rule_result": "ALLOW",
        }

        entry = AuditEntry.from_dict(data)

        assert entry.current_value is None
        assert entry.threshold_value is None
        assert entry.order_id is None
        assert entry.context == {}

    def test_audit_entry_default_context(self):
        """Test that context defaults to empty dict."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="rule_check",
            rule_name="Test",
            rule_result="ALLOW",
        )

        assert entry.context == {}


class TestAuditLogger:
    """Tests for AuditLogger class."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.setex = AsyncMock()
        return redis

    @pytest.fixture
    def audit_logger(self, mock_redis):
        """Create an AuditLogger with mock Redis."""
        return AuditLogger(mock_redis, "ftmo-gold-001")

    def test_audit_logger_init(self, mock_redis):
        """Test AuditLogger initialization."""
        logger = AuditLogger(mock_redis, "ftmo-gold-001")

        assert logger.account_id == "ftmo-gold-001"

    @pytest.mark.asyncio
    async def test_log_rule_check_allow(self, audit_logger, mock_redis):
        """Test logging an ALLOW result."""
        rule = MockRule()
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

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args

        # Check TTL
        assert call_args[0][1] == AUDIT_TTL_SECONDS  # 86400 seconds = 24 hours

        # Check key pattern
        key = call_args[0][0]
        assert key.startswith("audit:ftmo-gold-001:")

        # Check value
        value = json.loads(call_args[0][2])
        assert value["event_type"] == "rule_check"
        assert value["rule_result"] == "ALLOW"
        assert value["current_value"] == 3.5
        assert value["threshold_value"] == 5.0

    @pytest.mark.asyncio
    async def test_log_rule_check_block(self, audit_logger, mock_redis):
        """Test logging a BLOCK result includes blocking reason."""
        rule = MockRule(name="Daily Loss Limit")
        result = RuleResult(
            action=RuleAction.BLOCK,
            message="Daily loss 5.5% exceeds limit of 5%",
            current_value=5.5,
            threshold_value=5.0,
        )

        await audit_logger.log_rule_check(
            rule=rule,
            result=result,
            order_id="ORDER-123",
            context={"signal": "BUY", "symbol": "XAUUSD"},
        )

        call_args = mock_redis.setex.call_args
        value = json.loads(call_args[0][2])

        assert value["event_type"] == "trade_blocked"
        assert value["rule_result"] == "BLOCK"
        assert value["context"]["blocking_reason"] == "Daily loss 5.5% exceeds limit of 5%"
        assert value["context"]["signal"] == "BUY"

    @pytest.mark.asyncio
    async def test_log_rule_check_warn(self, audit_logger, mock_redis):
        """Test logging a WARN result."""
        rule = MockRule()
        result = RuleResult(
            action=RuleAction.WARN,
            message="Approaching daily loss limit",
            current_value=4.2,
            threshold_value=5.0,
        )

        await audit_logger.log_rule_check(
            rule=rule,
            result=result,
            order_id="ORDER-123",
            context={"signal": "BUY"},
        )

        call_args = mock_redis.setex.call_args
        value = json.loads(call_args[0][2])

        assert value["event_type"] == "warning_triggered"
        assert value["rule_result"] == "WARN"

    @pytest.mark.asyncio
    async def test_log_rule_check_ttl_is_24_hours(self, audit_logger, mock_redis):
        """Test that TTL is set to 24 hours (86400 seconds)."""
        rule = MockRule()
        result = RuleResult(action=RuleAction.ALLOW)

        await audit_logger.log_rule_check(rule, result)

        call_args = mock_redis.setex.call_args
        ttl = call_args[0][1]
        assert ttl == 86400

    @pytest.mark.asyncio
    async def test_log_rule_check_context_includes_order_details(self, audit_logger, mock_redis):
        """Test that context includes order details."""
        rule = MockRule()
        result = RuleResult(action=RuleAction.ALLOW)

        await audit_logger.log_rule_check(
            rule=rule,
            result=result,
            order_id="ORDER-123",
            context={
                "signal": "BUY",
                "symbol": "XAUUSD",
                "size": 0.1,
                "price": 2050.50,
            },
        )

        call_args = mock_redis.setex.call_args
        value = json.loads(call_args[0][2])

        assert value["order_id"] == "ORDER-123"
        assert value["context"]["signal"] == "BUY"
        assert value["context"]["symbol"] == "XAUUSD"
        assert value["context"]["size"] == 0.1
        assert value["context"]["price"] == 2050.50

    @pytest.mark.asyncio
    async def test_log_rule_check_redis_error_is_caught(self, mock_redis):
        """Test that Redis errors are caught and logged (fire-and-forget)."""
        mock_redis.setex.side_effect = Exception("Redis connection failed")
        logger = AuditLogger(mock_redis, "test-account")

        rule = MockRule()
        result = RuleResult(action=RuleAction.ALLOW)

        # Should not raise
        await logger.log_rule_check(rule, result)


class TestAuditLoggerRegistry:
    """Tests for AuditLoggerRegistry class."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.setex = AsyncMock()
        return redis

    @pytest.fixture
    def registry(self, mock_redis):
        """Create an AuditLoggerRegistry."""
        return AuditLoggerRegistry(mock_redis)

    def test_registry_init(self, mock_redis):
        """Test registry initialization."""
        registry = AuditLoggerRegistry(mock_redis)
        assert registry.account_count == 0
        assert registry.account_ids == []

    def test_get_or_create_new_logger(self, registry):
        """Test creating a new logger for an account."""
        logger = registry.get_or_create("ftmo-gold-001")

        assert logger is not None
        assert logger.account_id == "ftmo-gold-001"
        assert registry.account_count == 1

    def test_get_or_create_returns_same_logger(self, registry):
        """Test that get_or_create returns the same logger instance."""
        logger1 = registry.get_or_create("ftmo-gold-001")
        logger2 = registry.get_or_create("ftmo-gold-001")

        assert logger1 is logger2
        assert registry.account_count == 1

    def test_get_or_create_multiple_accounts(self, registry):
        """Test creating loggers for multiple accounts."""
        logger1 = registry.get_or_create("ftmo-gold-001")
        logger2 = registry.get_or_create("ftmo-silver-002")

        assert logger1.account_id == "ftmo-gold-001"
        assert logger2.account_id == "ftmo-silver-002"
        assert registry.account_count == 2
        assert "ftmo-gold-001" in registry.account_ids
        assert "ftmo-silver-002" in registry.account_ids

    def test_get_logger_existing(self, registry):
        """Test getting an existing logger without creating."""
        registry.get_or_create("ftmo-gold-001")
        logger = registry.get_logger("ftmo-gold-001")

        assert logger is not None
        assert logger.account_id == "ftmo-gold-001"

    def test_get_logger_nonexistent(self, registry):
        """Test getting a nonexistent logger returns None."""
        logger = registry.get_logger("nonexistent")
        assert logger is None

    def test_remove_logger(self, registry):
        """Test removing a logger."""
        registry.get_or_create("ftmo-gold-001")
        assert registry.account_count == 1

        registry.remove_logger("ftmo-gold-001")

        assert registry.account_count == 0
        assert registry.get_logger("ftmo-gold-001") is None

    def test_remove_nonexistent_logger(self, registry):
        """Test removing a nonexistent logger doesn't raise."""
        registry.remove_logger("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_log_all(self, registry, mock_redis):
        """Test log_all convenience method."""
        rule = MockRule()
        result = RuleResult(action=RuleAction.ALLOW)

        await registry.log_all(
            account_id="ftmo-gold-001",
            rule=rule,
            result=result,
            order_id="ORDER-123",
            context={"signal": "BUY"},
        )

        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_all_fire_and_forget(self, registry, mock_redis):
        """Test fire-and-forget logging pattern."""
        rule = MockRule()
        result = RuleResult(action=RuleAction.ALLOW)

        task = registry.log_all_fire_and_forget(
            account_id="ftmo-gold-001",
            rule=rule,
            result=result,
            order_id="ORDER-123",
            context={"signal": "BUY"},
        )

        assert isinstance(task, asyncio.Task)
        await task  # Wait for completion

        mock_redis.setex.assert_called_once()


class TestAuditTaskDoneCallback:
    """Tests for audit_task_done_callback function."""

    def test_callback_handles_cancelled_task(self):
        """Test callback handles cancelled tasks gracefully."""
        task = MagicMock()
        task.cancelled.return_value = True

        # Should not raise
        audit_task_done_callback(task)

    def test_callback_handles_exception(self):
        """Test callback logs task exceptions."""
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = Exception("Test error")
        task.get_name.return_value = "test_task"

        # Should not raise
        audit_task_done_callback(task)

    def test_callback_handles_successful_task(self):
        """Test callback handles successful tasks."""
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None

        # Should not raise
        audit_task_done_callback(task)


class TestAuditDBWriter:
    """Tests for AuditDBWriter batch buffering and flush."""

    @pytest.fixture
    def db_writer(self):
        """Create an AuditDBWriter with test configuration."""
        try:
            # Use a dummy database URL - actual connection not tested in unit tests
            writer = AuditDBWriter(
                database_url="postgresql+asyncpg://test:test@localhost/test",
                batch_size=10,
                flush_interval=1.0,
            )
            return writer
        except ModuleNotFoundError:
            pytest.skip("asyncpg not installed - skipping AuditDBWriter tests")

    def test_db_writer_init(self, db_writer):
        """Test AuditDBWriter initialization."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")
        assert db_writer.buffer_size == 0
        assert db_writer.is_running is False

    @pytest.mark.asyncio
    async def test_add_entry_to_buffer(self, db_writer):
        """Test adding entries to buffer."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="rule_check",
            rule_name="Test",
            rule_result="ALLOW",
        )

        await db_writer.add_entry(entry)

        assert db_writer.buffer_size == 1

    @pytest.mark.asyncio
    async def test_add_multiple_entries(self, db_writer):
        """Test adding multiple entries to buffer."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")
        entries = [
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                account_id="test",
                event_type="rule_check",
                rule_name=f"Test {i}",
                rule_result="ALLOW",
            )
            for i in range(5)
        ]

        await db_writer.add_entries(entries)

        assert db_writer.buffer_size == 5


class TestAuditLogModel:
    """Tests for AuditLogModel SQLAlchemy model."""

    def test_from_audit_entry(self):
        """Test creating AuditLogModel from AuditEntry."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="ftmo-gold-001",
            event_type="rule_check",
            rule_name="Daily Loss Limit 5%",
            rule_result="ALLOW",
            current_value=3.5,
            threshold_value=5.0,
            order_id=str(uuid.uuid4()),
            context={"signal": "BUY"},
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.account_id == "ftmo-gold-001"
        assert model.event_type == "rule_check"
        assert model.rule_name == "Daily Loss Limit 5%"
        assert model.rule_result == "ALLOW"
        assert model.context == {"signal": "BUY"}
        assert model.source == "rule-engine"
        assert model.level == "INFO"

    def test_from_audit_entry_order_id_stored_as_string(self):
        """Test that order_id is stored as string (not UUID)."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="test",
            event_type="rule_check",
            rule_name="Test",
            rule_result="ALLOW",
            order_id="ORDER-12345",
        )

        model = AuditLogModel.from_audit_entry(entry)

        assert model.order_id == "ORDER-12345"


class TestNonBlockingBehavior:
    """Tests for non-blocking (fire-and-forget) behavior."""

    @pytest.mark.asyncio
    async def test_logging_overhead_is_minimal(self):
        """Test that logging overhead is under 2ms."""
        mock_redis = AsyncMock()

        # Make setex take some time to simulate network latency
        async def slow_setex(*args):
            await asyncio.sleep(0.1)  # 100ms simulated latency

        mock_redis.setex = slow_setex

        registry = AuditLoggerRegistry(mock_redis)
        rule = MockRule()
        result = RuleResult(action=RuleAction.ALLOW)

        start = time.perf_counter()

        # Fire-and-forget should return immediately
        task = registry.log_all_fire_and_forget(
            account_id="test",
            rule=rule,
            result=result,
        )

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should return in under 2ms (not waiting for Redis)
        assert elapsed_ms < 2.0, f"Logging took {elapsed_ms:.2f}ms, expected < 2ms"

        # Clean up the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
