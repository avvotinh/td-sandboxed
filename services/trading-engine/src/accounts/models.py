"""Account Pydantic models for trading account configuration.

This module defines the data models for:
- MT5 connection configuration
- Signal filtering rules
- Individual account configuration
- Collection of multiple accounts

All models use Pydantic v2 for validation and serialization.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class AccountType(str, Enum):
    """Trading account type enumeration."""

    PROP_FIRM = "prop_firm"
    PERSONAL = "personal"
    DEMO = "demo"


class MT5Config(BaseModel):
    """MT5 connection configuration.

    Attributes:
        server: MT5 broker server name
        login: MT5 account login number (must be positive)
        password_env: Environment variable name containing the MT5 password
    """

    server: str = Field(..., description="MT5 server name")
    login: int = Field(..., gt=0, description="MT5 login number")
    password_env: str = Field(..., description="Environment variable name for password")

    @field_validator("password_env")
    @classmethod
    def validate_password_env(cls, v: str) -> str:
        """Validate password_env is uppercase with underscores only."""
        if not v.isupper() or not v.replace("_", "").isalnum():
            raise ValueError("password_env must be uppercase with underscores only")
        return v


class SignalFilter(BaseModel):
    """Signal filtering configuration.

    Controls which trading signals are processed for an account.

    Attributes:
        symbols: List of allowed trading symbols (empty = all allowed)
        sessions: List of allowed trading sessions (empty = all allowed)
        max_spread_pips: Maximum allowed spread in pips (None = no limit)
    """

    symbols: list[str] = Field(default_factory=list, description="Allowed symbols")
    sessions: list[str] = Field(default_factory=list, description="Allowed sessions")
    max_spread_pips: Optional[float] = Field(
        default=None, ge=0, description="Maximum spread in pips"
    )


class AccountConfig(BaseModel):
    """Single trading account configuration.

    Represents a complete trading account setup including MT5 connection,
    strategy assignment, and compliance rules.

    Attributes:
        id: Unique account identifier (alphanumeric with dashes/underscores)
        name: Human-readable account name
        type: Account type (prop_firm, personal, demo)
        prop_firm: Prop firm preset name for compliance rules
        rules_file: Path to custom rules file (alternative to prop_firm)
        mt5: MT5 connection configuration
        strategy: Strategy name to execute on this account
        strategy_params: Strategy-specific parameters
        signal_filter: Signal filtering rules
        status: Account status (active, paused, stopped)
    """

    id: str = Field(..., min_length=1, description="Unique account identifier")
    name: str = Field(..., min_length=1, description="Human-readable name")
    type: AccountType = Field(..., description="Account type")
    prop_firm: Optional[str] = Field(default=None, description="Prop firm preset name")
    rules_file: Optional[str] = Field(default=None, description="Custom rules file path")
    mt5: MT5Config
    strategy: str = Field(..., min_length=1, description="Strategy name")
    strategy_params: dict[str, Any] = Field(default_factory=dict, description="Strategy parameters")
    signal_filter: SignalFilter = Field(default_factory=SignalFilter)
    status: str = Field(default="active", pattern="^(active|paused|stopped)$")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate account ID format (alphanumeric with dashes/underscores)."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("id must be alphanumeric with dashes/underscores only")
        return v

    @model_validator(mode="after")
    def validate_rules_source(self) -> "AccountConfig":
        """Validate that non-demo accounts have a rules source.

        Prop firm and personal accounts must specify either:
        - prop_firm: Name of a prop firm preset (e.g., "ftmo")
        - rules_file: Path to a custom rules configuration file

        Demo accounts are exempt from this requirement.
        """
        if self.type != AccountType.DEMO:
            if not self.prop_firm and not self.rules_file:
                raise ValueError(
                    f"Account '{self.id}' of type '{self.type.value}' must have "
                    "either 'prop_firm' or 'rules_file' specified"
                )
        return self


class AccountsConfig(BaseModel):
    """Root configuration containing all trading accounts.

    Attributes:
        accounts: List of account configurations
    """

    accounts: list[AccountConfig] = Field(default_factory=list)

    @field_validator("accounts")
    @classmethod
    def validate_unique_ids(cls, v: list[AccountConfig]) -> list[AccountConfig]:
        """Validate that all account IDs are unique."""
        ids = [acc.id for acc in v]
        if len(ids) != len(set(ids)):
            duplicates = [id for id in ids if ids.count(id) > 1]
            raise ValueError(f"Account IDs must be unique. Duplicates found: {set(duplicates)}")
        return v
