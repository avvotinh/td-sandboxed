# Tech-Spec: Epic 3 - FTMO Compliance Engine

**Created:** 2025-12-04
**Status:** Ready for Development
**Epic:** 3 - FTMO Compliance Engine
**Service:** trading-engine (Python/Nautilus Trader)

---

## Overview

### Problem Statement

FTMO challenges require strict adherence to risk rules - a single violation terminates the account. Traditional trading systems treat compliance as an afterthought (end-of-day checks), but violations can occur intra-day. The trading-engine needs a first-class compliance engine that:

1. Validates rules in **real-time** after every bar (not end-of-day)
2. **Prevents violations before they happen** through order blocking
3. Supports **declarative YAML configuration** for different prop firms
4. Maintains an **immutable audit trail** for accountability

### Solution

Build a multi-layer FTMO Compliance Engine with:

- **YAML Rule Configuration Loader** - Declarative rules as data, not code
- **Daily Loss Validator** - Enforce 5% max daily loss with preventive blocking
- **Total Drawdown Validator** - Enforce 10% max drawdown from starting balance
- **Profit Target & Trading Days Tracker** - Track challenge progress
- **Multi-Layer Compliance Validation** - Strategy, account, and system-level checks
- **Immutable Audit Logger** - Append-only compliance audit trail
- **Emergency Stop Mechanism** - Immediate trading halt when triggered

### Scope

**In Scope:**
- YAML-based rule configuration with Pydantic validation
- Real-time daily P&L tracking (intraday, not EOD)
- Drawdown calculation from starting balance (FTMO method)
- Preventive order blocking at configurable thresholds (70-95%)
- Multi-layer validation pipeline (strategy → account → system)
- Audit logging to TimescaleDB (append-only)
- Emergency stop via CLI and Telegram command
- Support for multiple prop firm rule configurations

**Out of Scope:**
- Strategy execution logic (Epic 4)
- Backtesting integration (Epic 5)
- State management/recovery (Epic 6)
- Position sizing (moved to Epic 4)

**Dependencies:**
- Epic 1: Configuration system, structured logging, CLI framework
- Epic 2: TimescaleDB adapter for audit persistence, Redis for state

---

## Context for Development

### Codebase Patterns

**From Architecture Document (Section: trading-engine):**

```
services/trading-engine/src/
├── risk/                    # Risk & compliance
│   ├── __init__.py
│   ├── ftmo_rules.py        # FTMO rule engine
│   ├── validators.py        # Rule validators
│   └── audit_logger.py      # Compliance audit trail
```

**Proposed Directory Structure for Epic 3:**

```
services/trading-engine/src/
├── config/
│   ├── ftmo_rules.yaml      # Default FTMO Phase 1 rules
│   ├── ftmo_phase2.yaml     # FTMO Phase 2 rules
│   └── ftuk_rules.yaml      # FTUK rules (extensibility)
├── risk/
│   ├── __init__.py
│   ├── models.py            # Pydantic rule models
│   ├── loader.py            # YAML rule loader
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── base.py          # Abstract validator
│   │   ├── daily_loss.py    # Daily loss validator
│   │   ├── drawdown.py      # Total drawdown validator
│   │   ├── trading_days.py  # Trading days tracker
│   │   └── profit_target.py # Profit target tracker
│   ├── engine.py            # Multi-layer rule engine
│   ├── audit.py             # Immutable audit logger
│   └── emergency.py         # Emergency stop mechanism
```

### Files to Reference

| File | Purpose |
|------|---------|
| `docs/architecture.md` | Section 3: trading-engine structure, Section 7: TimescaleDB schema |
| `docs/epics-trading-engine.md` | Stories 3.1-3.7 acceptance criteria, FR8-17 |
| `docs/prd.md` | FTMO Compliance requirements (FR8-17), domain-specific requirements |
| `docs/sprint-artifacts/tech-spec-epic-2-adapters.md` | TimescaleDB adapter interface |

### Technical Decisions

#### TD-1: Pydantic for Rule Schema Validation

**Decision:** Use Pydantic BaseModel with ConfigDict for YAML rule schemas

**Rationale (from Context7 research):**
- Type-safe validation with clear error messages
- ConfigDict allows strict validation and extra field handling
- Nested model support for complex rule structures
- `model_validator` for cross-field validation (e.g., warning < blocking threshold)

**Implementation Pattern:**

