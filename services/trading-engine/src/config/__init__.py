"""Config module - Configuration management.

This module handles:
- Environment-based configuration (pydantic-settings)
- Account configuration loading and validation
- Trading parameters

Exports:
- ConfigLoader: YAML configuration loader with validation
- ConfigSyntaxError: User-friendly YAML syntax error wrapper
- ConfigValidationError: User-friendly validation error wrapper
"""

from .firm_profile import (
    AccountPhase,
    AccountProduct,
    CommissionProfile,
    DrawdownMethod,
    FirmProfile,
    InstrumentClass,
    ReportTemplate,
    ResetAnchor,
    ScalingPolicy,
    SessionConfig,
    SymbolPolicy,
)
from .firm_registry import (
    FirmNotFoundError,
    FirmProfileLoadError,
    FirmRegistry,
    FirmRegistryError,
    FirmRegistryNotConfiguredError,
    PhaseNotFoundError,
    ProductNotFoundError,
)
from .loader import ConfigLoader, ConfigSyntaxError, ConfigValidationError

__all__ = [
    "AccountPhase",
    "AccountProduct",
    "CommissionProfile",
    "ConfigLoader",
    "ConfigSyntaxError",
    "ConfigValidationError",
    "DrawdownMethod",
    "FirmNotFoundError",
    "FirmProfile",
    "FirmProfileLoadError",
    "FirmRegistry",
    "FirmRegistryError",
    "FirmRegistryNotConfiguredError",
    "InstrumentClass",
    "PhaseNotFoundError",
    "ProductNotFoundError",
    "ReportTemplate",
    "ResetAnchor",
    "ScalingPolicy",
    "SessionConfig",
    "SymbolPolicy",
]
