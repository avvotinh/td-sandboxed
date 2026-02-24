"""Unit tests for rule violation tracking (Story 7.3).

Tests cover:
- Task 1: RuleViolation dataclass and from_rule_result() factory
- Task 2: RuleViolationModel ORM and from_violation() factory
- Task 3: ViolationDBWriter batch buffer
- Task 4: ViolationService facade methods
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rules.base_rule import RuleAction, RuleResult
from src.rules.violation import ACTION_MAP, RuleViolation
from src.rules.violation_db_writer import RuleViolationModel, ViolationDBWriter
from src.rules.violation_service import ViolationService


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

class FakeRule:
    """Minimal rule satisfying BaseRule protocol."""

    def __init__(
        self,
        rule_type: str = "daily_loss_limit",
        name: str = "FTMO Daily Loss 5%",
        priority: int = 1,
    ):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority

    def validate(self, context):
        return RuleResult()

    def get_current_value(self, context):
        return 0.0

    def get_threshold(self):
        return 5.0

    def get_warning_thresholds(self):
        return [70.0, 80.0, 90.0]


@pytest.fixture
def fake_rule():
    return FakeRule()


@pytest.fixture
def block_result():
    return RuleResult(
        action=RuleAction.BLOCK,
        message="Trade blocked: daily loss 4.80% exceeds 96% of 5.00% limit",
        current_value=4.8,
        threshold_value=5.0,
        metadata={"threshold_pct": 0.96},
    )


@pytest.fixture
def warn_result_90():
    """WARN result at 92% of threshold → CRITICAL severity."""
    return RuleResult(
        action=RuleAction.WARN,
        message="Warning: daily loss at 92% of limit",
        current_value=4.6,
        threshold_value=5.0,
    )


@pytest.fixture
def warn_result_80():
    """WARN result at 85% of threshold → WARNING severity."""
    return RuleResult(
        action=RuleAction.WARN,
        message="Warning: daily loss at 85% of limit",
        current_value=4.25,
        threshold_value=5.0,
    )


@pytest.fixture
def warn_result_low():
    """WARN result at 70% of threshold → INFO severity."""
    return RuleResult(
        action=RuleAction.WARN,
        message="Warning: daily loss at 70% of limit",
        current_value=3.5,
        threshold_value=5.0,
    )


@pytest.fixture
def warn_result_no_threshold():
    """WARN result without threshold values → defaults to WARNING."""
    return RuleResult(
        action=RuleAction.WARN,
        message="Warning: approaching limit",
        current_value=None,
        threshold_value=None,
    )


ACCOUNT_ID = "ftmo-gold-001"


# ===========================================================================
# Task 1: RuleViolation dataclass tests
# ===========================================================================

class TestRuleViolationFromRuleResult:
    """Test 7.1-7.3: RuleViolation.from_rule_result() factory."""

    def test_block_maps_to_fatal_severity(self, fake_rule, block_result):
        """7.1: BLOCK → FATAL severity, order_blocked=True."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        assert violation.severity == "FATAL"
        assert violation.action_taken == "blocked"
        assert violation.order_blocked is True
        assert violation.trade_id is None  # Blocked = no trade
        assert violation.account_id == ACCOUNT_ID
        assert violation.rule_type == "daily_loss_limit"
        assert violation.rule_name == "FTMO Daily Loss 5%"
        assert violation.message == block_result.message

    def test_warn_90_maps_to_critical(self, fake_rule, warn_result_90):
        """7.2: WARN at ≥90% → CRITICAL severity."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_90,
            account_id=ACCOUNT_ID,
        )

        assert violation.severity == "CRITICAL"
        assert violation.action_taken == "warned"
        assert violation.order_blocked is False

    def test_warn_80_maps_to_warning(self, fake_rule, warn_result_80):
        """7.2: WARN at ≥80% → WARNING severity."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_80,
            account_id=ACCOUNT_ID,
        )

        assert violation.severity == "WARNING"
        assert violation.action_taken == "warned"
        assert violation.order_blocked is False

    def test_warn_below_80_maps_to_info(self, fake_rule, warn_result_low):
        """7.2: WARN at <80% → INFO severity."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_low,
            account_id=ACCOUNT_ID,
        )

        assert violation.severity == "INFO"
        assert violation.action_taken == "warned"

    def test_warn_no_threshold_defaults_to_warning(self, fake_rule, warn_result_no_threshold):
        """7.2: WARN without threshold data → WARNING severity."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_no_threshold,
            account_id=ACCOUNT_ID,
        )

        assert violation.severity == "WARNING"
        assert violation.action_taken == "warned"

    def test_threshold_percent_calculated(self, fake_rule, warn_result_90):
        """7.3: threshold_percent = (current / threshold) * 100."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_90,
            account_id=ACCOUNT_ID,
        )

        expected = (4.6 / 5.0) * 100  # 92.0
        assert violation.threshold_percent == pytest.approx(expected)

    def test_threshold_percent_none_when_values_missing(self, fake_rule, warn_result_no_threshold):
        """7.3: threshold_percent is None when values unavailable."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_no_threshold,
            account_id=ACCOUNT_ID,
        )

        assert violation.threshold_percent is None

    def test_threshold_percent_none_when_threshold_zero(self, fake_rule):
        """7.3: threshold_percent is None when threshold is 0 (avoid division by zero)."""
        result = RuleResult(
            action=RuleAction.WARN,
            current_value=1.0,
            threshold_value=0.0,
        )
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=result,
            account_id=ACCOUNT_ID,
        )

        assert violation.threshold_percent is None

    def test_signal_context_included(self, fake_rule, block_result):
        """Signal context is merged into violation context."""
        ctx = {"signal": "BUY", "symbol": "XAUUSD", "size": 0.1, "price": 2650.0}
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
            signal_context=ctx,
        )

        assert violation.context["signal"] == "BUY"
        assert violation.context["symbol"] == "XAUUSD"
        assert violation.context["size"] == 0.1

    def test_rule_metadata_included_in_context(self, fake_rule, block_result):
        """Rule result metadata is nested under 'rule_metadata' key."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        assert "rule_metadata" in violation.context
        assert violation.context["rule_metadata"] == block_result.metadata

    def test_trade_id_passed_through(self, fake_rule, warn_result_80):
        """trade_id is stored when provided (WARN with proceeding trade)."""
        tid = str(uuid.uuid4())
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_80,
            account_id=ACCOUNT_ID,
            trade_id=tid,
        )

        assert violation.trade_id == tid

    def test_timestamp_set_to_utc(self, fake_rule, block_result):
        """Timestamp is set to current UTC time."""
        before = datetime.now(timezone.utc)
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )
        after = datetime.now(timezone.utc)

        assert before <= violation.timestamp <= after
        assert violation.timestamp.tzinfo is not None

    def test_acknowledged_defaults(self, fake_rule, block_result):
        """acknowledged defaults to False, acknowledged_at to None."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        assert violation.acknowledged is False
        assert violation.acknowledged_at is None

    def test_to_dict_serialization(self, fake_rule, block_result):
        """to_dict() returns a JSON-serializable dictionary."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        d = violation.to_dict()
        assert d["account_id"] == ACCOUNT_ID
        assert d["severity"] == "FATAL"
        assert d["action_taken"] == "blocked"
        assert d["order_blocked"] is True
        assert d["rule_type"] == "daily_loss_limit"
        assert isinstance(d["timestamp"], str)


# ===========================================================================
# Task 2: RuleViolationModel ORM tests
# ===========================================================================

class TestRuleViolationModel:
    """Test 7.4: RuleViolationModel.from_violation() mapping."""

    def test_from_violation_maps_all_fields(self, fake_rule, block_result):
        """7.4: All fields mapped correctly with DECIMAL precision."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        model = RuleViolationModel.from_violation(violation)

        assert model.account_id == ACCOUNT_ID
        assert model.rule_type == "daily_loss_limit"
        assert model.rule_name == "FTMO Daily Loss 5%"
        assert model.severity == "FATAL"
        assert model.action_taken == "blocked"
        assert model.order_blocked is True
        assert model.trade_id is None
        assert model.acknowledged is False
        assert model.acknowledged_at is None

    def test_decimal_precision(self, fake_rule, block_result):
        """7.4: Float values converted to Decimal via str()."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        model = RuleViolationModel.from_violation(violation)

        assert isinstance(model.current_value, Decimal)
        assert isinstance(model.threshold_value, Decimal)
        assert model.current_value == Decimal("4.8")
        assert model.threshold_value == Decimal("5.0")

    def test_threshold_percent_decimal(self, fake_rule, warn_result_90):
        """threshold_percent converted to Decimal."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_90,
            account_id=ACCOUNT_ID,
        )

        model = RuleViolationModel.from_violation(violation)

        assert isinstance(model.threshold_percent, Decimal)

    def test_none_values_remain_none(self, fake_rule, warn_result_no_threshold):
        """None numeric values stay None (not Decimal)."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_no_threshold,
            account_id=ACCOUNT_ID,
        )

        model = RuleViolationModel.from_violation(violation)

        assert model.current_value is None
        assert model.threshold_value is None
        assert model.threshold_percent is None

    def test_invalid_severity_raises(self, fake_rule, block_result):
        """Invalid severity raises ValueError (matches DB CHECK constraint)."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )
        violation.severity = "INVALID"

        with pytest.raises(ValueError, match="Invalid severity"):
            RuleViolationModel.from_violation(violation)

    def test_invalid_action_taken_raises(self, fake_rule, block_result):
        """Invalid action_taken raises ValueError (matches DB CHECK constraint)."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )
        violation.action_taken = "invalid_action"

        with pytest.raises(ValueError, match="Invalid action_taken"):
            RuleViolationModel.from_violation(violation)

    def test_trade_id_converted_to_uuid(self, fake_rule, warn_result_80):
        """String trade_id converted to UUID object."""
        tid = str(uuid.uuid4())
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_80,
            account_id=ACCOUNT_ID,
            trade_id=tid,
        )

        model = RuleViolationModel.from_violation(violation)

        assert isinstance(model.trade_id, uuid.UUID)
        assert str(model.trade_id) == tid

    def test_empty_context_stored_as_none(self, fake_rule, warn_result_no_threshold):
        """Empty context dict stored as None in DB."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=warn_result_no_threshold,
            account_id=ACCOUNT_ID,
        )
        violation.context = {}

        model = RuleViolationModel.from_violation(violation)

        assert model.context is None


