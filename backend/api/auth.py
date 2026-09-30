"""Authorisation helpers.

The API Gateway HTTP API Cognito JWT authorizer validates the token and passes the
claims into the Lambda event at
``event["requestContext"]["authorizer"]["jwt"]["claims"]``. We NEVER trust role or
organisation from the request body/query — they come only from these validated claims.
This is the privacy core: a staff user's organisation is read from the token, so they
cannot act on another org's data by tampering with the request.

See ARCHITECTURE.md section 1.1 and RATIONALE ADR-010.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

GROUP_INDIVIDUAL = "Individual"
GROUP_STAFF = "Staff"


class AuthError(Exception):
    """Raised when the caller is unauthenticated or not permitted."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Principal:
    """The authenticated caller, derived solely from validated JWT claims."""

    user_id: str  # Cognito `sub` — stable unique id
    email: Optional[str]
    groups: list[str]
    organisation_id: Optional[str]

    @property
    def is_staff(self) -> bool:
        return GROUP_STAFF in self.groups

    @property
    def is_individual(self) -> bool:
        return GROUP_INDIVIDUAL in self.groups

    def require_individual(self) -> None:
        if not self.is_individual:
            raise AuthError(403, "This action is for individual users.")

    def require_staff(self) -> None:
        if not self.is_staff:
            raise AuthError(403, "This action is for organisation staff.")
        if not self.organisation_id:
            raise AuthError(403, "Staff account is not bound to an organisation.")


def _claims(event: dict) -> dict:
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]
    except (KeyError, TypeError):
        raise AuthError(401, "Missing or invalid authentication.")


def _parse_groups(raw) -> list[str]:
    """`cognito:groups` may arrive as a list, a space/comma string, or "[a b]"."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [g for g in raw if g]
    s = str(raw).strip().strip("[]")
    return [g for g in s.replace(",", " ").split() if g]


def principal_from_event(event: dict) -> Principal:
    """Build the Principal from the validated authorizer claims."""
    claims = _claims(event)
    user_id = claims.get("sub")
    if not user_id:
        raise AuthError(401, "Token has no subject.")
    return Principal(
        user_id=user_id,
        email=claims.get("email"),
        groups=_parse_groups(claims.get("cognito:groups")),
        organisation_id=claims.get("custom:organisationId") or None,
    )