```python
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from typing_extensions import Self


class RuleThresholds(BaseModel):
    """Threshold configuration for a compliance rule."""
    model_config = ConfigDict(strict=True, frozen=True)

    enabled: bool = True
    warning_threshold: Decimal = Field(ge=0, le=100, description="Percent of limit to warn")
    blocking_threshold: Decimal = Field(ge=0, le=100, description="Percent of limit to block")

    @model_validator(mode='after')
    def validate_thresholds(self) -> Self:
        if self.warning_threshold >= self.blocking_threshold:
            raise ValueError('warning_threshold must be less than blocking_threshold')
        return self


class DailyLossRule(BaseModel):
    """FTMO daily loss rule configuration."""
    model_config = ConfigDict(strict=True, frozen=True)

    max_loss_percent: Decimal = Field(ge=0, le=100, default=Decimal("5.0"))
    thresholds: RuleThresholds = Field(
        default_factory=lambda: RuleThresholds(
            warning_threshold=Decimal("70"),
            blocking_threshold=Decimal("95")
        )
    )


class TotalDrawdownRule(BaseModel):
    """FTMO total drawdown rule configuration."""
    model_config = ConfigDict(strict=True, frozen=True)

    max_drawdown_percent: Decimal = Field(ge=0, le=100, default=Decimal("10.0"))
    thresholds: RuleThresholds = Field(
        default_factory=lambda: RuleThresholds(
            warning_threshold=Decimal("70"),
            blocking_threshold=Decimal("95")
        )
    )


class ProfitTargetRule(BaseModel):
    """FTMO profit target rule configuration."""
    model_config = ConfigDict(strict=True, frozen=True)

    enabled: bool = True
    target_percent: Decimal = Field(ge=0, le=100, default=Decimal("10.0"))


class TradingDaysRule(BaseModel):
    """FTMO minimum trading days rule configuration."""
    model_config = ConfigDict(strict=True, frozen=True)

    enabled: bool = True
    required_days: int = Field(ge=0, default=4)


class FTMORuleSet(BaseModel):
    """Complete FTMO rule configuration."""
    model_config = ConfigDict(strict=True, extra='forbid')

    version: str = "1.0"
    challenge_type: Literal["phase1", "phase2", "funded"] = "phase1"

    daily_loss: DailyLossRule = Field(default_factory=DailyLossRule)
    total_drawdown: TotalDrawdownRule = Field(default_factory=TotalDrawdownRule)
    profit_target: ProfitTargetRule = Field(default_factory=ProfitTargetRule)
    trading_days: TradingDaysRule = Field(default_factory=TradingDaysRule)
```

#### TD-2: YAML Configuration with Pydantic-Settings

**Decision:** Use PyYAML + Pydantic for YAML rule loading with environment override

**Rationale (from Context7 research):**
- pydantic-settings supports multiple config sources with priority
- YAML files for rule definitions, env vars for overrides
- Validation on load with clear error messages

**Implementation Pattern:**

```python
import yaml
from pathlib import Path
from pydantic import ValidationError
from .models import FTMORuleSet


class RuleLoader:
    """Load and validate FTMO rules from YAML configuration."""

    def __init__(self, config_dir: Path):
        self._config_dir = config_dir
        self._cache: dict[str, FTMORuleSet] = {}

    def load(self, rule_file: str = "ftmo_rules.yaml") -> FTMORuleSet:
        """Load rules from YAML file with validation."""
        if rule_file in self._cache:
            return self._cache[rule_file]

        path = self._config_dir / rule_file
        if not path.exists():
            raise FileNotFoundError(f"Rule file not found: {path}")

        with open(path) as f:
            raw_config = yaml.safe_load(f)

        try:
            rules = FTMORuleSet.model_validate(raw_config)
            self._cache[rule_file] = rules
            return rules
        except ValidationError as e:
            raise ValueError(f"Invalid rule configuration in {rule_file}: {e}")

    def reload(self, rule_file: str = "ftmo_rules.yaml") -> FTMORuleSet:
        """Force reload of rule configuration (for hot reload)."""
        self._cache.pop(rule_file, None)
        return self.load(rule_file)
```

#### TD-3: Validation Result Pattern

**Decision:** Use dataclass-based ValidationResult for rule check outcomes

**Rationale:**
- Consistent return type across all validators
- Includes context for debugging and audit logging
- Supports aggregation in multi-layer validation

**Implementation Pattern:**

