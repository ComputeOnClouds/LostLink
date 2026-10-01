"""Cognito post-confirmation trigger: assign self-registered users to a role group.

Self sign-up is enabled on the user pool, but Cognito does not place a new user in any
group. Role in LostLink is carried by group membership (the ``cognito:groups`` claim),
so without this trigger a self-registered user would authenticate but fail every
Individual API call (``require_individual`` -> 403) and would not route to a portal.

Policy:
- Self-registered users are **Individuals** (lost-item reporters). They have no
  organisation, so we add them to the ``Individual`` group.
- Staff are provisioned by an administrator (``admin-create-user`` + an explicit
  ``custom:organisationId`` + ``admin-add-user-to-group Staff``). We therefore skip
  anyone who already carries an organisation id, so an admin-created staff member is
  never silently downgraded to Individual by this trigger.

The trigger must return the (unmodified) event. Any exception would fail the
confirmation, so group assignment is best-effort and logged; a user can still be fixed
by an admin if the call fails.
"""

from __future__ import annotations

import os

import boto3

GROUP_INDIVIDUAL = os.environ.get("INDIVIDUAL_GROUP", "Individual")

_cognito = boto3.client("cognito-idp")


def handler(event: dict, _context) -> dict:
    # Only act on the sign-up confirmation (ignore forgot-password confirmations etc.).
    trigger = event.get("triggerSource", "")
    if trigger not in ("PostConfirmation_ConfirmSignUp", "PostConfirmation_AutoConfirm"):
        return event

    user_pool_id = event.get("userPoolId")
    username = event.get("userName")
    attributes = (event.get("request") or {}).get("userAttributes") or {}

    # Staff are admin-created and already carry an organisation id — never touch them.
    if attributes.get("custom:organisationId"):
        print(f"{username}: has organisationId; leaving group membership to admin")
        return event

    if not user_pool_id or not username:
        print("post-confirmation event missing userPoolId/userName; skipping")
        return event

    try:
        _cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName=GROUP_INDIVIDUAL,
        )
        print(f"{username}: added to group {GROUP_INDIVIDUAL}")
    except Exception as e:  # noqa: BLE001 - never fail confirmation on a group error
        print(f"{username}: failed to add to {GROUP_INDIVIDUAL}: {e!r}")

    return event
