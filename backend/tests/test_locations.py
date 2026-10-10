"""Coordinate contracts, provider failures, matching and legacy compatibility."""

import copy
import json
import math
from decimal import Decimal
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from boto3.dynamodb.types import TypeSerializer

from api.auth import AuthError, Principal
from api.location_validation import parse_location, parse_radius
from api.onemap import OneMapClient, OneMapError, _request
from api import locations_handler
from pipeline.models import Item, ItemLocation, ItemType, VectorMap
from pipeline.location import distance_metres, within_search_radius
from pipeline.impl.ddb_mapping import ddb_to_item, item_to_ddb
from pipeline.impl.scorer import BlendedScorer, _spatial


LOCATION = {
    "name": "Central Library", "address": "NUS", "latitude": 1.2966,
    "longitude": 103.7736, "provider": "onemap", "selectionMethod": "search",
}


def item(kind=ItemType.LOST, **kwargs):
    return Item(item_id=kind.value + "-1", item_type=kind, organisation_id="org",
                owner_id="user", description="wallet", vectors=VectorMap(text=[1, 0]), **kwargs)


def test_location_roundtrip_is_ddb_serializable_and_legacy_safe():
    source = item(location=parse_location({**LOCATION, "note": "Level 2"}), search_radius_metres=1000)
    row = item_to_ddb(source)
    assert isinstance(row["location"]["latitude"], Decimal)
    TypeSerializer().serialize(row)  # No native float slips into the DynamoDB payload.
    assert ddb_to_item(row) == source
    old = item(location_zone="zone-library")
    assert ddb_to_item(item_to_ddb(old)).location is None


@pytest.mark.parametrize("patch", [
    {"latitude": None}, {"longitude": "103.8"}, {"latitude": True},
    {"latitude": math.nan}, {"longitude": math.inf}, {"latitude": 51},
    {"longitude": 1.3, "latitude": 103.8}, {"name": " "},
    {"provider": "google"}, {"selectionMethod": "invented"}, {"note": "a" * 501},
    {"name": 123},
])
def test_rejects_bad_locations(patch):
    with pytest.raises(AuthError) as exc:
        parse_location({**LOCATION, **patch})
    assert exc.value.status == 400


@pytest.mark.parametrize("radius", [True, 1000.0, "1000", -1, 0, 999])
def test_radius_validation(radius):
    with pytest.raises(AuthError):
        parse_radius(radius, parse_location(LOCATION))


def test_radius_needs_coordinates():
    with pytest.raises(AuthError):
        parse_radius(1000, None)
    assert parse_radius(None, None) is None


def test_haversine_known_distance_symmetry_and_antipodes():
    a = ItemLocation("a", 0, 0)
    b = ItemLocation("b", 0, 1)
    assert distance_metres(a, a) == 0
    assert distance_metres(a, b) == pytest.approx(111195.08, abs=.1)
    assert distance_metres(b, a) == distance_metres(a, b)
    assert distance_metres(a, ItemLocation("opposite", 0, 180)) == pytest.approx(math.pi * 6371008.8)


def test_spatial_uses_points_over_names_and_legacy_fallback():
    point = parse_location(LOCATION)
    a = item(location=point, location_zone="different-a")
    b = item(ItemType.FOUND, location=copy.copy(point), location_zone="different-b")
    b.location.name = "A different label"
    assert _spatial(a, b) == 1
    b.location.latitude += .005
    d = distance_metres(a.location, b.location)
    assert _spatial(a, b) == pytest.approx(.5 ** (d / 500))
    b.location = None
    assert _spatial(a, b) == .1
    a.location_zone = None
    assert _spatial(a, b) is None


def test_configurable_half_distance_and_bad_config():
    a = item(location=parse_location(LOCATION))
    b = item(ItemType.FOUND, location=parse_location({**LOCATION, "latitude": 1.3066}))
    assert BlendedScorer(1000).score(a, b, {"location": 1}).score > BlendedScorer(500).score(a, b, {"location": 1}).score
    for value in (0, -1, math.nan, math.inf):
        with pytest.raises(ValueError):
            BlendedScorer(value)


def test_radius_inclusive_and_applied_to_lost_side_in_both_orientations():
    lost = item(location=parse_location(LOCATION))
    found = item(ItemType.FOUND, location=parse_location({**LOCATION, "latitude": 1.3016}))
    lost.search_radius_metres = distance_metres(lost.location, found.location)
    assert within_search_radius(lost, found) and within_search_radius(found, lost)
    lost.search_radius_metres -= .001
    assert not within_search_radius(lost, found) and not within_search_radius(found, lost)
    found.location = None
    assert not within_search_radius(found, lost)
    lost.search_radius_metres = None
    assert within_search_radius(found, lost)