# ===========================================================================
# Task 3: ViolationDBWriter tests
# ===========================================================================

class TestViolationDBWriter:
    """Test 7.5-7.6: ViolationDBWriter buffer and flush."""

    @pytest.fixture
    def writer(self):
        """Create a ViolationDBWriter with mocked engine."""
        with patch("src.rules.violation_db_writer.create_async_engine") as mock_engine, \
             patch("src.rules.violation_db_writer.async_sessionmaker"):
            w = ViolationDBWriter(
                database_url="postgresql+asyncpg://test:test@localhost/test",
                batch_size=5,
                flush_interval=60.0,
            )
            return w

    @pytest.mark.asyncio
    async def test_add_violation_buffers(self, writer, fake_rule, block_result):
        """7.5: add_violation() adds to buffer."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        await writer.add_violation(violation)

        assert writer.buffer_size == 1

    @pytest.mark.asyncio
    async def test_flush_buffer_uses_session_add_all(self, writer, fake_rule, block_result):
        """7.6: _flush_buffer() persists via session.add_all()."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        await writer.add_violation(violation)
        assert writer.buffer_size == 1

        # Mock the session factory with nested async context managers
        mock_session = MagicMock()
        mock_session.add_all = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_begin)
        mock_begin.__aexit__ = AsyncMock(return_value=False)

        mock_session.begin = MagicMock(return_value=mock_begin)
        writer._session_factory = MagicMock(return_value=mock_session)

        await writer._flush_buffer()

        mock_session.add_all.assert_called_once()
        assert writer.buffer_size == 0

    @pytest.mark.asyncio
    async def test_flush_requeues_on_failure(self, writer, fake_rule, block_result):
        """Entries re-added to buffer on flush failure."""
        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        await writer.add_violation(violation)

        # Make session factory raise
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=Exception("DB error"))
        mock_session.__aexit__ = AsyncMock(return_value=False)
        writer._session_factory.return_value = mock_session

        await writer._flush_buffer()

        # Entry should be re-added to buffer
        assert writer.buffer_size == 1

    @pytest.mark.asyncio
    async def test_start_creates_flush_timer(self, writer):
        """start() creates flush timer task and sets running flag."""
        assert not writer.is_running
        assert writer._flush_task is None

        await writer.start()

        assert writer.is_running
        assert writer._flush_task is not None
        assert writer._flush_task.get_name() == "violation_db_flush_timer"

        # Clean up
        writer._running = False
        writer._flush_task.cancel()
        try:
            await writer._flush_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_start_idempotent(self, writer):
        """start() is idempotent - calling twice doesn't create duplicate tasks."""
        await writer.start()
        first_task = writer._flush_task

        await writer.start()
        assert writer._flush_task is first_task

        # Clean up
        writer._running = False
        writer._flush_task.cancel()
        try:
            await writer._flush_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_and_disposes(self, writer, fake_rule, block_result):
        """stop() cancels timer, flushes remaining buffer, disposes engine."""
        await writer.start()

        violation = RuleViolation.from_rule_result(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )
        await writer.add_violation(violation)
        assert writer.buffer_size == 1

        # Mock session for flush during stop
        mock_session = MagicMock()
        mock_session.add_all = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_begin)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)
        writer._session_factory = MagicMock(return_value=mock_session)

        # Mock engine.dispose()
        writer._engine = MagicMock()
        writer._engine.dispose = AsyncMock()

        await writer.stop()

        assert not writer.is_running
        assert writer._flush_task is None
        mock_session.add_all.assert_called_once()
        writer._engine.dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, writer):
        """stop() is idempotent - calling when not running is a no-op."""
        assert not writer.is_running
        await writer.stop()  # Should not raise
        assert not writer.is_running

    @pytest.mark.asyncio
    async def test_auto_flush_at_batch_threshold(self, writer, fake_rule, block_result):
        """Adding batch_size violations triggers automatic flush."""
        # Mock session for the auto-flush
        mock_session = MagicMock()
        mock_session.add_all = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_begin)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)
        writer._session_factory = MagicMock(return_value=mock_session)

        # batch_size is 5 for the test writer fixture
        for i in range(5):
            violation = RuleViolation.from_rule_result(
                rule=fake_rule,
                result=block_result,
                account_id=ACCOUNT_ID,
            )
            await writer.add_violation(violation)

        # Allow the fire-and-forget flush task to execute
        await asyncio.sleep(0)

        # Buffer should be drained by auto-flush
        mock_session.add_all.assert_called_once()
        flushed_entries = mock_session.add_all.call_args[0][0]
        assert len(flushed_entries) == 5
        assert writer.buffer_size == 0


