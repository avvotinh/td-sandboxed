"""Accounts module - Multi-account management.

This module handles:
- Account lifecycle management
- Signal routing per account
- Account state persistence
- Per-account risk isolation

Exports:
- AccountConfig: Single trading account configuration
- AccountsConfig: Collection of account configurations
- AccountType: Account type enumeration (prop_firm, personal, demo)
- MT5Config: MT5 connection configuration
- SignalFilter: Signal filtering configuration
- AccountState: Account lifecycle state enumeration
- AccountManager: Account lifecycle manager
- SignalRouter: Routes signals to accounts based on symbol filters
- RiskState: Per-account risk metrics state
- AccountRiskManager: Per-account risk state manager
- RiskStateRegistry: Registry for per-account risk managers
- RiskIsolationService: Integration point for risk isolation
- RuleConfig: Configuration for a single risk rule
"""

from .account_manager import AccountManager
from .models import (
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)
from .risk_isolation import RiskIsolationService, RuleConfig
from .risk_manager import AccountRiskManager
from .risk_registry import RiskStateRegistry
from .risk_state import RiskState
from .signal_router import SignalRouter
from .state import AccountState

__all__ = [
    "AccountConfig",
    "AccountsConfig",
    "AccountManager",
    "AccountRiskManager",
    "AccountState",
    "AccountType",
    "MT5Config",
    "RiskIsolationService",
    "RiskState",
    "RiskStateRegistry",
    "RuleConfig",
    "SignalFilter",
    "SignalRouter",
]