def row(**kwargs):
    return {"BUILDING": "Library", "ADDRESS": "NUS Library", "LATITUDE": "1.3", "LONGITUDE": "103.8", **kwargs}


def client_with(responses, clock=lambda: 100):
    calls = []
    def request(path, **kwargs):
        calls.append((path, kwargs))
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    return OneMapClient({"email": "example", "password": "test"}, request, clock), calls


TOKEN = {"access_token": "test-token", "expiry_timestamp": "10000"}


def test_onemap_normalizes_deduplicates_filters_and_caches():
    client, calls = client_with([TOKEN, {"results": [row(), row(), row(LATITUDE="nan"), row(LATITUDE="51"), row(BUILDING="NIL", SEARCHVAL="Park", LONGITUDE=None)]}])
    results = client.search("Library & NUS")
    assert len(results) == 1 and results[0]["name"] == "Library"
    assert results[0]["latitude"] == 1.3
    assert "searchVal=Library+%26+NUS" in calls[1][0]
    assert client.search("library & nus") == results
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [{"error": "Authentication token expired", "results": [row()]}, OneMapError(401)])
def test_onemap_refreshes_once_on_http_or_json_auth_error(failure):
    client, calls = client_with([TOKEN, failure, TOKEN, {"results": [row()]}])
    assert client.search("NUS")
    assert len(calls) == 4


def test_repeated_auth_failure_is_bounded_and_does_not_leak():
    client, calls = client_with([TOKEN, {"error": "invalid token SECRET"}, TOKEN, {"error": "invalid token SECRET"}])
    with pytest.raises(OneMapError) as exc:
        client.search("NUS")
    assert "SECRET" not in str(exc.value)
    assert len(calls) == 4


def test_throttling_does_not_retry_or_cache_errors():
    client, calls = client_with([TOKEN, OneMapError(429), {"results": []}])
    with pytest.raises(OneMapError) as exc:
        client.search("NUS")
    assert exc.value.status == 429
    assert client.search("NUS") == []
    assert len(calls) == 3


def test_token_and_search_cache_expire():
    now = [100]
    client, calls = client_with([TOKEN, {"results": []}, {"results": []}, {**TOKEN, "expiry_timestamp": "20000"}, {"results": []}], lambda: now[0])
    client.search("NUS")
    now[0] = 500
    client.search("NUS")
    now[0] = 10001
    client.search("NUS")
    assert len(calls) == 5


@pytest.mark.parametrize("failure", [TimeoutError(), URLError("SECRET"), HTTPError("url", 429, "SECRET", {}, None)])
def test_transport_errors_are_sanitized(monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr("api.onemap.urlopen", fail)
    with pytest.raises(OneMapError) as exc:
        _request("/api/common/elastic/search")
    assert "SECRET" not in str(exc.value)


def event(group="Individual", query="NUS"):
    return {"routeKey": "GET /locations/search", "queryStringParameters": {"q": query},
            "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u", "cognito:groups": group}}}}}


def test_search_route_auth_query_errors_and_throttling(monkeypatch):
    calls = []
    monkeypatch.setattr(locations_handler, "_client", SimpleNamespace(search=lambda q: calls.append(q) or []))
    assert locations_handler.handler({})["statusCode"] == 401
    assert locations_handler.handler(event("Unknown"))["statusCode"] == 403
    for q in ("a", " " * 3, "a" * 121):
        assert locations_handler.handler(event(query=q))["statusCode"] == 400
    assert calls == []
    for group in ("Individual", "Staff"):
        assert locations_handler.handler(event(group))["statusCode"] == 200
    def throttle(q):
        raise OneMapError(429)
    monkeypatch.setattr(locations_handler, "_client", SimpleNamespace(search=throttle))
    response = locations_handler.handler(event())
    assert response["statusCode"] == 429 and response["headers"]["Retry-After"] == "10"


@pytest.mark.parametrize("trigger", ["lost-1", "found-1"])
def test_worker_radius_filters_before_scoring_and_notifications(trigger):
    from test_worker_t8 import FakeRepo, _make_worker
    repo = FakeRepo()
    repo.save(item(location=parse_location(LOCATION), search_radius_metres=500))
    repo.save(item(ItemType.FOUND, location=parse_location({**LOCATION, "latitude": 1.32})))
    worker = _make_worker(repo, {})
    worker.handle({"itemId": trigger})
    assert repo.saved_matches == [] and worker.notifier.calls == []
    repo.items["found-1"].location = parse_location(LOCATION)
    worker.handle({"itemId": trigger})
    assert len(repo.saved_matches) == 1 and len(worker.notifier.calls) == 1


