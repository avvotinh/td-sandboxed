"""Accounts module - Multi-account management.

This module handles:
- Account lifecycle management
- Signal routing per account
- Account state persistence

Exports:
- AccountConfig: Single trading account configuration
- AccountsConfig: Collection of account configurations
- AccountType: Account type enumeration (prop_firm, personal, demo)
- MT5Config: MT5 connection configuration
- SignalFilter: Signal filtering configuration
- AccountState: Account lifecycle state enumeration
- AccountManager: Account lifecycle manager
"""

from .account_manager import AccountManager
from .models import (
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)
from .state import AccountState

__all__ = [
    "AccountConfig",
    "AccountsConfig",
    "AccountManager",
    "AccountState",
    "AccountType",
    "MT5Config",
    "SignalFilter",
]
