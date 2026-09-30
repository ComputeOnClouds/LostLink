"""Task 11 unit tests for the claim state machine (pure, no AWS)."""

import pytest

from api import claim_state as cs


def test_valid_individual_transitions():
    assert cs.next_state("respond", cs.STATE_INFO_REQUESTED) == cs.STATE_SUBMITTED
    assert cs.next_state("cancel", cs.STATE_SUBMITTED) == cs.STATE_CANCELLED
    assert cs.next_state("cancel", cs.STATE_INFO_REQUESTED) == cs.STATE_CANCELLED


def test_valid_staff_transitions():
    assert cs.next_state("request_info", cs.STATE_SUBMITTED) == cs.STATE_INFO_REQUESTED
    assert cs.next_state("approve", cs.STATE_SUBMITTED) == cs.STATE_APPROVED
    assert cs.next_state("reject", cs.STATE_SUBMITTED) == cs.STATE_REJECTED
    assert cs.next_state("reject", cs.STATE_INFO_REQUESTED) == cs.STATE_REJECTED
    assert cs.next_state("reserve", cs.STATE_APPROVED) == cs.STATE_RESERVED
    assert cs.next_state("hand_over", cs.STATE_APPROVED) == cs.STATE_HANDED_OVER
    assert cs.next_state("hand_over", cs.STATE_RESERVED) == cs.STATE_HANDED_OVER


def test_invalid_transitions_raise():
    with pytest.raises(cs.InvalidTransition):
        cs.next_state("approve", cs.STATE_APPROVED)          # already approved
    with pytest.raises(cs.InvalidTransition):
        cs.next_state("reserve", cs.STATE_SUBMITTED)         # must approve first
    with pytest.raises(cs.InvalidTransition):
        cs.next_state("respond", cs.STATE_APPROVED)          # nothing to respond to
    with pytest.raises(cs.InvalidTransition):
        cs.next_state("cancel", cs.STATE_HANDED_OVER)        # terminal
    with pytest.raises(cs.InvalidTransition):
        cs.next_state("unknown_action", cs.STATE_SUBMITTED)


def test_terminal_states_have_no_outgoing():
    for terminal in cs.TERMINAL_STATES:
        for action in cs.TRANSITIONS:
            assert not cs.can_transition(action, terminal), (action, terminal)


def test_details_visibility_is_the_privacy_gate():
    # Hidden before approval.
    assert not cs.details_visible(cs.STATE_SUBMITTED)
    assert not cs.details_visible(cs.STATE_INFO_REQUESTED)
    assert not cs.details_visible(cs.STATE_REJECTED)
    assert not cs.details_visible(cs.STATE_CANCELLED)
    # Visible once approved onward.
    assert cs.details_visible(cs.STATE_APPROVED)
    assert cs.details_visible(cs.STATE_RESERVED)
    assert cs.details_visible(cs.STATE_HANDED_OVER)


def test_actor_for():
    assert cs.actor_for("approve") == "staff"
    assert cs.actor_for("cancel") == "individual"
    assert cs.actor_for("nope") is None
