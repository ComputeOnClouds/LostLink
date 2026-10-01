#!/usr/bin/env python3
"""Verify the lost-report status lifecycle live:
  - a report that matches a found item ends as 'matched'
  - a report with no similar found item ends as 'no_match'
Both start at 'pending_match'. Self-cleans.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import boto3

API = os.environ["API_URL"].rstrip("/")
REGION = os.environ.get("REGION", "ap-southeast-2")
POOL = os.environ["USER_POOL_ID"]
CLIENT = os.environ["CLIENT_ID"]
items_t = boto3.resource("dynamodb", region_name=REGION).Table(os.environ["ITEMS_TABLE"])
matches_t = boto3.resource("dynamodb", region_name=REGION).Table(os.environ["MATCHES_TABLE"])

failures = []
created = []


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


def post(path, tok, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}{path}", data=data, method="POST")
    req.add_header("Authorization", tok); req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or "{}")


def status_of(item_id):
    return items_t.get_item(Key={"itemId": item_id}).get("Item", {}).get("status")


def wait_status(item_id, wanted, timeout=90):
    for _ in range(timeout // 3):
        if status_of(item_id) == wanted:
            return True
        time.sleep(3)
    return False


def main():
    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    user = token("user@lostlink.example", "User!Pass123", "Individual")

    print("1. a matching pair -> report ends 'matched'")
    f = post("/items", staff, {
        "description": "a bright orange Garmin GPS cycling computer with a cracked screen",
        "locationZone": "zone-velodrome", "eventTime": "2026-09-22T14:00:00+00:00"})
    created.append(("found", f["itemId"]))
    r = post("/reports", user, {
        "description": "lost my orange Garmin bike GPS computer, screen is cracked",
        "locationZone": "zone-velodrome", "eventTime": "2026-09-22T12:00:00+00:00"})
    lost_match = r["itemId"]; created.append(("lost", lost_match))
    # Note: the report is created as 'pending_match', but the async worker is fast and may
    # have already advanced it by the time we read — so we assert the END state, not the
    # transient initial one. (Initial pending_match is covered by the backend unit tests.)
    check(wait_status(lost_match, "matched"), f"report -> matched (got {status_of(lost_match)})")

    print("2. a non-matching report -> ends 'no_match'")
    r = post("/reports", user, {
        "description": "lost a hand-carved wooden chess set in a walnut box",
        "locationZone": "zone-common-room", "eventTime": "2026-09-21T10:00:00+00:00"})
    lost_none = r["itemId"]; created.append(("lost", lost_none))
    check(wait_status(lost_none, "no_match"), f"report -> no_match (got {status_of(lost_none)})")

    print("3. cleanup")
    for _t, iid in created:
        items_t.delete_item(Key={"itemId": iid})
    # delete any match rows for the matched report
    rows = matches_t.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("queryItemId").eq(lost_match)
    ).get("Items", [])
    for m in rows:
        matches_t.delete_item(Key={"queryItemId": m["queryItemId"], "candidateItemId": m["candidateItemId"]})
    print("  [OK  ] cleaned up")

    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED"); [print(" -", x) for x in failures]
        sys.exit(1)
    print("RESULT: report status lifecycle verified (pending_match -> matched / no_match)")


if __name__ == "__main__":
    main()
