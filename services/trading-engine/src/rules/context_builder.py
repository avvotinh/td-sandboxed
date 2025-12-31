"""Rule Context Builder - Builder for creating rule validation contexts.

This module provides the RuleContextBuilder class that constructs
validation contexts from account state and trading signals.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# Context keys documentation (for IDE support)
# Required: account_id, current_balance, current_equity
# Standard: signal, symbol, side, quantity, daily_pnl, daily_pnl_percent,
#           total_drawdown_percent, open_positions_count, total_exposure,
#           initial_balance, peak_balance, timestamp
# Rule-specific: account_balance, requested_lots, current_position_lots,
#               total_pnl_percent, trading_days_count


@dataclass
class RuleContextBuilder:
    """Builder for creating rule validation contexts.

    Signal type: Any object with `symbol`, `side`, `quantity` attributes (duck typing).
    The builder extracts these via getattr() with fallback to account_state.

    Example:
        >>> builder = RuleContextBuilder()
        >>> context = builder.build_validation_context(
        ...     account_id="ftmo-001",
        ...     signal=signal_obj,
        ...     account_state={"balance": 100000, "equity": 99500},
        ... )
    """

    _custom_fields: dict[str, Any] = field(default_factory=dict)

    def build_validation_context(
        self,
        account_id: str,
        signal: Any,
        account_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a complete validation context.

        Args:
            account_id: Account identifier.
            signal: Trading signal (any object with symbol/side/quantity attrs).
            account_state: Current account state (balance, equity, etc.).

        Returns:
            Context dictionary for rule validation.
        """
        # Get volume from signal (Order uses 'volume', signals use 'quantity')
        signal_volume = getattr(
            signal, "volume", getattr(signal, "quantity", account_state.get("quantity", 0.0))
        )

        context = {
            # Account identification
            "account_id": account_id,
            "timestamp": datetime.now(timezone.utc),
            # Signal information (duck typing - works with any signal type)
            "signal": signal,
            "symbol": getattr(signal, "symbol", account_state.get("symbol")),
            "side": getattr(signal, "side", account_state.get("side")),
            "quantity": signal_volume,
            # Account state
            "current_balance": account_state.get("balance", 0.0),
            "current_equity": account_state.get("equity", 0.0),
            "initial_balance": account_state.get("initial_balance", 0.0),
            "peak_balance": account_state.get("peak_balance", 0.0),
            # P&L metrics
            "daily_pnl": account_state.get("daily_pnl", 0.0),
            "daily_pnl_percent": account_state.get("daily_pnl_percent", 0.0),
            "total_drawdown_percent": account_state.get("total_drawdown_percent", 0.0),
            # Position info
            "open_positions_count": account_state.get("open_positions_count", 0),
            "total_exposure": account_state.get("total_exposure", 0.0),
            # Rule-specific fields (for rules that access context directly)
            # MaxPositionSizeRule uses these
            "account_balance": account_state.get("account_balance", account_state.get("balance", 0.0)),
            "requested_lots": account_state.get("requested_lots", signal_volume),
            "current_position_lots": account_state.get("current_position_lots", 0.0),
            # ProfitTargetRule, MinTradingDaysRule use these
            "total_pnl_percent": account_state.get("total_pnl_percent", 0.0),
            "trading_days_count": account_state.get("trading_days_count", 0),
        }

        # Add custom fields
        context.update(self._custom_fields)

        return context

    def add_custom_field(self, key: str, value: Any) -> "RuleContextBuilder":
        """Add a custom field to the context.

        Note: Custom fields persist across multiple build_validation_context() calls
        on the same builder instance. Use clear_custom_fields() to reset if needed.

        Args:
            key: Field name.
            value: Field value.

        Returns:
            Self for chaining.
        """
        self._custom_fields[key] = value
        return self

    def clear_custom_fields(self) -> "RuleContextBuilder":
        """Clear all custom fields from the builder.

        Use this when reusing a builder instance and you want to reset
        custom fields between context builds.

        Returns:
            Self for chaining.
        """
        self._custom_fields.clear()
        return self

    def validate_context(self, context: dict[str, Any]) -> bool:
        """Validate that context has required fields.

        Args:
            context: Context dictionary to validate.

        Returns:
            True if valid.

        Raises:
            ValueError: If required fields are missing.
        """
        required = ["account_id", "current_balance", "current_equity"]

        missing = [f for f in required if f not in context]
        if missing:
            raise ValueError(f"Context missing required fields: {missing}")

        return True