```python
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class ValidationStatus(Enum):
    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"
    ERROR = "error"


class ValidationLayer(Enum):
    STRATEGY = "strategy"
    ACCOUNT = "account"
    SYSTEM = "system"


@dataclass(frozen=True)
class ValidationResult:
    """Result of a compliance rule validation."""

    status: ValidationStatus
    rule_name: str
    layer: ValidationLayer
    current_value: Decimal
    threshold_value: Decimal
    limit_value: Decimal
    percent_used: Decimal
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status in (ValidationStatus.PASS, ValidationStatus.WARNING)

    @property
    def should_block(self) -> bool:
        return self.status == ValidationStatus.BLOCKED

    @property
    def should_warn(self) -> bool:
        return self.status == ValidationStatus.WARNING
```

#### TD-4: Multi-Layer Validation Pipeline

**Decision:** Chain validators in fixed order: strategy → account → system

**Rationale (from Nautilus Trader RiskEngine pattern):**
- Early rejection saves processing
- Each layer has distinct concerns
- Aggregate results for comprehensive audit

**Implementation Pattern:**

```python
from abc import ABC, abstractmethod
from typing import Protocol


class OrderContext(Protocol):
    """Context needed for order validation."""
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal | None


class ComplianceValidator(ABC):
    """Abstract base for compliance validators."""

    @property
    @abstractmethod
    def rule_name(self) -> str:
        """Name of the rule this validator enforces."""
        pass

    @property
    @abstractmethod
    def layer(self) -> ValidationLayer:
        """Validation layer (strategy, account, system)."""
        pass

    @abstractmethod
    async def validate(
        self,
        order: OrderContext,
        account_state: "AccountState",
    ) -> ValidationResult:
        """Validate order against this rule."""
        pass


class ComplianceEngine:
    """Multi-layer compliance validation engine."""

    def __init__(
        self,
        rules: FTMORuleSet,
        validators: list[ComplianceValidator],
        audit_logger: "AuditLogger",
    ):
        self._rules = rules
        self._validators = sorted(validators, key=lambda v: v.layer.value)
        self._audit_logger = audit_logger
        self._emergency_stop = False

    async def validate_order(
        self,
        order: OrderContext,
        account_state: "AccountState",
    ) -> tuple[bool, list[ValidationResult]]:
        """
        Validate order against all compliance rules.

        Returns:
            Tuple of (allowed, results) where allowed is False if any rule blocks.
        """
        if self._emergency_stop:
            return False, [ValidationResult(
                status=ValidationStatus.BLOCKED,
                rule_name="emergency_stop",
                layer=ValidationLayer.SYSTEM,
                current_value=Decimal("0"),
                threshold_value=Decimal("0"),
                limit_value=Decimal("0"),
                percent_used=Decimal("100"),
                message="Emergency stop is active - all trading halted",
            )]

        results: list[ValidationResult] = []

        for validator in self._validators:
            result = await validator.validate(order, account_state)
            results.append(result)

            # Log every validation
            await self._audit_logger.log_validation(result, order)

            # Early exit on block
            if result.should_block:
                return False, results

        return True, results

    def trigger_emergency_stop(self, reason: str) -> None:
        """Trigger emergency stop - halt all trading."""
        self._emergency_stop = True
        # Log will be handled by caller

    def clear_emergency_stop(self) -> None:
        """Clear emergency stop - resume trading."""
        self._emergency_stop = False

    @property
    def is_emergency_stopped(self) -> bool:
        return self._emergency_stop
```

#### TD-5: Nautilus Portfolio Integration

**Decision:** Use Nautilus Portfolio for account state access

**Rationale (from Context7 research):**
- `portfolio.realized_pnl()` and `portfolio.unrealized_pnl()` for P&L
- `portfolio.account(venue).balance_total()` for balance
- Consistent interface for backtest and live

**Implementation Pattern:**

