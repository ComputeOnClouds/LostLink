#!/usr/bin/env python3
"""Task 11 integration test: individual claims workflow + privacy.

Flow:
  - staff registers a found item; individual reports the matching lost item.
  - wait for the worker to produce the match.
  - GET /matches: individual sees the suggestion but NOT the found item's description.
  - POST /claims: submit ownership evidence -> claim 'submitted'.
  - GET /claims + GET /claims/{id}: item details HIDDEN while submitted (privacy).
  - cannot claim against a report that isn't mine (403).
  - cancel the claim -> 'cancelled'; respond-after-terminal -> 409.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

import boto3

API = os.environ["API_URL"].rstrip("/")
REGION = os.environ.get("REGION", "ap-southeast-2")
POOL = os.environ["USER_POOL_ID"]
CLIENT = os.environ["CLIENT_ID"]
ddb = boto3.resource("dynamodb", region_name=REGION)
items_t = ddb.Table(os.environ["ITEMS_TABLE"])
matches_t = ddb.Table(os.environ["MATCHES_TABLE"])
claims_t = ddb.Table(os.environ["CLAIMS_TABLE"])

failures = []
created_items = []
created_claims = []


def check(c, m):
    print(f"  [{'OK  ' if c else 'FAIL'}] {m}")
    if not c:
        failures.append(m)


def aws(*a):
    o = subprocess.run(["aws", *a, "--region", REGION], capture_output=True, text=True)
    if o.returncode != 0:
        raise RuntimeError(o.stderr.strip())
    return o.stdout.strip()


def token(email, pw, group, org=None):
    attrs = [f"Name=email,Value={email}", "Name=email_verified,Value=true"]
    if org:
        attrs.append(f"Name=custom:organisationId,Value={org}")
    try:
        aws("cognito-idp", "admin-create-user", "--user-pool-id", POOL, "--username", email,
            "--message-action", "SUPPRESS", "--user-attributes", *attrs)
    except RuntimeError as e:
        if "UsernameExistsException" not in str(e):
            raise
    aws("cognito-idp", "admin-set-user-password", "--user-pool-id", POOL,
        "--username", email, "--password", pw, "--permanent")
    if org:
        aws("cognito-idp", "admin-update-user-attributes", "--user-pool-id", POOL,
            "--username", email, "--user-attributes", f"Name=custom:organisationId,Value={org}")
    aws("cognito-idp", "admin-add-user-to-group", "--user-pool-id", POOL,
        "--username", email, "--group-name", group)
    r = aws("cognito-idp", "initiate-auth", "--auth-flow", "USER_PASSWORD_AUTH",
            "--client-id", CLIENT, "--auth-parameters", f"USERNAME={email},PASSWORD={pw}")
    return json.loads(r)["AuthenticationResult"]["IdToken"]


def call(method, path, tok, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", tok)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def poll_match(q, timeout=90):
    for _ in range(timeout // 3):
        rows = matches_t.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("queryItemId").eq(q)
        ).get("Items", [])
        if rows:
            return rows[0]
        time.sleep(3)
    return None


SECRET = "a lime-green Fjallraven Kanken backpack with a broken zip and a NASA patch"


def main():
    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    user = token("user@lostlink.example", "User!Pass123", "Individual")
    other = token("user2@lostlink.example", "User2!Pass123", "Individual")

    print("1. staff registers a found item with a distinctive secret description")
    _, b = call("POST", "/items", staff, {
        "description": SECRET, "locationZone": "zone-lecture-hall-3",
        "eventTime": "2026-09-27T09:00:00+00:00"})
    found_id = b["itemId"]; created_items.append(found_id)
    _, b = call("POST", "/reports", user, {
        "description": "lost my lime green Kanken backpack, broken zip, has a NASA patch",
        "locationZone": "zone-lecture-hall-3", "eventTime": "2026-09-27T08:00:00+00:00"})
    lost_id = b["itemId"]; created_items.append(lost_id)

    print("2. wait for the worker to produce the match")
    m = poll_match(lost_id)
    check(m is not None, "match produced")
    if not m:
        cleanup(); finish()

    print("3. GET /matches shows the suggestion but HIDES the found item's description")
    st, body = call("GET", "/matches", user)
    check(st == 200, f"GET /matches -> 200 (got {st})")
    mine = [x for x in body.get("matches", []) if x["queryItemId"] == lost_id]
    check(len(mine) == 1, "my match suggestion is listed")
    blob = json.dumps(body)
    check(SECRET not in blob, "found item's secret description NOT exposed in /matches")
    check(mine and "score" in mine[0] and "organisationId" in mine[0], "suggestion has score + org only")

    print("4. cannot claim against a report that isn't mine (403)")
    st, _ = call("POST", "/claims", other, {
        "queryItemId": lost_id, "candidateItemId": found_id, "evidenceText": "mine!"})
    check(st == 403, f"other user claiming my report -> 403 (got {st})")

    print("5. submit a claim with ownership evidence")
    st, body = call("POST", "/claims", user, {
        "queryItemId": lost_id, "candidateItemId": found_id,
        "evidenceText": "I have the receipt and can describe the NASA patch position."})
    check(st == 201 and body.get("state") == "submitted", f"POST /claims -> 201 submitted (got {st})")
    claim_id = body.get("claimId"); created_claims.append(claim_id)

    print("6. validation: claim without evidence -> 400")
    st, _ = call("POST", "/claims", user, {"queryItemId": lost_id, "candidateItemId": found_id})
    check(st == 400, f"claim without evidence -> 400 (got {st})")

    print("7. GET /claims + GET /claims/{id}: item HIDDEN while submitted (privacy)")
    st, body = call("GET", "/claims", user)
    check(st == 200 and any(c["claimId"] == claim_id for c in body.get("claims", [])), "claim listed")
    st, body = call("GET", f"/claims/{claim_id}", user)
    check(st == 200, f"GET claim -> 200 (got {st})")
    check(body.get("item") is None, "found item details hidden while state=submitted")
    check(SECRET not in json.dumps(body), "secret description not leaked in claim view")

    print("8. respond is invalid from 'submitted' (nothing was requested) -> 409")
    st, _ = call("POST", f"/claims/{claim_id}/respond", user, {"message": "hello"})
    check(st == 409, f"respond from submitted -> 409 (got {st})")

    print("9. cancel the claim -> cancelled; respond after terminal -> 409")
    st, body = call("POST", f"/claims/{claim_id}/cancel", user, {})
    check(st == 200 and body.get("state") == "cancelled", f"cancel -> cancelled (got {st})")
    st, _ = call("POST", f"/claims/{claim_id}/respond", user, {"message": "again"})
    check(st == 409, f"respond after cancel -> 409 (got {st})")

    cleanup(); finish()


def cleanup():
    print("cleanup")
    for iid in created_items:
        items_t.delete_item(Key={"itemId": iid})
    if len(created_items) >= 2:
        matches_t.delete_item(Key={"queryItemId": created_items[1], "candidateItemId": created_items[0]})
    for cid in created_claims:
        if cid:
            claims_t.delete_item(Key={"claimId": cid})
    print("  [OK  ] cleaned up")


def finish():
    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: individual claims workflow + privacy verified live")
    sys.exit(0)


if __name__ == "__main__":
    main()
