# Story 3.6: Per-Account Equity and Balance Tracking

Status: done

## Story

As a **trader**,
I want **to see each account's equity, balance, and drawdown independently**,
So that **I know the financial state of each account**.

## Acceptance Criteria

1. **AC1**: Given Account A has initial balance $100,000 and current equity $98,500, when I run `trading-engine accounts status ftmo-gold-001`, then I see formatted output showing Account ID, Name, Status, Balance, Equity, Daily P&L (amount and %), Max Drawdown %, and Peak Equity

2. **AC2**: Given Account B has different financials, when I view Account B's status, then I see Account B's metrics (not Account A's) - complete isolation

3. **AC3**: Given I run `trading-engine accounts list`, when the command executes, then I see a summary table with columns: ID, Name, Status, Balance, Daily P&L % for all accounts

4. **AC4**: Given equity updates occur on tick/position changes, when the system processes updates, then Balance, Equity, Daily P&L, Max Drawdown, and Peak Equity are all updated correctly per-account

5. **AC5**: Given an account's metrics are stored in Redis, when I query the status, then the CLI retrieves and formats data from `risk:{account_id}:state` hash

## Tasks / Subtasks

### Task 1: Create AccountMetrics Model (AC: 1, 2, 4)

- [x] 1.1: Create `src/accounts/metrics.py` with `AccountMetrics` dataclass
- [x] 1.2: Define fields: `balance: Decimal`, `equity: Decimal`, `daily_pnl: Decimal`, `daily_pnl_percent: Decimal`, `peak_equity: Decimal`, `max_drawdown_percent: Decimal`, `last_updated: datetime`
- [x] 1.3: Add `unrealized_pnl` computed property: `equity - balance`
- [x] 1.4: Add `format_currency(value: Decimal) -> str` method for display formatting
- [x] 1.5: Add `to_status_dict() -> dict` for CLI output formatting

### Task 2: Create AccountMetricsService (AC: 1, 2, 4, 5)

- [x] 2.1: Create `src/accounts/metrics_service.py` with `AccountMetricsService` class
- [x] 2.2: Constructor accepts `redis_manager: RedisStateManager`, `risk_registry: RiskStateRegistry`
- [x] 2.3: Implement `get_account_metrics(account_id: str) -> AccountMetrics | None`:
  - Load from `risk:{account_id}:state` Redis hash
  - Combine with account config for balance
  - Calculate derived metrics
- [x] 2.4: Implement `update_balance(account_id: str, balance: Decimal) -> None`:
  - Update balance field in Redis
  - Trigger equity recalculation
- [x] 2.5: Implement `update_equity_from_mt5(account_id: str, equity: Decimal) -> None`:
  - Update equity in RiskStateRegistry (leverages Story 3.5 infrastructure)
  - Update peak equity if new high
  - Recalculate drawdown
- [x] 2.6: Implement `get_all_account_metrics() -> dict[str, AccountMetrics]`:
  - Load metrics for all registered accounts
  - Return dictionary keyed by account_id

### Task 3: Extend RedisStateManager for Balance Storage (AC: 4, 5)

- [x] 3.1: Add `save_account_balance(account_id: str, balance: Decimal) -> None`
- [x] 3.2: Add `get_account_balance(account_id: str) -> Decimal | None`
- [x] 3.3: Use Redis key pattern: `account:{account_id}:balance`
- [x] 3.4: Add method to fetch all balance keys for summary

### Task 4: Implement CLI Status Command (AC: 1, 2)

- [x] 4.1: Add `accounts status <account_id>` command to CLI via `src/cli/accounts.py`
- [x] 4.2: Implement status output formatter matching expected format:
  ```
  Account: {account_id} ({account_name})
  Status: {status}
  Balance: ${balance:,.2f}
  Equity: ${equity:,.2f}
  Daily P&L: ${daily_pnl:+,.2f} ({daily_pnl_percent:+.1f}%)
  Max Drawdown: {max_drawdown:.1f}%
  Peak Equity: ${peak_equity:,.2f}
  ```
- [x] 4.3: Handle account not found with appropriate error message
- [x] 4.4: Add color coding: green for profit, red for loss (using Typer/Click)

### Task 5: Implement CLI List Command (AC: 3)

- [x] 5.1: Add `accounts list` command to CLI
- [x] 5.2: Implement table formatter with columns: ID, Name, Status, Balance, Daily P&L
- [x] 5.3: Use tabulate library for table formatting
- [x] 5.4: Sort accounts by status (active first), then by ID
- [x] 5.5: Show summary row with total balance across all accounts

### Task 5.5: Extend AccountManager (AC: 1, 3)

- [x] 5.5.1: Add `get_all_accounts() -> list[str]` method to AccountManager
- [x] 5.5.2: Add `get_account(account_id: str) -> AccountConfig | None` method if not exists

### Task 6: Integrate with MT5 Balance/Equity Updates (AC: 4)

- [x] 6.1: Add `on_mt5_balance_update(account_id: str, balance: Decimal, equity: Decimal)` handler
- [x] 6.2: Add integration point in `src/adapters/zmq_adapter.py`:
  - Add `_metrics_service: AccountMetricsService` to ZMQAdapter
  - Add `set_metrics_service(service: AccountMetricsService)` setter
  - Wire `on_account_info_message()` to call `_metrics_service.on_mt5_balance_update()`
- [x] 6.3: Ensure updates flow through AccountMetricsService
- [x] 6.4: Add debouncing for high-frequency updates (max 1 update per 100ms per account)

### Task 7: Unit Tests (AC: 1, 2, 3, 4, 5)

- [x] 7.1: Test `AccountMetrics` dataclass properties and formatting
- [x] 7.2: Test `AccountMetricsService.get_account_metrics()` returns correct data
- [x] 7.3: Test metrics isolation: Account A metrics don't affect Account B
- [x] 7.4: Test balance/equity updates propagate correctly
- [x] 7.5: Test CLI status command output format
- [x] 7.6: Test CLI list command table format
- [x] 7.7: Test edge cases: new account with no history, account with zero balance

### Task 8: Integration Tests (AC: 1, 2, 3)

- [x] 8.1: Test full flow: update balance → update equity → query status
- [x] 8.2: Test multi-account list with mixed statuses
- [x] 8.3: Test concurrent balance updates to different accounts

## Dev Notes

### Technical Stack

- **Python:** 3.11+ (required by NautilusTrader)
- **Redis:** 7.2+ for state storage (async via redis.asyncio)
- **Pydantic:** v2 for model validation (optional for dataclass)
- **Click:** CLI framework (already in use)
- **Decimal:** For precise financial calculations
- **Tabulate/Rich:** For CLI table formatting

### Key Architecture Patterns

**AccountMetrics Data Flow:**
```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ACCOUNT METRICS FLOW                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   MT5 Bridge                                                            │
│   +-- ZMQ Account Info Message                                          │
│   |   {"account_id": "ftmo-001", "balance": 100000, "equity": 98500}   │
│   |                                                                     │
│   ▼                                                                     │
│   AccountMetricsService                                                 │
│   +-- on_mt5_balance_update()                                           │
│   |   +-- Update balance in Redis: account:{id}:balance                │
│   |   +-- Call RiskRegistry.update_account_equity() (from 3.5)         │
│   |                                                                     │
│   ▼                                                                     │
│   RiskStateRegistry (from Story 3.5)                                    │
│   +-- Updates risk:{account_id}:state hash                             │
│   +-- Calculates drawdown, updates peak                                 │
│   |                                                                     │
│   ▼                                                                     │
│   CLI Query                                                             │
│   +-- AccountMetricsService.get_account_metrics()                      │
│   +-- Combines: balance + risk state → AccountMetrics                  │
│   +-- Formats and displays                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**AccountMetrics Model:**
```python
# src/accounts/metrics.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass
class AccountMetrics:
    """Per-account financial metrics for display.

    Combines balance (from MT5) with risk metrics (from RiskStateRegistry)
    to provide a complete financial picture of each account.

    IMPORTANT: All financial values use Decimal for precision.
    """

    account_id: str
    account_name: str
    status: str  # active, paused, stopped, error
    balance: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    daily_pnl_percent: Decimal = Decimal("0")
    peak_equity: Decimal = Decimal("0")
    max_drawdown_percent: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized P&L = Equity - Balance."""
        return self.equity - self.balance

    @staticmethod
    def format_currency(value: Decimal) -> str:
        """Format decimal as currency string.

        Args:
            value: Decimal value to format

        Returns:
            Formatted string like "$100,000.00" or "-$1,500.00"
        """
        if value < 0:
            return f"-${abs(value):,.2f}"
        return f"${value:,.2f}"

    @staticmethod
    def format_percent(value: Decimal, show_sign: bool = True) -> str:
        """Format decimal as percentage string.

        Args:
            value: Decimal value to format (e.g., -1.5 for -1.5%)
            show_sign: Whether to show +/- sign

        Returns:
            Formatted string like "+0.8%" or "-1.5%"
        """
        if show_sign:
            return f"{value:+.1f}%"
        return f"{value:.1f}%"

    def to_status_dict(self) -> dict[str, str]:
        """Format metrics for CLI status display.

        Returns:
            Dict with formatted string values for display
        """
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "status": self.status,
            "balance": self.format_currency(self.balance),
            "equity": self.format_currency(self.equity),
            "daily_pnl": f"{self.format_currency(self.daily_pnl)} ({self.format_percent(self.daily_pnl_percent)})",
            "max_drawdown": self.format_percent(self.max_drawdown_percent, show_sign=False),
            "peak_equity": self.format_currency(self.peak_equity),
        }

    def to_list_row(self) -> list[str]:
        """Format metrics for CLI list table row.

        Returns:
            List of formatted string values for table row
        """
        return [
            self.account_id,
            self.account_name,
            self.status,
            self.format_currency(self.balance),
            self.format_percent(self.daily_pnl_percent),
        ]
```

**AccountMetricsService:**
```python
# src/accounts/metrics_service.py
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from .metrics import AccountMetrics

if TYPE_CHECKING:
    from ..state.redis_state import RedisStateManager
    from .risk_registry import RiskStateRegistry
    from .account_manager import AccountManager

logger = logging.getLogger(__name__)


class AccountMetricsService:
    """Service for retrieving and updating account financial metrics.

    Combines data from multiple sources:
    - Balance: From MT5 via account:{id}:balance key
    - Risk metrics: From RiskStateRegistry (Story 3.5)
    - Account config: From AccountManager

    CRITICAL: All operations are per-account isolated.
    """

    def __init__(
        self,
        redis_manager: "RedisStateManager",
        risk_registry: "RiskStateRegistry",
        account_manager: "AccountManager",
    ) -> None:
        """Initialize metrics service.

        Args:
            redis_manager: Redis state manager for balance storage
            risk_registry: Risk state registry for risk metrics
            account_manager: Account manager for account configs
        """
        self._redis = redis_manager
        self._risk_registry = risk_registry
        self._account_manager = account_manager

    async def get_account_metrics(self, account_id: str) -> AccountMetrics | None:
        """Get complete metrics for a single account.

        Args:
            account_id: Account identifier

        Returns:
            AccountMetrics if account exists, None otherwise
        """
        # Get account config
        account_config = self._account_manager.get_account(account_id)
        if not account_config:
            logger.warning(f"Account not found: {account_id}")
            return None

        # Get balance from Redis
        balance = await self._redis.get_account_balance(account_id)
        if balance is None:
            balance = Decimal("0")

        # Get risk state from registry
        risk_state = self._risk_registry.get_risk_state(account_id)

        # Get account status
        status = await self._redis.get_account_status(account_id) or "unknown"

        # Build metrics combining all sources
        return AccountMetrics(
            account_id=account_id,
            account_name=account_config.name,
            status=status,
            balance=balance,
            equity=risk_state.current_equity if risk_state else balance,
            daily_pnl=risk_state.daily_pnl if risk_state else Decimal("0"),
            daily_pnl_percent=risk_state.daily_pnl_percent if risk_state else Decimal("0"),
            peak_equity=risk_state.peak_equity if risk_state else balance,
            max_drawdown_percent=risk_state.total_drawdown_percent if risk_state else Decimal("0"),
            last_updated=risk_state.last_updated if risk_state else None,
        )

    async def get_all_account_metrics(self) -> dict[str, AccountMetrics]:
        """Get metrics for all registered accounts.

        Returns:
            Dict mapping account_id to AccountMetrics
        """
        accounts = self._account_manager.get_all_accounts()
        metrics = {}

        for account_id in accounts:
            account_metrics = await self.get_account_metrics(account_id)
            if account_metrics:
                metrics[account_id] = account_metrics

        return metrics

    async def update_balance(self, account_id: str, balance: Decimal) -> None:
        """Update account balance from MT5.

        Args:
            account_id: Account identifier
            balance: New balance value
        """
        await self._redis.save_account_balance(account_id, balance)
        logger.debug(f"Updated balance for {account_id}: {balance}")

    async def on_mt5_balance_update(
        self,
        account_id: str,
        balance: Decimal,
        equity: Decimal,
    ) -> None:
        """Handle balance/equity update from MT5.

        Called when MT5 reports new account info.

        Args:
            account_id: Account identifier
            balance: Current balance
            equity: Current equity (balance + unrealized P&L)
        """
        # Update balance
        await self.update_balance(account_id, balance)

        # Update equity through risk registry (leverages Story 3.5)
        await self._risk_registry.update_account_equity(account_id, equity)

        logger.info(
            f"MT5 update for {account_id}: "
            f"balance={balance}, equity={equity}"
        )
```

**CLI Async Wrapper (Required for Click):**
```python
# Click does not natively support async functions.
# Use this wrapper pattern for async CLI commands.

import asyncio
from functools import wraps

def async_command(f):
    """Decorator to run async Click commands."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper
```

**CLI Commands Implementation:**
```python
# Add to src/cli/accounts.py (new file)

import asyncio
import click
from decimal import Decimal
from functools import wraps
from tabulate import tabulate

from ..accounts.metrics_service import AccountMetricsService


def async_command(f):
    """Decorator to run async Click commands."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper


@click.group()
def accounts():
    """Account management commands."""
    pass


@accounts.command()
@click.argument("account_id")
@click.pass_context
@async_command
async def status(ctx, account_id: str):
    """Show detailed status for a specific account.

    Example: trading-engine accounts status ftmo-gold-001
    """
    metrics_service: AccountMetricsService = ctx.obj["metrics_service"]
    metrics = await metrics_service.get_account_metrics(account_id)

    if not metrics:
        click.echo(click.style(f"Account not found: {account_id}", fg="red"))
        return

    # Format status output
    status_data = metrics.to_status_dict()

    click.echo(f"Account: {status_data['account_id']} ({status_data['account_name']})")
    click.echo(f"Status: {status_data['status']}")
    click.echo(f"Balance: {status_data['balance']}")
    click.echo(f"Equity: {status_data['equity']}")

    # Color-code P&L
    pnl_color = "green" if metrics.daily_pnl >= 0 else "red"
    click.echo(f"Daily P&L: " + click.style(status_data['daily_pnl'], fg=pnl_color))

    click.echo(f"Max Drawdown: {status_data['max_drawdown']}")
    click.echo(f"Peak Equity: {status_data['peak_equity']}")


@accounts.command(name="list")
@click.pass_context
@async_command
async def list_accounts(ctx):
    """List all accounts with summary metrics.

    Example: trading-engine accounts list
    """
    metrics_service: AccountMetricsService = ctx.obj["metrics_service"]
    all_metrics = await metrics_service.get_all_account_metrics()

    if not all_metrics:
        click.echo("No accounts configured.")
        return

    # Sort: active first, then by ID
    sorted_metrics = sorted(
        all_metrics.values(),
        key=lambda m: (0 if m.status == "active" else 1, m.account_id)
    )

    # Build table
    headers = ["ID", "Name", "Status", "Balance", "Daily P&L"]
    rows = [m.to_list_row() for m in sorted_metrics]

    click.echo(tabulate(rows, headers=headers, tablefmt="simple"))

    # Summary row
    total_balance = sum(m.balance for m in sorted_metrics)
    click.echo(f"\nTotal Balance: ${total_balance:,.2f}")
```

**AccountManager Extensions:**
```python
# Add to src/accounts/account_manager.py

    def get_all_accounts(self) -> list[str]:
        """Get all registered account IDs.

        Returns:
            List of account IDs.
        """
        return list(self._accounts.keys())

    def get_account(self, account_id: str) -> "AccountConfig | None":
        """Get account configuration by ID.

        Args:
            account_id: Account identifier.

        Returns:
            AccountConfig if found, None otherwise.
        """
        return self._accounts.get(account_id)
```

**RedisStateManager Extensions:**
```python
# Add to src/state/redis_state.py

    async def save_account_balance(self, account_id: str, balance: Decimal) -> None:
        """Save account balance to Redis.

        Key pattern: account:{account_id}:balance

        Args:
            account_id: Account identifier
            balance: Balance value
        """
        key = f"account:{account_id}:balance"
        await self.client.set(key, str(balance))

    async def get_account_balance(self, account_id: str) -> Decimal | None:
        """Get account balance from Redis.

        Args:
            account_id: Account identifier

        Returns:
            Decimal balance if found, None otherwise
        """
        key = f"account:{account_id}:balance"
        value = await self.client.get(key)
        if value is None:
            return None
        return Decimal(value)

    async def get_all_account_balances(self) -> dict[str, Decimal]:
        """Get balances for all accounts.

        Returns:
            Dict mapping account_id to balance
        """
        # Scan for all balance keys
        balances = {}
        async for key in self.client.scan_iter("account:*:balance"):
            # Extract account_id from key
            parts = key.split(":")
            if len(parts) == 3:
                account_id = parts[1]
                value = await self.client.get(key)
                if value:
                    balances[account_id] = Decimal(value)
        return balances
```

**MT5 ZMQ Adapter Integration:**
```python
# Add to src/adapters/zmq_adapter.py

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..accounts.metrics_service import AccountMetricsService


class ZMQAdapter:
    # ... existing code ...

    def __init__(self, ...):
        # ... existing init ...
        self._metrics_service: "AccountMetricsService | None" = None

    def set_metrics_service(self, service: "AccountMetricsService") -> None:
        """Register metrics service for balance/equity updates.

        Args:
            service: AccountMetricsService instance.
        """
        self._metrics_service = service

    async def on_account_info_message(self, message: dict) -> None:
        """Handle account info update from MT5.

        Message format from MT5 EA:
        {"type": "account_info", "account_id": "ftmo-001",
         "balance": 100000.00, "equity": 98500.00}
        """
        if self._metrics_service is None:
            return

        account_id = message["account_id"]
        balance = Decimal(str(message["balance"]))
        equity = Decimal(str(message["equity"]))

        await self._metrics_service.on_mt5_balance_update(
            account_id, balance, equity
        )
```

**Debouncing Implementation (add to AccountMetricsService):**
```python
# Add these to AccountMetricsService class

from asyncio import Lock
from datetime import datetime, timedelta, timezone

class AccountMetricsService:
    DEBOUNCE_MS = 100  # Minimum interval between updates per account

    def __init__(self, ...):
        # ... existing init ...
        self._last_update: dict[str, datetime] = {}
        self._update_lock = Lock()

    async def on_mt5_balance_update(
        self,
        account_id: str,
        balance: Decimal,
        equity: Decimal,
    ) -> None:
        """Handle balance/equity update from MT5 with debouncing."""
        # Check debounce
        async with self._update_lock:
            now = datetime.now(timezone.utc)
            last = self._last_update.get(account_id)
            if last:
                elapsed_ms = (now - last).total_seconds() * 1000
                if elapsed_ms < self.DEBOUNCE_MS:
                    return  # Skip - too soon
            self._last_update[account_id] = now

        # Proceed with update (outside lock for concurrency)
        await self.update_balance(account_id, balance)
        await self._risk_registry.update_account_equity(account_id, equity)
```

**Dependency Injection Wiring (add to engine initialization):**
```python
# Add to src/engine.py or main initialization code

async def initialize_services(redis_url: str, accounts_config: AccountsConfig):
    """Initialize all services with proper dependency injection."""
    # Create base services
    redis_manager = RedisStateManager(redis_url)
    await redis_manager.connect()

    # Create account manager
    account_manager = AccountManager(redis_manager)
    account_manager.load_accounts(accounts_config)

    # Create risk registry (from Story 3.5)
    risk_registry = RiskStateRegistry(redis_manager)
    account_manager.set_risk_registry(risk_registry)

    # Create metrics service (Story 3.6)
    metrics_service = AccountMetricsService(
        redis_manager=redis_manager,
        risk_registry=risk_registry,
        account_manager=account_manager,
    )

    # Wire to ZMQ adapter
    zmq_adapter = ZMQAdapter(...)
    zmq_adapter.set_metrics_service(metrics_service)

    return {
        "redis_manager": redis_manager,
        "account_manager": account_manager,
        "risk_registry": risk_registry,
        "metrics_service": metrics_service,
        "zmq_adapter": zmq_adapter,
    }
```

**CLI Entry Point Registration:**
```python
# Add to src/__main__.py

import click
from .cli.accounts import accounts as accounts_group

@click.group()
def cli():
    """Trading Engine CLI."""
    pass

# Register the accounts command group
cli.add_command(accounts_group)

if __name__ == "__main__":
    cli()
```

### File Locations

| File | Action | Purpose |
|------|--------|---------|
| `src/accounts/metrics.py` | CREATE | AccountMetrics dataclass |
| `src/accounts/metrics_service.py` | CREATE | AccountMetricsService class |
| `src/cli/accounts.py` | CREATE | CLI commands for accounts |
| `src/state/redis_state.py` | MODIFY | Add balance storage methods |
| `src/accounts/account_manager.py` | MODIFY | Add get_all_accounts(), get_account() |
| `src/adapters/zmq_adapter.py` | MODIFY | Add metrics service wiring |
| `src/__main__.py` | MODIFY | Register accounts CLI group |
| `src/accounts/__init__.py` | MODIFY | Export new classes |
| `tests/unit/test_metrics.py` | CREATE | Unit tests for AccountMetrics |
| `tests/unit/test_metrics_service.py` | CREATE | Unit tests for AccountMetricsService |
| `tests/integration/test_metrics_cli.py` | CREATE | Integration tests for CLI |

### Existing Code Analysis

**From Story 3.5 (Per-Account Risk Isolation):**
- `RiskStateRegistry` already tracks per-account: `daily_pnl`, `daily_pnl_percent`, `current_equity`, `peak_equity`, `total_drawdown_percent`
- `RiskState` dataclass already has `to_dict()` and `from_dict()` for Redis serialization
- Redis keys: `risk:{account_id}:state` (Hash type)
- **Key insight:** This story builds ON TOP of 3.5 infrastructure - we add balance tracking and CLI, not duplicate risk tracking

**From AccountManager (src/accounts/account_manager.py):**
- Has `_accounts: dict[str, AccountConfig]` for account configs
- Has `get_account(account_id)` method
- **Key insight:** Use existing account config for names, no duplication

**Existing Redis Key Patterns:**
```
# From Story 3.5:
risk:{account_id}:state → Hash (RiskState fields)

# New for this story:
account:{account_id}:balance → String (Decimal as string)
```

### Testing Requirements

**Framework:** pytest + pytest-asyncio | **Location:** `tests/unit/`, `tests/integration/`

```python
# tests/unit/test_metrics.py

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from src.accounts.metrics import AccountMetrics


class TestAccountMetrics:
    """Unit tests for AccountMetrics dataclass."""

    def test_unrealized_pnl_calculation(self):
        """Unrealized P&L = Equity - Balance."""
        metrics = AccountMetrics(
            account_id="test-001",
            account_name="Test Account",
            status="active",
            balance=Decimal("100000"),
            equity=Decimal("98500"),
        )

        assert metrics.unrealized_pnl == Decimal("-1500")

    def test_format_currency_positive(self):
        """Format positive currency correctly."""
        assert AccountMetrics.format_currency(Decimal("100000")) == "$100,000.00"
        assert AccountMetrics.format_currency(Decimal("1234.56")) == "$1,234.56"

    def test_format_currency_negative(self):
        """Format negative currency correctly."""
        assert AccountMetrics.format_currency(Decimal("-1500")) == "-$1,500.00"

    def test_format_percent_with_sign(self):
        """Format percentage with sign."""
        assert AccountMetrics.format_percent(Decimal("0.8")) == "+0.8%"
        assert AccountMetrics.format_percent(Decimal("-1.5")) == "-1.5%"

    def test_format_percent_without_sign(self):
        """Format percentage without sign."""
        assert AccountMetrics.format_percent(Decimal("1.5"), show_sign=False) == "1.5%"

    def test_to_status_dict(self):
        """Status dict contains all required fields."""
        metrics = AccountMetrics(
            account_id="ftmo-gold-001",
            account_name="FTMO Gold Challenge",
            status="active",
            balance=Decimal("100000"),
            equity=Decimal("98500"),
            daily_pnl=Decimal("-1500"),
            daily_pnl_percent=Decimal("-1.5"),
            peak_equity=Decimal("100000"),
            max_drawdown_percent=Decimal("1.5"),
        )

        status_dict = metrics.to_status_dict()

        assert status_dict["account_id"] == "ftmo-gold-001"
        assert status_dict["account_name"] == "FTMO Gold Challenge"
        assert status_dict["status"] == "active"
        assert status_dict["balance"] == "$100,000.00"
        assert status_dict["equity"] == "$98,500.00"
        assert "-$1,500.00" in status_dict["daily_pnl"]
        assert "-1.5%" in status_dict["daily_pnl"]

    def test_to_list_row(self):
        """List row contains columns in correct order."""
        metrics = AccountMetrics(
            account_id="ftmo-gold-001",
            account_name="FTMO Gold Challenge",
            status="active",
            balance=Decimal("100000"),
            daily_pnl_percent=Decimal("-1.5"),
        )

        row = metrics.to_list_row()

        assert row[0] == "ftmo-gold-001"
        assert row[1] == "FTMO Gold Challenge"
        assert row[2] == "active"
        assert row[3] == "$100,000.00"
        assert row[4] == "-1.5%"


class TestAccountMetricsEdgeCases:
    """Edge case tests for AccountMetrics."""

    def test_zero_balance(self):
        """Handle zero balance correctly."""
        metrics = AccountMetrics(
            account_id="new-account",
            account_name="New Account",
            status="active",
            balance=Decimal("0"),
            equity=Decimal("0"),
        )

        assert metrics.unrealized_pnl == Decimal("0")
        assert metrics.format_currency(metrics.balance) == "$0.00"

    def test_large_numbers(self):
        """Handle large account balances."""
        metrics = AccountMetrics(
            account_id="whale",
            account_name="Whale Account",
            status="active",
            balance=Decimal("10000000"),  # 10 million
            equity=Decimal("9999000"),
        )

        assert "$10,000,000.00" in metrics.format_currency(metrics.balance)
```

**Integration Test Example:**
```python
# tests/integration/test_metrics_cli.py

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.accounts.metrics_service import AccountMetricsService
from src.accounts.metrics import AccountMetrics


@pytest.mark.integration
class TestMetricsServiceIntegration:
    """Integration tests for AccountMetricsService."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies."""
        redis = MagicMock()
        redis.get_account_balance = AsyncMock(return_value=Decimal("100000"))
        redis.get_account_status = AsyncMock(return_value="active")

        risk_registry = MagicMock()
        risk_state = MagicMock()
        risk_state.current_equity = Decimal("98500")
        risk_state.daily_pnl = Decimal("-1500")
        risk_state.daily_pnl_percent = Decimal("-1.5")
        risk_state.peak_equity = Decimal("100000")
        risk_state.total_drawdown_percent = Decimal("1.5")
        risk_registry.get_risk_state = MagicMock(return_value=risk_state)

        account_manager = MagicMock()
        account_config = MagicMock()
        account_config.name = "FTMO Gold Challenge"
        account_manager.get_account = MagicMock(return_value=account_config)
        account_manager.get_all_accounts = MagicMock(return_value=["ftmo-gold-001"])

        return redis, risk_registry, account_manager

    @pytest.mark.asyncio
    async def test_get_account_metrics_combines_sources(self, mock_dependencies):
        """Metrics combines data from Redis, RiskRegistry, and AccountManager."""
        redis, risk_registry, account_manager = mock_dependencies

        service = AccountMetricsService(redis, risk_registry, account_manager)
        metrics = await service.get_account_metrics("ftmo-gold-001")

        assert metrics is not None
        assert metrics.account_id == "ftmo-gold-001"
        assert metrics.account_name == "FTMO Gold Challenge"
        assert metrics.balance == Decimal("100000")
        assert metrics.equity == Decimal("98500")
        assert metrics.daily_pnl == Decimal("-1500")

    @pytest.mark.asyncio
    async def test_account_not_found_returns_none(self, mock_dependencies):
        """Returns None for non-existent account."""
        redis, risk_registry, account_manager = mock_dependencies
        account_manager.get_account = MagicMock(return_value=None)

        service = AccountMetricsService(redis, risk_registry, account_manager)
        metrics = await service.get_account_metrics("nonexistent")

        assert metrics is None

    @pytest.mark.asyncio
    async def test_metrics_isolation(self, mock_dependencies):
        """Each account gets its own metrics (no cross-contamination)."""
        redis, risk_registry, account_manager = mock_dependencies

        # Setup two different accounts
        def get_account(account_id):
            configs = {
                "account-a": MagicMock(name="Account A"),
                "account-b": MagicMock(name="Account B"),
            }
            return configs.get(account_id)

        account_manager.get_account = get_account
        account_manager.get_all_accounts = MagicMock(return_value=["account-a", "account-b"])

        # Different balances per account
        async def get_balance(account_id):
            balances = {"account-a": Decimal("100000"), "account-b": Decimal("50000")}
            return balances.get(account_id)

        redis.get_account_balance = get_balance

        service = AccountMetricsService(redis, risk_registry, account_manager)

        metrics_a = await service.get_account_metrics("account-a")
        metrics_b = await service.get_account_metrics("account-b")

        assert metrics_a.balance == Decimal("100000")
        assert metrics_b.balance == Decimal("50000")
```

### Context from Previous Stories

**From Story 3.5 (Per-Account Risk Isolation) - CRITICAL DEPENDENCY:**
- RiskState dataclass already tracks: `daily_pnl`, `daily_pnl_percent`, `current_equity`, `peak_equity`, `total_drawdown_percent`
- RiskStateRegistry provides `get_risk_state(account_id)` method
- Redis key pattern: `risk:{account_id}:state`
- **DO NOT DUPLICATE:** This story adds balance tracking and CLI display, leveraging existing risk tracking

**From Story 3.2 (Account Manager Multi-Account Orchestration):**
- AccountManager has `_accounts` dict with account configs
- Each account config has `id`, `name`, `status`

**From Story 3.4 (Per-Account MT5 Connections):**
- MT5ConnectionManager provides per-account connections
- Account info updates come through ZMQ adapter
- **Key integration point:** Wire balance/equity updates to AccountMetricsService

### Latest Technical Documentation (Context7 Research 2025-12-30)

**Redis-py Async Operations:**
```python
# Async Redis hash operations for state management
import redis.asyncio as aioredis

r = await aioredis.from_url('redis://localhost:6379', decode_responses=True)

# Hash operations (for risk state)
await r.hset('risk:account-001:state', mapping=state.to_dict())
data = await r.hgetall('risk:account-001:state')

# String with TTL (for balance)
await r.set('account:account-001:balance', '100000')
value = await r.get('account:account-001:balance')

# Pipeline for batch operations
async with r.pipeline(transaction=True) as pipe:
    await pipe.set('key1', 'value1')
    await pipe.expire('key1', 3600)
    await pipe.execute()
```

**Pydantic Decimal Handling:**
```python
from decimal import Decimal
from pydantic.dataclasses import dataclass
from pydantic import Field

@dataclass
class FinancialModel:
    balance: Decimal = Field(ge=0)  # >= 0 constraint
    pnl: Decimal = Field(decimal_places=2)  # Max 2 decimal places

# Serialization preserves Decimal type in Python
model.model_dump()  # {'balance': Decimal('100000')}
```

### CLI Commands for Testing

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_metrics.py tests/unit/test_metrics_service.py -v

# Run integration tests
uv run pytest tests/integration/test_metrics_cli.py -v --cov=src/accounts

# Test CLI commands manually
uv run python -m src accounts status ftmo-gold-001
uv run python -m src accounts list

# Verify no regressions
uv run pytest tests/ -v && uv run ruff check src/
```

### Anti-Patterns

- **DO NOT** duplicate risk tracking - use RiskStateRegistry from Story 3.5
- **DO NOT** store balance in risk state hash - keep separate for clarity
- **DO NOT** calculate drawdown in this story - leverage existing RiskState.total_drawdown_percent
- **DO NOT** use floating point for financial values - always use Decimal
- **DO NOT** mix sync and async - keep all Redis operations async
- **DO NOT** skip the account config lookup - always verify account exists

### Redis Key Patterns

| Key Pattern | Type | Purpose | TTL |
|-------------|------|---------|-----|
| `account:{account_id}:balance` | String | Current MT5 balance | None |
| `risk:{account_id}:state` | Hash | Risk metrics (from 3.5) | 7 days |
| `account:{account_id}:status` | String | Account status | None |

### References

- [Source: docs/architecture.md#Multi-Account-Architecture] - Multi-account management patterns
- [Source: docs/architecture.md#Redis-Data-Structures] - Redis key patterns
- [Source: docs/epics.md#Story-3.6] - Story requirements and acceptance criteria
- [Source: docs/sprint-artifacts/3-5-per-account-risk-isolation.md] - Previous story implementation
- [Source: services/trading-engine/src/accounts/risk_registry.py] - RiskStateRegistry class
- [Source: services/trading-engine/src/accounts/risk_state.py] - RiskState dataclass
- [Source: Context7 redis-py 2025-12-30] - Async Redis operations
- [Source: Context7 Pydantic 2025-12-30] - Decimal field handling

## Dev Agent Record

### Context Reference

Story created via create-story workflow with:
- Epic 3 analysis from docs/epics.md
- Architecture analysis from docs/architecture.md
- Previous story 3.5 implementation patterns (CRITICAL DEPENDENCY)
- Existing codebase analysis (accounts/, state/)
- Context7 MCP research: redis-py async operations (2025-12-30)
- Context7 MCP research: Pydantic decimal handling (2025-12-30)
- Git history analysis: Recent Epic 3 story commits

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Story creation

### Completion Notes List

- This story BUILDS ON Story 3.5 infrastructure - DO NOT duplicate risk tracking
- AccountMetrics combines: balance (new) + risk state (existing) + account config (existing)
- CLI commands provide visibility into per-account financial state
- All financial calculations use Decimal for precision
- Redis operations are async (redis.asyncio module)
- Balance stored separately from risk state for clarity
- Isolation verified: Account A metrics don't leak to Account B

### Change Log (Code Review 2025-12-30)

| Change | Description |
|--------|-------------|
| CLI Framework | Used **Typer** instead of Click (Typer is built on Click but provides better typing support and cleaner syntax). This is an improvement over the original spec. |
| Async Pattern | Used `_run_async()` helper instead of `async_command` decorator pattern specified in Dev Notes. Both achieve same result. |
| Table Formatting | Chose **tabulate** library (lightweight) over rich (full-featured) for table formatting per Task 5.3 options. |
| CLI Entry Point | Registered via `src/cli/main.py` with `accounts_app` subcommand instead of `src/__main__.py` to follow existing CLI architecture. |
| Integration Tests | Added `tests/integration/test_metrics_cli.py` during code review (was missing). |
| Debounce Tests | Improved unit tests to use mocked datetime for deterministic timing tests. |

### File List

Files created:
- `services/trading-engine/src/accounts/metrics.py` - AccountMetrics dataclass
- `services/trading-engine/src/accounts/metrics_service.py` - AccountMetricsService class
- `services/trading-engine/src/cli/accounts.py` - CLI commands for accounts (using Typer)
- `services/trading-engine/tests/unit/test_metrics.py` - Unit tests for AccountMetrics
- `services/trading-engine/tests/unit/test_metrics_service.py` - Unit tests for service
- `services/trading-engine/tests/integration/test_metrics_cli.py` - Integration tests

Files modified:
- `services/trading-engine/src/state/redis_state.py` - Add balance storage methods
- `services/trading-engine/src/accounts/account_manager.py` - Add get_all_accounts(), get_account()
- `services/trading-engine/src/adapters/zmq_adapter.py` - Add metrics service wiring
- `services/trading-engine/src/cli/main.py` - Register accounts_app subcommand
- `services/trading-engine/src/accounts/__init__.py` - Export new classes
- `services/trading-engine/pyproject.toml` - Dependencies (tabulate)
- `services/trading-engine/tests/unit/test_cli_accounts.py` - Extended CLI tests

Dependencies used:
- `services/trading-engine/src/cli/constants.py` - STATUS_COLORS for CLI formatting (existing file)

---

## Definition of Done

- [x] `metrics.py` created with AccountMetrics dataclass
- [x] `metrics_service.py` created with AccountMetricsService class
- [x] `src/cli/accounts.py` created with CLI commands (using Typer with `_run_async` helper)
- [x] RedisStateManager extended with balance storage methods
- [x] AccountManager extended with `get_all_accounts()`, `get_account()` methods
- [x] ZMQ adapter wired to AccountMetricsService for MT5 updates
- [x] CLI `accounts status <id>` command implemented and working
- [x] CLI `accounts list` command implemented and working
- [x] CLI registered via `src/cli/main.py` and `accounts_app` subcommand
- [x] Status output matches expected format from acceptance criteria
- [x] List table displays all accounts with summary metrics
- [x] Balance updates from MT5 flow correctly with debouncing (100ms)
- [x] Equity updates leverage RiskStateRegistry (no duplication)
- [x] All financial values use Decimal (no floating point)
- [x] Unit tests cover AccountMetrics formatting (14 tests)
- [x] Unit tests cover AccountMetricsService methods (11 tests)
- [x] Integration tests verify CLI output (6 tests)
- [x] All existing tests still pass (825 passed)
- [x] Code passes: `uv run ruff check src/accounts/`

---

### Validation Notes (2025-12-30)

**Story validated via validate-create-story workflow. Applied improvements:**

| ID | Type | Description |
|----|------|-------------|
| C1 | Critical | Added `get_all_accounts()` and `get_account()` methods to AccountManager (Task 5.5) |
| C2 | Critical | Added specific MT5 ZMQ adapter integration code with file location |
| C3 | Critical | Added CLI async wrapper pattern for Click compatibility |
| E1 | Enhancement | Added dependency injection wiring example in `initialize_services()` |
| E2 | Enhancement | Added CLI entry point registration code for `src/__main__.py` |
| E3 | Enhancement | Added debouncing implementation with per-account lock and timestamp |
| O1 | Optimization | Updated File Locations table with all new/modified files |

**Validation Score:** Initial draft improved with all critical, enhancement, and optimization items