```python
from decimal import Decimal
from datetime import date
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.model.identifiers import Venue


class AccountState:
    """Account state wrapper for compliance validation."""

    def __init__(
        self,
        portfolio: Portfolio,
        venue: Venue,
        starting_balance: Decimal,
        peak_balance: Decimal,
        daily_start_balance: Decimal,
        trading_days: set[date],
    ):
        self._portfolio = portfolio
        self._venue = venue
        self._starting_balance = starting_balance
        self._peak_balance = peak_balance
        self._daily_start_balance = daily_start_balance
        self._trading_days = trading_days

    @property
    def current_balance(self) -> Decimal:
        """Current account balance including unrealized P&L."""
        account = self._portfolio.account(self._venue)
        if not account:
            return self._starting_balance
        return account.balance_total().as_decimal()

    @property
    def starting_balance(self) -> Decimal:
        """Balance at start of challenge."""
        return self._starting_balance

    @property
    def peak_balance(self) -> Decimal:
        """Highest balance reached (high water mark)."""
        return max(self._peak_balance, self.current_balance)

    @property
    def daily_pnl(self) -> Decimal:
        """Today's P&L (realized + unrealized)."""
        return self.current_balance - self._daily_start_balance

    @property
    def daily_pnl_percent(self) -> Decimal:
        """Today's P&L as percent of starting balance."""
        if self._starting_balance == 0:
            return Decimal("0")
        return (self.daily_pnl / self._starting_balance) * 100

    @property
    def total_drawdown(self) -> Decimal:
        """Current drawdown from starting balance (FTMO method)."""
        return self._starting_balance - self.current_balance

    @property
    def total_drawdown_percent(self) -> Decimal:
        """Current drawdown as percent of starting balance."""
        if self._starting_balance == 0:
            return Decimal("0")
        return (self.total_drawdown / self._starting_balance) * 100

    @property
    def total_profit_percent(self) -> Decimal:
        """Current profit as percent of starting balance."""
        profit = self.current_balance - self._starting_balance
        if self._starting_balance == 0:
            return Decimal("0")
        return (profit / self._starting_balance) * 100

    @property
    def trading_days_count(self) -> int:
        """Number of unique trading days."""
        return len(self._trading_days)

    def record_trading_day(self, day: date) -> None:
        """Record that trading occurred on this day."""
        self._trading_days.add(day)
```

#### TD-6: Immutable Audit Logging

**Decision:** Append-only audit logs to TimescaleDB with checksum

**Rationale:**
- TimescaleDB hypertable for time-series audit data
- Checksum for tamper detection
- Batch writes for performance (flush every 1 second)

**Implementation Pattern:**

```python
import hashlib
import json
import uuid
from asyncio import Queue, create_task, sleep
from datetime import datetime
from decimal import Decimal
from typing import Any

from .models import ValidationResult


class AuditLogger:
    """Immutable audit logger for compliance events."""

    def __init__(
        self,
        timescale_adapter: "TimescaleDBAdapter",
        flush_interval: float = 1.0,
        batch_size: int = 100,
    ):
        self._adapter = timescale_adapter
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._queue: Queue[dict] = Queue()
        self._running = False

    async def start(self) -> None:
        """Start the audit logger background task."""
        self._running = True
        create_task(self._flush_loop())

    async def stop(self) -> None:
        """Stop the audit logger and flush remaining entries."""
        self._running = False
        await self._flush()

    async def log_validation(
        self,
        result: ValidationResult,
        order: "OrderContext",
    ) -> None:
        """Log a compliance validation result."""
        entry = self._create_entry(
            event_type="compliance_check",
            rule_name=result.rule_name,
            rule_result=result.status.value,
            current_value=result.current_value,
            threshold_value=result.threshold_value,
            order_id=getattr(order, 'order_id', None),
            context={
                "layer": result.layer.value,
                "percent_used": str(result.percent_used),
                "limit_value": str(result.limit_value),
                "message": result.message,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": str(order.quantity),
            },
        )
        await self._queue.put(entry)

    async def log_emergency_stop(
        self,
        reason: str,
        triggered_by: str,
    ) -> None:
        """Log emergency stop activation."""
        entry = self._create_entry(
            event_type="emergency_stop",
            rule_name="emergency_stop",
            rule_result="triggered",
            current_value=Decimal("0"),
            threshold_value=Decimal("0"),
            context={"reason": reason, "triggered_by": triggered_by},
        )
        await self._queue.put(entry)

    async def log_order_blocked(
        self,
        order: "OrderContext",
        results: list[ValidationResult],
    ) -> None:
        """Log a blocked order with all validation results."""
        blocking_result = next((r for r in results if r.should_block), None)
        entry = self._create_entry(
            event_type="order_blocked",
            rule_name=blocking_result.rule_name if blocking_result else "unknown",
            rule_result="blocked",
            current_value=blocking_result.current_value if blocking_result else Decimal("0"),
            threshold_value=blocking_result.threshold_value if blocking_result else Decimal("0"),
            order_id=getattr(order, 'order_id', None),
            context={
                "symbol": order.symbol,
                "side": order.side,
                "quantity": str(order.quantity),
                "all_results": [
                    {
                        "rule": r.rule_name,
                        "status": r.status.value,
                        "percent_used": str(r.percent_used),
                    }
                    for r in results
                ],
            },
        )
        await self._queue.put(entry)

    def _create_entry(
        self,
        event_type: str,
        rule_name: str,
        rule_result: str,
        current_value: Decimal,
        threshold_value: Decimal,
        order_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict:
        """Create an audit log entry with checksum."""
        timestamp = datetime.utcnow()
        log_id = str(uuid.uuid4())

        entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "rule_name": rule_name,
            "rule_result": rule_result,
            "current_value": current_value,
            "threshold_value": threshold_value,
            "order_id": order_id,
            "context": context or {},
        }

        # Add checksum for tamper detection
        checksum_data = f"{log_id}:{timestamp.isoformat()}:{event_type}:{rule_name}:{rule_result}"
        entry["checksum"] = hashlib.sha256(checksum_data.encode()).hexdigest()

        return entry

    async def _flush_loop(self) -> None:
        """Background task to flush audit entries."""
        while self._running:
            await sleep(self._flush_interval)
            await self._flush()

    async def _flush(self) -> None:
        """Flush queued entries to database."""
        entries = []
        while not self._queue.empty() and len(entries) < self._batch_size:
            entries.append(await self._queue.get())

        if entries:
            for entry in entries:
                await self._adapter.save_audit_log(entry)
```

