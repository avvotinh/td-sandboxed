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

__all__ = [
    "AccountPhase",
    "AccountProduct",
    "CommissionProfile",
    "DrawdownMethod",
    "FirmProfile",
    "InstrumentClass",
    "ReportTemplate",
    "ResetAnchor",
    "ScalingPolicy",
    "SessionConfig",
    "SymbolPolicy",
]
