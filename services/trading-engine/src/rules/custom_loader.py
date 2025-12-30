"""Loader for custom rule files.

Loads rules from user-defined YAML files, supporting both absolute paths
and paths relative to the configs directory.

Example:
    >>> loader = CustomRuleLoader()
    >>> rules = loader.load_custom_rules("my_rules.yaml")  # From configs/
    >>> rules = loader.load_custom_rules("/absolute/path/rules.yaml")
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .parser import RuleParser

if TYPE_CHECKING:
    from .base_rule import BaseRule

logger = logging.getLogger(__name__)


class RulesFileNotFoundError(Exception):
    """Raised when custom rules file is not found.

    Provides the full path that was checked to help users locate
    where the file should be placed.

    Attributes:
        rules_file: Original file path provided.
        resolved_path: Full resolved path that was checked.
    """

    def __init__(self, rules_file: str, resolved_path: Path):
        """Initialize RulesFileNotFoundError.

        Args:
            rules_file: Original file path provided by user.
            resolved_path: Full resolved path that was checked.
        """
        self.rules_file = rules_file
        self.resolved_path = resolved_path

        super().__init__(f"Custom rules file not found: {resolved_path}")


class RulesFileInvalidError(Exception):
    """Raised when custom rules file is invalid.

    Attributes:
        rules_file: File path that failed to load.
        reason: Description of why the file is invalid.
    """

    def __init__(self, rules_file: str, reason: str):
        """Initialize RulesFileInvalidError.

        Args:
            rules_file: File path that failed to load.
            reason: Description of why the file is invalid.
        """
        self.rules_file = rules_file
        self.reason = reason

        super().__init__(f"Invalid rules file '{rules_file}': {reason}")


class CustomRuleLoader:
    """Loader for custom rule files.

    Loads rules from user-defined YAML files, supporting both
    absolute paths and paths relative to the configs directory.

    Custom rules allow users to define their own trading rules
    beyond the built-in prop firm presets.

    Attributes:
        config_dir: Base directory for relative paths.
    """

    def __init__(self, config_dir: Path | str | None = None):
        """Initialize custom rule loader.

        Args:
            config_dir: Base directory for relative paths.
                        Defaults to project configs/ directory.
        """
        self._parser = RuleParser()

        if config_dir is None:
            # Default to configs/ relative to the trading-engine service
            # This assumes the working directory is services/trading-engine/
            self._config_dir = Path("configs")
        elif isinstance(config_dir, str):
            self._config_dir = Path(config_dir)
        else:
            self._config_dir = config_dir

    @property
    def config_dir(self) -> Path:
        """Get the configuration directory."""
        return self._config_dir

    def load_custom_rules(self, rules_file: str) -> list["BaseRule"]:
        """Load rules from a custom YAML file.

        Args:
            rules_file: Path to custom rules file.
                        - Absolute path: Used directly
                        - Relative path: Resolved relative to config_dir

        Returns:
            List of instantiated rule objects.

        Raises:
            RulesFileNotFoundError: If file doesn't exist.
            RulesFileInvalidError: If file cannot be parsed.
        """
        # Resolve path
        path = self._resolve_path(rules_file)

        if not path.exists():
            raise RulesFileNotFoundError(rules_file, path)

        if not path.is_file():
            raise RulesFileNotFoundError(rules_file, path)

        # Load and parse YAML
        try:
            with open(path, "r", encoding="utf-8") as f:
                rules_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise RulesFileInvalidError(rules_file, f"YAML parsing error: {e}") from e

        if rules_data is None:
            raise RulesFileInvalidError(rules_file, "File is empty")

        if not isinstance(rules_data, dict):
            raise RulesFileInvalidError(
                rules_file,
                f"Expected dictionary at root, got {type(rules_data).__name__}",
            )

        # Parse rules using RuleParser
        try:
            rules = self._parser.parse_rules(rules_data)
        except Exception as e:
            raise RulesFileInvalidError(rules_file, str(e)) from e

        name = rules_data.get("name", "unknown")
        logger.info(
            f"Loaded {len(rules)} custom rules from '{path}' (name: {name})"
        )

        return rules

    def _resolve_path(self, rules_file: str) -> Path:
        """Resolve a rules file path.

        Args:
            rules_file: Path to rules file (absolute or relative).

        Returns:
            Resolved absolute path.
        """
        path = Path(rules_file)

        if path.is_absolute():
            return path.resolve()

        # Relative path - resolve against config_dir
        return (self._config_dir / path).resolve()

    def validate_rules_file(self, rules_file: str) -> dict[str, str | int]:
        """Validate a rules file without fully loading it.

        Useful for checking if a rules file is valid before using it.

        Args:
            rules_file: Path to custom rules file.

        Returns:
            Dictionary with file metadata and validation status.

        Raises:
            RulesFileNotFoundError: If file doesn't exist.
            RulesFileInvalidError: If file cannot be parsed.
        """
        path = self._resolve_path(rules_file)

        if not path.exists():
            raise RulesFileNotFoundError(rules_file, path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                rules_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise RulesFileInvalidError(rules_file, f"YAML parsing error: {e}") from e

        if rules_data is None:
            raise RulesFileInvalidError(rules_file, "File is empty")

        if "rules" not in rules_data:
            raise RulesFileInvalidError(rules_file, "Missing 'rules' key")

        return {
            "path": str(path),
            "name": rules_data.get("name", "unknown"),
            "version": rules_data.get("version", "unknown"),
            "description": rules_data.get("description", "No description"),
            "rule_count": len(rules_data.get("rules", [])),
            "valid": True,
        }