---

## Implementation Plan

### Tasks

#### Story 3.1: YAML Rule Configuration Loader

- [ ] **Task 3.1.1:** Create `src/risk/models.py` with Pydantic rule models (FTMORuleSet, DailyLossRule, etc.)
- [ ] **Task 3.1.2:** Add `model_validator` for threshold validation (warning < blocking)
- [ ] **Task 3.1.3:** Create `src/risk/loader.py` with RuleLoader class
- [ ] **Task 3.1.4:** Implement `load()` method with YAML parsing and Pydantic validation
- [ ] **Task 3.1.5:** Implement `reload()` method for hot reload support
- [ ] **Task 3.1.6:** Create default `config/ftmo_rules.yaml` with Phase 1 rules
- [ ] **Task 3.1.7:** Create `config/ftmo_phase2.yaml` with Phase 2 rules (8%/20% targets)
- [ ] **Task 3.1.8:** Write unit tests for rule loading and validation errors

#### Story 3.2: Daily Loss Validator

- [ ] **Task 3.2.1:** Create `src/risk/validators/base.py` with ComplianceValidator ABC
- [ ] **Task 3.2.2:** Create `src/risk/validators/daily_loss.py` with DailyLossValidator
- [ ] **Task 3.2.3:** Implement intraday P&L calculation (realized + unrealized)
- [ ] **Task 3.2.4:** Implement percent-of-limit calculation against starting balance
- [ ] **Task 3.2.5:** Implement WARNING status when >= warning_threshold (70%)
- [ ] **Task 3.2.6:** Implement BLOCKED status when >= blocking_threshold (95%)
- [ ] **Task 3.2.7:** Add daily reset logic (00:00 UTC detection)
- [ ] **Task 3.2.8:** Persist daily metrics to Redis for recovery
- [ ] **Task 3.2.9:** Write unit tests for all threshold scenarios

#### Story 3.3: Total Drawdown Validator

- [ ] **Task 3.3.1:** Create `src/risk/validators/drawdown.py` with TotalDrawdownValidator
- [ ] **Task 3.3.2:** Implement drawdown calculation from starting balance (FTMO method)
- [ ] **Task 3.3.3:** Track peak balance (high water mark) - NOTE: FTMO uses starting balance as denominator
- [ ] **Task 3.3.4:** Implement WARNING status at 70% of limit (7% drawdown)
- [ ] **Task 3.3.5:** Implement BLOCKED status at 95% of limit (9.5% drawdown)
- [ ] **Task 3.3.6:** Persist peak balance to Redis for recovery
- [ ] **Task 3.3.7:** Write unit tests including edge cases (profit then loss)

#### Story 3.4: Profit Target & Trading Days Tracker

