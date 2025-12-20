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

from .loader import ConfigLoader, ConfigSyntaxError, ConfigValidationError

__all__ = ["ConfigLoader", "ConfigSyntaxError", "ConfigValidationError"]
