"""Account state management - State enum and transitions."""

from enum import Enum


class AccountState(str, Enum):
    """Trading account lifecycle states."""

    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"

    @classmethod
    def valid_transitions(cls) -> dict["AccountState", list["AccountState"]]:
        """Return valid state transitions.

        State Machine:
            active → paused, stopped, error
            paused → active, stopped, error
            stopped → active (restart)
            error → stopped (acknowledge)
        """
        return {
            cls.ACTIVE: [cls.PAUSED, cls.STOPPED, cls.ERROR],
            cls.PAUSED: [cls.ACTIVE, cls.STOPPED, cls.ERROR],
            cls.STOPPED: [cls.ACTIVE],
            cls.ERROR: [cls.STOPPED],
        }

    def can_transition_to(self, target: "AccountState") -> bool:
        """Check if transition to target state is valid.

        Args:
            target: The target state to transition to.

        Returns:
            True if the transition is valid, False otherwise.
        """
        return target in self.valid_transitions().get(self, [])