- [ ] **Task 3.4.1:** Create `src/risk/validators/profit_target.py` with ProfitTargetValidator
- [ ] **Task 3.4.2:** Implement profit percent calculation against starting balance
- [ ] **Task 3.4.3:** Return progress status (not blocking, informational)
- [ ] **Task 3.4.4:** Create `src/risk/validators/trading_days.py` with TradingDaysValidator
- [ ] **Task 3.4.5:** Track unique calendar days with at least 1 trade
- [ ] **Task 3.4.6:** Persist trading days to TimescaleDB
- [ ] **Task 3.4.7:** Return progress status (X/Y days completed)
- [ ] **Task 3.4.8:** Write unit tests for progress tracking

#### Story 3.5: Multi-Layer Compliance Validation

- [ ] **Task 3.5.1:** Create `src/risk/engine.py` with ComplianceEngine class
- [ ] **Task 3.5.2:** Implement validator registration and ordering (strategy → account → system)
- [ ] **Task 3.5.3:** Implement `validate_order()` with early exit on block
- [ ] **Task 3.5.4:** Create AccountState class for portfolio state access
- [ ] **Task 3.5.5:** Integrate with Nautilus Portfolio for balance/P&L
- [ ] **Task 3.5.6:** Implement aggregate result collection for audit
- [ ] **Task 3.5.7:** Add emergency stop check as first validation
- [ ] **Task 3.5.8:** Write integration tests for multi-layer validation

#### Story 3.6: Immutable Audit Logger

- [ ] **Task 3.6.1:** Create `src/risk/audit.py` with AuditLogger class
- [ ] **Task 3.6.2:** Implement async queue for non-blocking logging
- [ ] **Task 3.6.3:** Implement batch writes with flush interval (1 second)
- [ ] **Task 3.6.4:** Add SHA256 checksum for tamper detection
- [ ] **Task 3.6.5:** Implement `log_validation()` for every rule check
- [ ] **Task 3.6.6:** Implement `log_order_blocked()` for blocked orders
- [ ] **Task 3.6.7:** Implement `log_emergency_stop()` for emergency events
- [ ] **Task 3.6.8:** Use TimescaleDB adapter from Epic 2 for persistence
- [ ] **Task 3.6.9:** Write unit tests with mock adapter

#### Story 3.7: Emergency Stop Mechanism

- [ ] **Task 3.7.1:** Create `src/risk/emergency.py` with EmergencyStopManager
- [ ] **Task 3.7.2:** Store emergency stop flag in Redis (persistent across restarts)
- [ ] **Task 3.7.3:** Implement `trigger()` method - set flag, log, send alert
- [ ] **Task 3.7.4:** Implement `clear()` method - clear flag, log, require confirmation
- [ ] **Task 3.7.5:** Add auto-trigger when daily loss > 100% of limit
- [ ] **Task 3.7.6:** Add CLI commands: `python -m src emergency-stop` and `python -m src clear-stop`
- [ ] **Task 3.7.7:** Block engine startup when emergency stop is active
- [ ] **Task 3.7.8:** Integrate with notification service (Redis pub/sub alert)
- [ ] **Task 3.7.9:** Write unit tests for all trigger scenarios

---

### Acceptance Criteria

#### Story 3.1: YAML Rule Configuration Loader

- [ ] **AC 3.1.1:** Given a file `config/ftmo_rules.yaml` with valid YAML, When engine starts, Then rules are loaded and validated with Pydantic
- [ ] **AC 3.1.2:** Given invalid YAML (missing required field), When engine starts, Then it fails with clear error: `ValidationError: Missing required field 'max_loss_percent'`
- [ ] **AC 3.1.3:** Given warning_threshold >= blocking_threshold, When rules load, Then validation fails with: `warning_threshold must be less than blocking_threshold`
- [ ] **AC 3.1.4:** Given I want FTUK rules, When I create `config/ftuk_rules.yaml`, Then I can switch by changing config without code changes

#### Story 3.2: Daily Loss Validator

- [ ] **AC 3.2.1:** Given starting balance is $100,000 and daily P&L is -$3,500 (3.5% loss), When compliance check runs, Then status is PASS with 70% of limit used
- [ ] **AC 3.2.2:** Given daily P&L reaches -$3,850 (3.85% loss), When compliance check runs, Then status is WARNING (77% of limit) and alert is published
- [ ] **AC 3.2.3:** Given daily P&L reaches -$4,750 (4.75% loss), When I try to submit new order, Then order is BLOCKED (95% threshold) and audit log records the blocked order
- [ ] **AC 3.2.4:** Given it's a new trading day (00:00 UTC), When daily metrics reset, Then daily P&L resets to 0

