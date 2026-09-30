"""Claim state machine (shared by individual Task 11 and staff Task 12 handlers).

A claim moves through explicit states with a fixed set of allowed transitions. Both the
individual and staff handlers validate transitions through here so no invalid state
change is possible from either side.

States:
    submitted      - claimant has submitted ownership evidence; awaiting staff review
    info_requested - staff asked for more info; claimant must respond (-> submitted)
    approved       - staff confirmed ownership; item details may now be revealed
    rejected       - staff rejected the claim (terminal)
    reserved       - approved item reserved for collection
    handed_over    - physical handover recorded; case complete (terminal)
    cancelled      - claimant withdrew the claim (terminal)

Individual-initiated transitions: submit (create), respond (info_requested->submitted),
cancel. Staff-initiated: request_info, approve, reject, reserve, hand_over.
"""

from __future__ import annotations

STATE_SUBMITTED = "submitted"
STATE_INFO_REQUESTED = "info_requested"
STATE_APPROVED = "approved"
STATE_REJECTED = "rejected"
STATE_RESERVED = "reserved"
STATE_HANDED_OVER = "handed_over"
STATE_CANCELLED = "cancelled"

TERMINAL_STATES = {STATE_REJECTED, STATE_HANDED_OVER, STATE_CANCELLED}

# action -> (allowed_from_states, resulting_state, actor)
TRANSITIONS: dict[str, tuple[set[str], str, str]] = {
    # individual
    "respond": ({STATE_INFO_REQUESTED}, STATE_SUBMITTED, "individual"),
    "cancel": ({STATE_SUBMITTED, STATE_INFO_REQUESTED}, STATE_CANCELLED, "individual"),
    # staff
    "request_info": ({STATE_SUBMITTED}, STATE_INFO_REQUESTED, "staff"),
    "approve": ({STATE_SUBMITTED}, STATE_APPROVED, "staff"),
    "reject": ({STATE_SUBMITTED, STATE_INFO_REQUESTED}, STATE_REJECTED, "staff"),
    "reserve": ({STATE_APPROVED}, STATE_RESERVED, "staff"),
    "hand_over": ({STATE_APPROVED, STATE_RESERVED}, STATE_HANDED_OVER, "staff"),
}


class InvalidTransition(Exception):
    pass


def can_transition(action: str, current_state: str) -> bool:
    spec = TRANSITIONS.get(action)
    return bool(spec and current_state in spec[0])


def next_state(action: str, current_state: str) -> str:
    """Return the resulting state for ``action`` from ``current_state``.

    Raises InvalidTransition if the action is unknown or not allowed from here.
    """
    spec = TRANSITIONS.get(action)
    if not spec:
        raise InvalidTransition(f"Unknown claim action: {action}")
    allowed_from, result, _actor = spec
    if current_state not in allowed_from:
        raise InvalidTransition(
            f"Cannot '{action}' from state '{current_state}'."
        )
    return result


def actor_for(action: str) -> str | None:
    spec = TRANSITIONS.get(action)
    return spec[2] if spec else None


def details_visible(state: str) -> bool:
    """Found-item details are revealed to the claimant only once approved onward.

    This is the privacy core: before approval the claimant sees only that a partner
    organisation may hold their item, never the item's description or photo.
    """
    return state in {STATE_APPROVED, STATE_RESERVED, STATE_HANDED_OVER}
