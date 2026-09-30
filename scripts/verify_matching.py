#!/usr/bin/env python3
"""Task 8 end-to-end live verification of the async matching pipeline.

As staff: register a found item (org-nus) describing a distinctive object.
As individual: submit a lost report describing the same object, same zone, near time.
Then poll: (1) both items get text vectors cached by the worker, (2) a Match row is
persisted (lost -> found) above threshold, oriented correctly.

Also submits a clearly-unrelated lost report and asserts it does NOT match the found
item (guards against everything matching everything).

Env from verify_matching.sh: API_URL, USER_POOL_ID, CLIENT_ID, ITEMS_TABLE,
MATCHES_TABLE, REGION.
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

failures = []
created = []


def check(cond, msg):
    print(f"  [{'OK  ' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


def aws(*args):
    out = subprocess.run(["aws", *args, "--region", REGION], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


def token(email, password, group, org=None):
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
        "--username", email, "--password", password, "--permanent")
    if org:
        aws("cognito-idp", "admin-update-user-attributes", "--user-pool-id", POOL,
            "--username", email, "--user-attributes", f"Name=custom:organisationId,Value={org}")
    aws("cognito-idp", "admin-add-user-to-group", "--user-pool-id", POOL,
        "--username", email, "--group-name", group)
    res = aws("cognito-idp", "initiate-auth", "--auth-flow", "USER_PASSWORD_AUTH",
              "--client-id", CLIENT, "--auth-parameters", f"USERNAME={email},PASSWORD={password}")
    return json.loads(res)["AuthenticationResult"]["IdToken"]


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


def poll_vector(item_id, timeout=90):
    for _ in range(timeout // 3):
        it = items_t.get_item(Key={"itemId": item_id}).get("Item", {})
        if it.get("vecText"):
            return True
        time.sleep(3)
    return False


def poll_match(query_id, cand_id, timeout=90):
    for _ in range(timeout // 3):
        m = matches_t.get_item(Key={"queryItemId": query_id, "candidateItemId": cand_id})
        if "Item" in m:
            return m["Item"]
        time.sleep(3)
    return None


def main():
    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    user = token("user@lostlink.example", "User!Pass123", "Individual")

    print("1. staff registers a distinctive found item")
    st, body = call("POST", "/items", staff, {
        "description": "a bright yellow Hydro Flask water bottle with a dented lid and a panda sticker",
        "locationZone": "zone-central-library",
        "eventTime": "2026-09-29T15:00:00+00:00",
    })
    check(st == 201, f"register found -> 201 (got {st})")
    found_id = body.get("itemId"); created.append(found_id)

    print("2. individual reports the same item lost (same zone, near time)")
    st, body = call("POST", "/reports", user, {
        "description": "lost my yellow Hydro Flask bottle, it has a panda sticker and a dent on the lid",
        "locationZone": "zone-central-library",
        "eventTime": "2026-09-29T11:00:00+00:00",
    })
    check(st == 201, f"report lost -> 201 (got {st})")
    lost_id = body.get("itemId"); created.append(lost_id)

    print("3. an unrelated lost report (should NOT match the bottle)")
    st, body = call("POST", "/reports", user, {
        "description": "lost a black umbrella with a wooden curved handle",
        "locationZone": "zone-bus-stop",
        "eventTime": "2026-09-20T08:00:00+00:00",
    })
    unrelated_id = body.get("itemId"); created.append(unrelated_id)

    print("4. worker caches text vectors on both matched items")
    check(poll_vector(found_id), f"found item {found_id} got a text vector")
    check(poll_vector(lost_id), f"lost item {lost_id} got a text vector")

    print("5. a Match row is persisted (lost -> found), oriented + above threshold")
    m = poll_match(lost_id, found_id)
    check(m is not None, "match row lost->found exists")
    if m:
        check(str(m.get("organisationId")) == "org-nus", "match organisationId = org-nus")
        check(float(m.get("score", 0)) >= 0.7, f"score >= threshold (score={m.get('score')})")
        check(m.get("notified") is False, "match starts notified=false (Task 10 dedup ready)")

    print("6. unrelated report does NOT match the bottle")
    # give the worker time; then assert no match row for the unrelated pair
    time.sleep(8)
    um = matches_t.get_item(Key={"queryItemId": unrelated_id, "candidateItemId": found_id})
    check("Item" not in um, "unrelated umbrella report has no match to the bottle")

    print("7. cleanup")
    for iid in created:
        if iid:
            items_t.delete_item(Key={"itemId": iid})
    if m:
        matches_t.delete_item(Key={"queryItemId": lost_id, "candidateItemId": found_id})
    print("  [OK  ] cleaned up")

    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: matching pipeline verified end-to-end")


if __name__ == "__main__":
    main()
