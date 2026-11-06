"""Authenticated place search for both lost and found forms."""

from .auth import principal_from_event, AuthError
from .responses import respond, error, route_key
from .onemap import OneMapClient, OneMapError

_client = OneMapClient()


def handler(event, _context=None):
    try:
        principal = principal_from_event(event)
        if not principal.is_individual and not principal.is_staff:
            raise AuthError(403, "An individual or staff account is required.")
        if route_key(event) != "GET /locations/search":
            return error(404, "No location route found.")
        query = (event.get("queryStringParameters") or {}).get("q", "")
        if not isinstance(query, str):
            return error(400, "Enter a place name of 2–120 characters.")
        query = " ".join(query.split())
        if not 2 <= len(query) <= 120:
            return error(400, "Enter a place name of 2–120 characters.")
        result = respond(200, {"suggestions": _client.search(query)})
        result["headers"]["Cache-Control"] = "private, no-store"
        return result
    except AuthError as exc:
        return error(exc.status, exc.message)
    except OneMapError as exc:
        result = error(exc.status, str(exc))
        if exc.status == 429:
            result["headers"]["Retry-After"] = "10"
        return result
    except Exception:
        # Search strings may contain personal addresses; don't log them or provider errors.
        return error(503, "Place search is unavailable. Choose on the map or try again.")
