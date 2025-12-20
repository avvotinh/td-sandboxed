"""Tests for AccountState enum and state transitions."""

import pytest

from src.accounts.state import AccountState


class TestAccountStateEnum:
    """Tests for AccountState enum values."""

    def test_active_value(self):
        """Test ACTIVE state has correct value."""
        assert AccountState.ACTIVE.value == "active"

    def test_paused_value(self):
        """Test PAUSED state has correct value."""
        assert AccountState.PAUSED.value == "paused"

    def test_stopped_value(self):
        """Test STOPPED state has correct value."""
        assert AccountState.STOPPED.value == "stopped"

    def test_error_value(self):
        """Test ERROR state has correct value."""
        assert AccountState.ERROR.value == "error"

    def test_enum_is_str(self):
        """Test AccountState is a string enum."""
        assert isinstance(AccountState.ACTIVE, str)
        assert AccountState.ACTIVE == "active"

    def test_enum_from_string(self):
        """Test creating enum from string value."""
        assert AccountState("active") == AccountState.ACTIVE
        assert AccountState("paused") == AccountState.PAUSED
        assert AccountState("stopped") == AccountState.STOPPED
        assert AccountState("error") == AccountState.ERROR


class TestAccountStateTransitions:
    """Tests for state transition validation."""

    def test_valid_transitions_returns_dict(self):
        """Test valid_transitions returns a dictionary."""
        transitions = AccountState.valid_transitions()
        assert isinstance(transitions, dict)
        assert len(transitions) == 4  # All 4 states

    def test_active_to_paused_valid(self):
        """Test active → paused is valid."""
        assert AccountState.ACTIVE.can_transition_to(AccountState.PAUSED)

    def test_active_to_stopped_valid(self):
        """Test active → stopped is valid."""
        assert AccountState.ACTIVE.can_transition_to(AccountState.STOPPED)

    def test_active_to_error_valid(self):
        """Test active → error is valid."""
        assert AccountState.ACTIVE.can_transition_to(AccountState.ERROR)

    def test_active_to_active_invalid(self):
        """Test active → active is invalid (no self-transition)."""
        assert not AccountState.ACTIVE.can_transition_to(AccountState.ACTIVE)

    def test_paused_to_active_valid(self):
        """Test paused → active is valid (resume)."""
        assert AccountState.PAUSED.can_transition_to(AccountState.ACTIVE)

    def test_paused_to_stopped_valid(self):
        """Test paused → stopped is valid."""
        assert AccountState.PAUSED.can_transition_to(AccountState.STOPPED)

    def test_paused_to_error_valid(self):
        """Test paused → error is valid."""
        assert AccountState.PAUSED.can_transition_to(AccountState.ERROR)

    def test_paused_to_paused_invalid(self):
        """Test paused → paused is invalid."""
        assert not AccountState.PAUSED.can_transition_to(AccountState.PAUSED)

    def test_stopped_to_active_valid(self):
        """Test stopped → active is valid (restart)."""
        assert AccountState.STOPPED.can_transition_to(AccountState.ACTIVE)

    def test_stopped_to_paused_invalid(self):
        """Test stopped → paused is invalid."""
        assert not AccountState.STOPPED.can_transition_to(AccountState.PAUSED)

    def test_stopped_to_error_invalid(self):
        """Test stopped → error is invalid."""
        assert not AccountState.STOPPED.can_transition_to(AccountState.ERROR)

    def test_stopped_to_stopped_invalid(self):
        """Test stopped → stopped is invalid."""
        assert not AccountState.STOPPED.can_transition_to(AccountState.STOPPED)

    def test_error_to_stopped_valid(self):
        """Test error → stopped is valid (acknowledge)."""
        assert AccountState.ERROR.can_transition_to(AccountState.STOPPED)

    def test_error_to_active_invalid(self):
        """Test error → active is invalid (must go through stopped)."""
        assert not AccountState.ERROR.can_transition_to(AccountState.ACTIVE)

    def test_error_to_paused_invalid(self):
        """Test error → paused is invalid."""
        assert not AccountState.ERROR.can_transition_to(AccountState.PAUSED)

    def test_error_to_error_invalid(self):
        """Test error → error is invalid."""
        assert not AccountState.ERROR.can_transition_to(AccountState.ERROR)


class TestAccountStateEdgeCases:
    """Edge case tests for AccountState."""

    def test_invalid_string_raises_valueerror(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            AccountState("invalid")

    def test_case_sensitive(self):
        """Test state values are case-sensitive."""
        with pytest.raises(ValueError):
            AccountState("ACTIVE")

    def test_all_states_have_transitions(self):
        """Test all states have defined transitions."""
        transitions = AccountState.valid_transitions()
        for state in AccountState:
            assert state in transitions
