"""HTTP response helpers and request parsing for the API Gateway HTTP API payload v2."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .auth import AuthError

# Permissive CORS for the prototype SPA. Tighten allowed origin to the CloudFront
# domain in Task 6 if desired.
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
}


class _Encoder(json.JSONEncoder):
    def default(self, o: Any):
        if isinstance(o, Decimal):
            # Emit whole numbers as int, else float.
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


def respond(status: int, body: Any) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": json.dumps(body, cls=_Encoder),
    }


def error(status: int, message: str) -> dict:
    return respond(status, {"error": message})


def parse_body(event: dict) -> dict:
    raw = event.get("body")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise AuthError(400, "Request body is not valid JSON.")


def route_key(event: dict) -> str:
    """API Gateway HTTP API routeKey, e.g. "POST /reports"."""
    return event.get("routeKey", "")


def path_param(event: dict, name: str) -> str | None:
    return (event.get("pathParameters") or {}).get(name)
