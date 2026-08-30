import pytest

from scout_email.common.enums import LeadState
from scout_email.common.errors import InvalidStateTransitionError
from scout_email.db.repositories import validate_lead_transition


def test_discovered_cannot_jump_to_researched():
    with pytest.raises(InvalidStateTransitionError):
        validate_lead_transition(LeadState.DISCOVERED, LeadState.RESEARCHED)


def test_research_retry_path_is_explicitly_allowed():
    validate_lead_transition(LeadState.RESEARCHING, LeadState.RESEARCH_PENDING)


def test_terminal_state_has_no_outgoing_transition():
    with pytest.raises(InvalidStateTransitionError):
        validate_lead_transition(LeadState.SKIPPED, LeadState.QUALIFIED)