#### Story 3.3: Total Drawdown Validator

- [ ] **AC 3.3.1:** Given starting balance is $100,000, peak balance reached $105,000, current balance is $96,000, When compliance check runs, Then drawdown is calculated as ($100,000 - $96,000) / $100,000 = 4%
- [ ] **AC 3.3.2:** Given drawdown reaches 7% of 10% limit, When compliance check runs, Then status is WARNING and alert published
- [ ] **AC 3.3.3:** Given drawdown reaches 9.5% of 10% limit, When I try to submit new order, Then order is BLOCKED

#### Story 3.4: Profit Target & Trading Days Tracker

- [ ] **AC 3.4.1:** Given Phase 1 profit target is 10% and current profit is 8%, When I query progress, Then I see 80% of target achieved
- [ ] **AC 3.4.2:** Given I have traded on 3 unique days and minimum required is 4 days, When I query progress, Then I see 3/4 trading days completed
- [ ] **AC 3.4.3:** Given I reach 10% profit with only 3 trading days, When compliance check runs, Then status shows "Profit target met, need 1 more trading day"

#### Story 3.5: Multi-Layer Compliance Validation

- [ ] **AC 3.5.1:** Given a strategy generates a BUY signal, When order is submitted, Then validation runs in order: strategy-level, account-level, system-level
- [ ] **AC 3.5.2:** Given account-level daily_loss check fails, When validation runs, Then order is rejected with: `ValidationResult(passed=False, layer="account", rule="daily_loss", reason="Would exceed 95% of daily loss limit")`
- [ ] **AC 3.5.3:** Given all layers pass, When validation completes, Then all results are logged to audit trail

#### Story 3.6: Immutable Audit Logger

- [ ] **AC 3.6.1:** Given a compliance check runs, Then an audit entry is created with: timestamp, event_type, rule_name, rule_result, current_value, threshold_value, context, checksum
- [ ] **AC 3.6.2:** Given an order is blocked, Then audit entry includes order details and block reason
- [ ] **AC 3.6.3:** Given audit entries exist, When I try to modify or delete them, Then operation is rejected (append-only)

#### Story 3.7: Emergency Stop Mechanism

- [ ] **AC 3.7.1:** Given trading is active, When I trigger emergency stop (via CLI), Then all pending orders are cancelled, no new orders accepted, alert sent
- [ ] **AC 3.7.2:** Given a critical violation is detected (>100% of limit), When violation occurs, Then emergency stop is automatically triggered
- [ ] **AC 3.7.3:** Given emergency stop is active, When I run `python -m src run`, Then engine refuses to start until stop is cleared

---

## Additional Context

### Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| pydantic | >= 2.5.0 | Rule schema validation |
| pydantic-settings | >= 2.1.0 | Configuration management |
| PyYAML | >= 6.0.0 | YAML file parsing |
| nautilus_trader | >= 1.200.0 | Portfolio access, account state |
| redis | >= 5.0.0 | State persistence, pub/sub alerts |
| asyncpg | >= 0.29.0 | TimescaleDB audit logging |

### YAML Rule Configuration Example

```yaml
# config/ftmo_rules.yaml
version: "1.0"
challenge_type: "phase1"

daily_loss:
  max_loss_percent: 5.0
  thresholds:
    enabled: true
    warning_threshold: 70
    blocking_threshold: 95

total_drawdown:
  max_drawdown_percent: 10.0
  thresholds:
    enabled: true
    warning_threshold: 70
    blocking_threshold: 95

profit_target:
  enabled: true
  target_percent: 10.0

trading_days:
  enabled: true
  required_days: 4
```

### FTMO Rule Specifics

**Daily Loss Calculation (FR9):**
- Calculated from **starting balance of the day** (not previous close)
- Includes both realized AND unrealized P&L
- Resets at 00:00 UTC (FTMO server time)

**Total Drawdown Calculation (FR10):**
- FTMO uses **starting balance** as denominator (not peak balance)
- Formula: `(starting_balance - current_equity) / starting_balance`
- This is MORE restrictive than peak-to-trough drawdown

**Trading Days (FR11):**
- A "trading day" requires at least 1 executed trade
- Must be unique calendar days (not 24-hour periods)

### Redis Keys for State