# ===========================================================================
# Task 4: ViolationService tests
# ===========================================================================

class TestViolationService:
    """Test 7.7-7.8: ViolationService convenience methods."""

    @pytest.fixture
    def mock_writer(self):
        return AsyncMock(spec=ViolationDBWriter)

    @pytest.fixture
    def service(self, mock_writer):
        return ViolationService(mock_writer)

    @pytest.mark.asyncio
    async def test_record_block_creates_correct_violation(
        self, service, mock_writer, fake_rule, block_result,
    ):
        """7.7: record_block() creates RuleViolation with trade_id=None."""
        await service.record_block(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
            signal_context={"signal": "BUY", "symbol": "XAUUSD"},
        )

        mock_writer.add_violation.assert_awaited_once()
        violation = mock_writer.add_violation.call_args[0][0]
        assert isinstance(violation, RuleViolation)
        assert violation.severity == "FATAL"
        assert violation.action_taken == "blocked"
        assert violation.order_blocked is True
        assert violation.trade_id is None

    @pytest.mark.asyncio
    async def test_record_warning_critical(
        self, service, mock_writer, fake_rule, warn_result_90,
    ):
        """7.8: record_warning() at ≥90% → CRITICAL severity."""
        await service.record_warning(
            rule=fake_rule,
            result=warn_result_90,
            account_id=ACCOUNT_ID,
        )

        mock_writer.add_violation.assert_awaited_once()
        violation = mock_writer.add_violation.call_args[0][0]
        assert violation.severity == "CRITICAL"
        assert violation.action_taken == "warned"
        assert violation.order_blocked is False

    @pytest.mark.asyncio
    async def test_record_warning_warning_level(
        self, service, mock_writer, fake_rule, warn_result_80,
    ):
        """7.8: record_warning() at ≥80% → WARNING severity."""
        await service.record_warning(
            rule=fake_rule,
            result=warn_result_80,
            account_id=ACCOUNT_ID,
        )

        violation = mock_writer.add_violation.call_args[0][0]
        assert violation.severity == "WARNING"

    @pytest.mark.asyncio
    async def test_record_warning_info_level(
        self, service, mock_writer, fake_rule, warn_result_low,
    ):
        """7.8: record_warning() at <80% → INFO severity."""
        await service.record_warning(
            rule=fake_rule,
            result=warn_result_low,
            account_id=ACCOUNT_ID,
        )

        violation = mock_writer.add_violation.call_args[0][0]
        assert violation.severity == "INFO"

    @pytest.mark.asyncio
    async def test_record_warning_with_trade_id(
        self, service, mock_writer, fake_rule, warn_result_80,
    ):
        """record_warning() passes trade_id when trade proceeds."""
        tid = str(uuid.uuid4())
        await service.record_warning(
            rule=fake_rule,
            result=warn_result_80,
            account_id=ACCOUNT_ID,
            trade_id=tid,
        )

        violation = mock_writer.add_violation.call_args[0][0]
        assert violation.trade_id == tid

    @pytest.mark.asyncio
    async def test_record_violation_generic(
        self, service, mock_writer, fake_rule, block_result,
    ):
        """record_violation() delegates to writer."""
        await service.record_violation(
            rule=fake_rule,
            result=block_result,
            account_id=ACCOUNT_ID,
        )

        mock_writer.add_violation.assert_awaited_once()
