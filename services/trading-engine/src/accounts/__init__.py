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
"""

from .models import (
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)

__all__ = [
    "AccountConfig",
    "AccountsConfig",
    "AccountType",
    "MT5Config",
    "SignalFilter",
]