```
# Emergency stop flag
Key: compliance:emergency_stop
Value: "active" | "inactive"
TTL: None (persistent)

# Daily metrics (for recovery)
Key: compliance:daily:{date}
Fields:
  daily_start_balance: 100000.00
  daily_pnl: -350.00
  peak_balance: 102500.00
  trades_today: 3
TTL: 7 days

# Trading days set
Key: compliance:trading_days:{account_id}
Type: Set
Members: ["2025-12-01", "2025-12-02", ...]
TTL: None (persistent through challenge)
```

### TimescaleDB Audit Schema

```sql
-- Audit Logs (from Architecture, with checksum addition)
CREATE TABLE audit_logs (
    log_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    rule_name VARCHAR(100),
    rule_result VARCHAR(20),
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    order_id UUID,
    context JSONB,
    checksum VARCHAR(64),  -- SHA256 for tamper detection
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('audit_logs', 'timestamp');
CREATE INDEX idx_audit_rule ON audit_logs (rule_name, timestamp DESC);
CREATE INDEX idx_audit_event ON audit_logs (event_type, timestamp DESC);
```

### Testing Strategy

1. **Unit Tests (All Stories):**
   - Rule model validation (valid/invalid YAML)
   - Validator calculations (daily loss, drawdown)
   - Threshold logic (pass/warning/block)
   - Audit entry creation

2. **Integration Tests (Stories 3.5-3.7):**
   - Multi-layer validation pipeline
   - Redis state persistence
   - TimescaleDB audit logging
   - Emergency stop with Redis

3. **Scenario Tests:**
   - Replay historical violation scenarios
   - Verify zero false negatives (never allow violating orders)
   - Edge cases: exactly at threshold, rapid price moves

### CLI Commands

```bash
# Emergency stop commands (Story 3.7)
python -m src emergency-stop --reason "Manual halt for review"
python -m src clear-stop --confirm

# Compliance status query
python -m src compliance-status
# Output:
# Daily Loss: 3.5% of 5.0% (70% used) - OK
# Drawdown: 4.0% of 10.0% (40% used) - OK
# Trading Days: 3/4 completed
# Profit: 8.0% of 10.0% target (80%)
# Emergency Stop: INACTIVE
```

### Integration Points

| Component | Integration | Notes |
|-----------|-------------|-------|
| Strategy (Epic 4) | Calls `engine.validate_order()` before submission | Inject ComplianceEngine |
| Notification (Epic 2) | Publish to `alerts:risk` channel on warning/block | Redis pub/sub |
| TimescaleDB (Epic 2) | Audit logs via adapter | Use existing adapter |
| Redis (Epic 2) | State persistence via adapter | Use existing adapter |
| CLI (Epic 1) | Emergency stop commands | Extend Click commands |

---

## File Structure Summary

```
services/trading-engine/src/
├── config/
│   ├── ftmo_rules.yaml          # Default FTMO Phase 1 rules
│   ├── ftmo_phase2.yaml         # FTMO Phase 2 rules
│   └── ftuk_rules.yaml          # FTUK rules example
├── risk/
│   ├── __init__.py              # Export public API
│   ├── models.py                # Pydantic rule models
│   ├── loader.py                # YAML rule loader
│   ├── validators/
│   │   ├── __init__.py          # Export validators
│   │   ├── base.py              # ComplianceValidator ABC, ValidationResult
│   │   ├── daily_loss.py        # DailyLossValidator
│   │   ├── drawdown.py          # TotalDrawdownValidator
│   │   ├── trading_days.py      # TradingDaysValidator
│   │   └── profit_target.py     # ProfitTargetValidator
│   ├── engine.py                # ComplianceEngine, AccountState
│   ├── audit.py                 # AuditLogger
│   └── emergency.py             # EmergencyStopManager
tests/
├── unit/
│   ├── risk/
│   │   ├── test_models.py
│   │   ├── test_loader.py
│   │   ├── test_daily_loss.py
│   │   ├── test_drawdown.py
│   │   ├── test_trading_days.py
│   │   └── test_engine.py
├── integration/
│   └── risk/
│       ├── test_audit_logger.py
│       └── test_emergency_stop.py
```

---

_Tech-Spec generated via create-tech-spec workflow._
_Source: Epic 3 from docs/epics-trading-engine.md_
_Research: Context7 documentation for Nautilus Trader (risk management, portfolio), Pydantic (validators, ConfigDict), pydantic-settings (YAML loading)_