class ItemTable:
    def __init__(self):
        self.rows = {}

    def put_item(self, Item, **kwargs):
        self.rows[Item["itemId"]] = copy.deepcopy(Item)

    def get_item(self, Key):
        value = self.rows.get(Key["itemId"])
        return {"Item": copy.deepcopy(value)} if value else {}


@pytest.mark.parametrize("kind", ["lost", "found"])
def test_handlers_create_edit_roundtrip_and_rematch_only_points(monkeypatch, kind):
    from api import reports_handler, staff_handler
    handler = reports_handler if kind == "lost" else staff_handler
    principal = Principal("u", "u@example.com", ["Individual" if kind == "lost" else "Staff"], "org")
    table, jobs = ItemTable(), []
    monkeypatch.setattr(handler, "_items", lambda: table)
    monkeypatch.setattr(handler, "_enqueue_match", lambda *args: jobs.append(args))
    create = handler._create_report if kind == "lost" else handler._register_found
    edit = handler._edit_report if kind == "lost" else handler._update_item
    result = create(principal, {"description": "wallet", "location": LOCATION})
    assert result["statusCode"] == 201
    item_id = json.loads(result["body"])["itemId"]
    table.rows[item_id]["vecText"] = "[1, 0]"
    jobs.clear()
    result = edit(principal, item_id, {"location": {**LOCATION, "name": "New label", "note": "Level 2"}, "revision": 1})
    view = json.loads(result["body"])
    assert view["location"]["name"] == "New label" and view["rematching"] is False
    assert jobs == []
    result = edit(principal, item_id, {"location": {**LOCATION, "latitude": 1.3}, "revision": 2})
    assert json.loads(result["body"])["rematching"] is True
    assert len(jobs) == 1 and table.rows[item_id]["vecText"] == "[1, 0]"
    if kind == "lost":
        jobs.clear()
        result = edit(principal, item_id, {"searchRadiusMetres": 500, "revision": 3})
        assert json.loads(result["body"])["rematching"] is True and len(jobs) == 1
    else:
        assert edit(principal, item_id, {"searchRadiusMetres": 500})["statusCode"] == 400


def test_legacy_edit_preserves_zone_and_can_upgrade_to_point(monkeypatch):
    from api import reports_handler as handler
    principal = Principal("u", None, ["Individual"], None)
    table = ItemTable()
    table.rows["lost-1"] = item_to_ddb(item(location_zone="zone-library"))
    table.rows["lost-1"]["ownerId"] = "u"
    monkeypatch.setattr(handler, "_items", lambda: table)
    monkeypatch.setattr(handler, "_enqueue_match", lambda *args: None)
    assert handler._edit_report(principal, "lost-1", {"description": "a wallet"})["statusCode"] == 200
    result = handler._edit_report(principal, "lost-1", {"locationZone": None, "location": LOCATION})
    assert json.loads(result["body"])["locationZone"] is None
    assert table.rows["lost-1"]["location"]["latitude"] == Decimal(str(LOCATION["latitude"]))


def test_coordinates_remain_hidden_until_claim_approval(monkeypatch):
    from api import claims_handler as handler
    table = ItemTable()
    table.rows["found-1"] = item_to_ddb(item(ItemType.FOUND, location=parse_location(LOCATION)))
    monkeypatch.setattr(handler, "_items", lambda: table)
    claim = {"claimId": "c", "candidateItemId": "found-1", "state": "submitted"}
    assert handler._claim_view(claim)["item"] is None
    claim["state"] = "approved"
    assert handler._claim_view(claim)["item"]["location"]["name"] == LOCATION["name"]


def test_coordinate_fields_do_not_bypass_report_owner_or_staff_org(monkeypatch):
    from api import reports_handler, staff_handler
    table = ItemTable()
    table.rows["lost-1"] = item_to_ddb(item(location=parse_location(LOCATION)))
    table.rows["found-1"] = item_to_ddb(item(ItemType.FOUND, location=parse_location(LOCATION)))
    for handler, principal, item_id, edit in (
        (reports_handler, Principal("other", None, ["Individual"], None), "lost-1", reports_handler._edit_report),
        (staff_handler, Principal("staff", None, ["Staff"], "other-org"), "found-1", staff_handler._update_item),
    ):
        monkeypatch.setattr(handler, "_items", lambda: table)
        with pytest.raises(AuthError) as exc:
            edit(principal, item_id, {"location": LOCATION})
        assert exc.value.status == 403
