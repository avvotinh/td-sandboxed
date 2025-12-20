"""Configuration loader for trading accounts.

This module provides:
- ConfigLoader: Loads and validates account configurations from YAML
- ConfigValidationError: User-friendly validation error wrapper
"""

import os
from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from ..accounts.models import AccountsConfig


class ConfigSyntaxError(Exception):
    """User-friendly YAML syntax error.

    Wraps yaml.YAMLError with clear, actionable messages.
    """

    def __init__(self, yaml_error: yaml.YAMLError, file_path: str):
        """Initialize with a YAML error.

        Args:
            yaml_error: The original YAML parsing error
            file_path: Path to the file that failed to parse
        """
        self.yaml_error = yaml_error
        self.file_path = file_path
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format YAML error into a readable message."""
        lines = [f"YAML syntax error in {self.file_path}:"]
        if hasattr(self.yaml_error, "problem_mark") and self.yaml_error.problem_mark:
            mark = self.yaml_error.problem_mark
            lines.append(f"  • Line {mark.line + 1}, Column {mark.column + 1}")
        if hasattr(self.yaml_error, "problem") and self.yaml_error.problem:
            lines.append(f"  • {self.yaml_error.problem}")
        lines.append("  • Check for missing colons, incorrect indentation, or invalid characters")
        return "\n".join(lines)

    def __str__(self) -> str:
        """Return formatted error message."""
        return self._format_message()


class ConfigValidationError(Exception):
    """User-friendly configuration validation error.

    Wraps Pydantic ValidationError with clear, actionable messages.
    Provides field-level details for easy debugging.

    Attributes:
        validation_error: The original Pydantic ValidationError
        errors: List of validation error details
    """

    def __init__(self, validation_error: ValidationError):
        """Initialize with a Pydantic ValidationError.

        Args:
            validation_error: The original validation error from Pydantic
        """
        self.validation_error = validation_error
        self.errors = validation_error.errors()
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format validation errors into a readable message."""
        lines = ["Configuration validation failed:"]
        for error in self.errors:
            location = " -> ".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            lines.append(f"  • {location}: {msg}")
        return "\n".join(lines)

    def __str__(self) -> str:
        """Return formatted error message."""
        return self._format_message()


class ConfigLoader:
    """Loads and validates account configurations from YAML files.

    Provides methods to:
    - Load and validate account configurations
    - Resolve MT5 passwords from environment variables

    Example:
        ```python
        loader = ConfigLoader("configs/accounts.yaml")
        config = loader.load()

        for account in config.accounts:
            password = loader.resolve_password(account.mt5.password_env)
        ```
    """

    def __init__(self, config_path: Union[Path, str]):
        """Initialize the config loader.

        Args:
            config_path: Path to the YAML configuration file
        """
        self.config_path = Path(config_path)

    def load(self) -> AccountsConfig:
        """Load and validate accounts configuration from YAML file.

        Returns:
            AccountsConfig: Validated configuration object

        Raises:
            FileNotFoundError: If the config file doesn't exist
            ValueError: If the config file is empty
            ConfigValidationError: If the config fails validation
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        try:
            with open(self.config_path) as f:
                raw_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigSyntaxError(e, str(self.config_path)) from e

        if raw_config is None:
            raise ValueError(f"Config file is empty: {self.config_path}")

        try:
            return AccountsConfig.model_validate(raw_config)
        except ValidationError as e:
            raise ConfigValidationError(e) from e

    def resolve_password(self, password_env: str) -> str:
        """Resolve MT5 password from environment variable.

        Args:
            password_env: Name of the environment variable containing the password

        Returns:
            str: The password value

        Raises:
            ValueError: If the environment variable is not set
        """
        password = os.getenv(password_env)
        if not password:
            raise ValueError(f"Environment variable not set: {password_env}")
        return password
