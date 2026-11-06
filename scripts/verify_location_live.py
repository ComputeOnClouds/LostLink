#!/usr/bin/env python3
"""Live PR4 checks using existing demo users; soft-withdraws only its own QA data.

Requires APP_URL, USER_EMAIL, USER_PASSWORD, STAFF_EMAIL, STAFF_PASSWORD.
Does not provision users, reset passwords, or print authentication tokens.
"""
import json
import os
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3

REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
config = json.load(urllib.request.urlopen(os.environ["APP_URL"].rstrip("/") + "/config.json"))
API = config["apiUrl"].rstrip("/")
session = boto3.Session(region_name=REGION)
cognito = session.client("cognito-idp")
lambda_client = session.client("lambda")
items = session.resource("dynamodb").Table("LostLink-Items")
matches = session.resource("dynamodb").Table("LostLink-Matches")
created = []
claims = []
results = []


def check(ok, label):
    results.append({"passed": bool(ok), "test": label})
    print(("PASS " if ok else "FAIL ") + label, flush=True)
    if not ok:
        raise AssertionError(label)


def signin(prefix):
    return cognito.initiate_auth(ClientId=config["userPoolClientId"],
        AuthFlow="USER_PASSWORD_AUTH", AuthParameters={
            "USERNAME": os.environ[prefix + "_EMAIL"],
            "PASSWORD": os.environ[prefix + "_PASSWORD"],
        })["AuthenticationResult"]["IdToken"]


def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    request = urllib.request.Request(API + path, method=method, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or "{}")


def row(item_id):
    return items.get_item(Key={"itemId": item_id}, ConsistentRead=True)["Item"]


def active(lost_id, found_id):
    match = matches.get_item(Key={"queryItemId": lost_id,
        "candidateItemId": found_id}, ConsistentRead=True).get("Item", {})
    return bool(match) and match.get("active", True)


def wait_until(predicate, timeout=75):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(2)
    return False


def worker(item_id, kind):
    response = lambda_client.invoke(FunctionName="LostLink-MatchWorker",
        Payload=json.dumps({"Records": [{"messageId": uuid.uuid4().hex,
            "body": json.dumps({"itemId": item_id, "type": kind})}]}).encode())
    body = json.load(response["Payload"])
    check(not response.get("FunctionError") and not body.get("batchItemFailures"),
        "matching worker accepts " + kind + " job")


def point(latitude=1.2966):
    return {"name": "QA Central Library", "latitude": latitude,
        "longitude": 103.7736, "provider": "manual", "selectionMethod": "map"}


def create(kind, location, radius=None, legacy=False):
    path, token = ("/reports", user) if kind == "lost" else ("/items", staff)
    body = {"description": description, "eventTime": event_time}
    body.update({"locationZone": "zone-qa-location"} if legacy else {"location": location})
    if radius is not None:
        body["searchRadiusMetres"] = radius
    status, result = call("POST", path, token, body)
    check(status == 201, kind + " item saves through authenticated API")
    created.append((path, result["itemId"], token))
    return result["itemId"]


