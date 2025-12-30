"""Loader for built-in prop firm rule presets.

Presets are stored in src/rules/presets/ directory as YAML files.
Each preset defines rules specific to a prop firm's requirements.

Example:
    >>> loader = RulePresetLoader()
    >>> loader.get_available_presets()
    ['ftmo', 'the5ers', 'wmt']
    >>> rules = loader.load_preset("ftmo")
    >>> len(rules)
    4
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .parser import RuleParser

if TYPE_CHECKING:
    from .base_rule import BaseRule

logger = logging.getLogger(__name__)


class PresetNotFoundError(Exception):
    """Raised when a rule preset is not found.

    This exception provides helpful information about available presets
    to guide users toward valid choices.

    Attributes:
        preset_name: The preset name that was not found.
        available_presets: List of valid preset names.
    """

    def __init__(self, preset_name: str, available_presets: list[str] | None = None):
        """Initialize PresetNotFoundError.

        Args:
            preset_name: The preset name that was not found.
            available_presets: Optional list of valid preset names.
        """
        self.preset_name = preset_name
        self.available_presets = available_presets or []

        message = f"Preset '{preset_name}' not found"
        if self.available_presets:
            available = ", ".join(sorted(self.available_presets))
            message += f". Available presets: {available}"

        super().__init__(message)


class RulePresetLoader:
    """Loader for built-in prop firm rule presets.

    Presets are stored in src/rules/presets/ directory as YAML files.
    Each preset defines rules specific to a prop firm's requirements.

    Loaded presets are cached since they are immutable - the same preset
    will always return the same rules during a session.

    Attributes:
        PRESETS_DIR: Path to presets directory.
        AVAILABLE_PRESETS: Registry of preset name to file mapping.
    """

    PRESETS_DIR = Path(__file__).parent / "presets"

    AVAILABLE_PRESETS: dict[str, str] = {
        "ftmo": "ftmo.yaml",
        "the5ers": "the5ers.yaml",
        "wmt": "wmt.yaml",
    }

    def __init__(self, presets_dir: Path | None = None):
        """Initialize preset loader.

        Args:
            presets_dir: Optional custom presets directory. Defaults to
                         src/rules/presets/ relative to this module.

        Note:
            The presets directory is created automatically if it doesn't exist.
            This allows the loader to be used before presets are created.
        """
        self._presets_dir = presets_dir or self.PRESETS_DIR
        self._parser = RuleParser()
        self._cache: dict[str, list["BaseRule"]] = {}

        # Create presets directory if it doesn't exist
        if not self._presets_dir.exists():
            logger.info(f"Creating presets directory: {self._presets_dir}")
            self._presets_dir.mkdir(parents=True, exist_ok=True)

    def load_preset(self, preset_name: str) -> list["BaseRule"]:
        """Load rules from a preset.

        Args:
            preset_name: Name of the preset (e.g., "ftmo"). Case-insensitive.

        Returns:
            List of instantiated rule objects.

        Raises:
            PresetNotFoundError: If preset doesn't exist in registry or file not found.
        """
        # Normalize name to lowercase
        preset_name = preset_name.lower()

        # Check cache first (presets are immutable)
        if preset_name in self._cache:
            logger.debug(f"Returning cached preset: {preset_name}")
            return self._cache[preset_name]

        # Validate preset exists in registry
        if preset_name not in self.AVAILABLE_PRESETS:
            raise PresetNotFoundError(
                preset_name,
                available_presets=list(self.AVAILABLE_PRESETS.keys()),
            )

        # Load preset file
        preset_file = self._presets_dir / self.AVAILABLE_PRESETS[preset_name]

        if not preset_file.exists():
            raise PresetNotFoundError(
                preset_name,
                available_presets=self._get_existing_presets(),
            )

        # Parse YAML safely
        with open(preset_file, "r", encoding="utf-8") as f:
            preset_data = yaml.safe_load(f)

        if preset_data is None:
            raise PresetNotFoundError(
                preset_name,
                available_presets=list(self.AVAILABLE_PRESETS.keys()),
            )

        # Parse rules using RuleParser
        rules = self._parser.parse_rules(preset_data)

        # Cache for future use (presets are immutable)
        self._cache[preset_name] = rules

        version = preset_data.get("version", "unknown")
        logger.info(
            f"Loaded {len(rules)} rules from preset '{preset_name}' "
            f"(version: {version})"
        )

        return rules

    def get_available_presets(self) -> list[str]:
        """Get list of available preset names.

        Returns:
            List of preset names from the registry.
        """
        return list(self.AVAILABLE_PRESETS.keys())

    def _get_existing_presets(self) -> list[str]:
        """Get list of presets that actually exist on disk.

        Returns:
            List of preset names with existing files.
        """
        existing = []
        for preset_name, filename in self.AVAILABLE_PRESETS.items():
            if (self._presets_dir / filename).exists():
                existing.append(preset_name)
        return existing

    def get_preset_info(self, preset_name: str) -> dict[str, str]:
        """Get metadata about a preset without loading all rules.

        Args:
            preset_name: Name of the preset. Case-insensitive.

        Returns:
            Dictionary with preset metadata (name, version, description).

        Raises:
            PresetNotFoundError: If preset doesn't exist.
        """
        preset_name = preset_name.lower()

        if preset_name not in self.AVAILABLE_PRESETS:
            raise PresetNotFoundError(
                preset_name,
                available_presets=list(self.AVAILABLE_PRESETS.keys()),
            )

        preset_file = self._presets_dir / self.AVAILABLE_PRESETS[preset_name]

        if not preset_file.exists():
            raise PresetNotFoundError(
                preset_name,
                available_presets=self._get_existing_presets(),
            )

        with open(preset_file, "r", encoding="utf-8") as f:
            preset_data = yaml.safe_load(f)

        return {
            "name": preset_data.get("name", preset_name),
            "version": preset_data.get("version", "unknown"),
            "description": preset_data.get("description", "No description"),
            "rule_count": len(preset_data.get("rules", [])),
        }

    def clear_cache(self) -> None:
        """Clear the preset cache.

        Useful for testing or when presets are updated during runtime.
        """
        self._cache.clear()
        logger.debug("Preset cache cleared")