user = signin("USER")
staff = signin("STAFF")
description = "QA location " + uuid.uuid4().hex + " yellow Hydro Flask bottle with a panda sticker and dented lid"
event_time = datetime.now(timezone.utc).isoformat()
try:
    check(call("GET", "/locations/search?q=Central%20Library")[0] == 401,
        "location search rejects unauthenticated requests")
    status, search = call("GET", "/locations/search?q=Central%20Library", user)
    check(status == 200 and bool(search.get("suggestions")),
        "authenticated OneMap search returns live suggestions")
    print("INFO OneMap search HTTP " + str(status), flush=True)
    check(call("POST", "/reports", user, {"description": description,
        "location": point(103.7736)})[0] == 400, "API rejects out-of-area coordinates")
    check(call("POST", "/items", staff, {"description": description,
        "location": point(), "searchRadiusMetres": 500})[0] == 400,
        "staff cannot set a found-item search radius")

    near = create("found", point(1.2971))
    far = create("found", point(1.3166))
    lost = create("lost", point(), 500)
    check(wait_until(lambda: all(row(i).get("vecText") for i in (near, far, lost))),
        "SQS worker creates Titan embeddings asynchronously")
    worker(lost, "lost")
    check(active(lost, near), "lost-triggered job matches item inside 500 m")
    check(not active(lost, far), "lost-triggered job excludes item outside 500 m")
    worker(near, "found")
    worker(far, "found")
    check(active(lost, near) and not active(lost, far),
        "found-triggered jobs respect the lost report radius")

    status, saved = call("GET", "/reports/" + lost, user)
    check(status == 200 and saved["location"]["latitude"] == 1.2966
        and saved["searchRadiusMetres"] == 500, "lost location and radius survive reload")
    status, saved_found = call("GET", "/items/" + near, staff)
    check(status == 200 and saved_found["location"]["latitude"] == 1.2971,
        "staff location survives reload")
    check(isinstance(row(lost)["location"]["latitude"], Decimal),
        "DynamoDB stores coordinates as numbers")
    check(call("GET", "/items/" + near, user)[0] == 403,
        "individual cannot read staff inventory details")
    status, suggestions = call("GET", "/matches", user)
    ours = [m for m in suggestions.get("matches", []) if m["queryItemId"] == lost]
    check(status == 200 and ours and all(not any(k in m for k in
        ("location", "latitude", "longitude", "distanceMetres", "description", "photoKey"))
        for m in ours), "match suggestions hide found location and item details")
    status, claim = call("POST", "/claims", user, {"queryItemId": lost,
        "candidateItemId": near, "evidenceText": "QA location verification only"})
    check(status == 201, "QA ownership claim can be submitted")
    claims.append(claim["claimId"])
    status, view = call("GET", "/claims/" + claim["claimId"], user)
    check(status == 200 and view.get("item") is None,
        "unapproved claim hides found item details")

    before = row(lost)
    changed_label = {**saved["location"], "name": "QA renamed library", "note": "Level 2"}
    status, _ = call("PATCH", "/reports/" + lost, user,
        {"revision": int(before["revision"]), "location": changed_label})
    after = row(lost)
    check(status == 200 and after.get("vecText") == before.get("vecText")
        and after["status"] == before["status"], "label-only edit preserves embeddings and matching state")
    status, _ = call("PATCH", "/reports/" + lost, user,
        {"revision": int(after["revision"]), "searchRadiusMetres": 5000})
    check(status == 200, "radius edit saves")
    check(wait_until(lambda: active(lost, far)), "radius expansion triggers async rematching")
    check(row(lost).get("vecText") == before.get("vecText"),
        "radius edit preserves cached text embeddings")
    before_found = row(near)
    status, _ = call("PATCH", "/items/" + near, staff,
        {"revision": int(before_found["revision"]), "location": point(1.3566)})
    check(status == 200 and wait_until(lambda: not active(lost, near)),
        "found-coordinate edit removes match outside lost radius")
    check(row(near).get("vecText") == before_found.get("vecText"),
        "coordinate edit preserves found-item embeddings")

    legacy = create("lost", None, legacy=True)
    old = row(legacy)
    status, _ = call("PATCH", "/reports/" + legacy, user,
        {"revision": int(old["revision"]), "description": description + " legacy"})
    check(status == 200 and row(legacy)["locationZone"] == "zone-qa-location",
        "legacy report remains editable without losing its zone")
finally:
    for claim_id in claims:
        status, _ = call("POST", "/claims/" + claim_id + "/cancel", user, {})
        print("CLEANUP claim cancel HTTP " + str(status), flush=True)
    for path, item_id, token in reversed(created):
        status, _ = call("DELETE", path + "/" + item_id, token)
        print("CLEANUP QA item soft-withdraw HTTP " + str(status), flush=True)
    with open("/tmp/lostlink-pr4-live-results.json", "w") as output:
        json.dump({"results": results, "createdItemIds": [i for _, i, _ in created],
            "claimIds": claims}, output, indent=2)
    print("RESULT " + str(sum(r["passed"] for r in results)) + "/" + str(len(results)) + " checks passed", flush=True)
