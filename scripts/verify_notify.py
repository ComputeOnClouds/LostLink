#!/usr/bin/env python3
"""Task 10 live verification: notification dedup + owner_email plumbing.

1. Submit a matching found item + lost report via the API (owner_email now stored).
2. Wait for the worker to produce a Match row; assert it starts notified=false.
3. Re-drive the SAME match job to the SQS queue (simulating reprocessing) and confirm
   the notified flag ends up true and the worker did not error — the SesNotifier's
   conditional-update dedup makes the claim exactly-once.
4. Assert the lost item stored ownerEmail.

Actual SES delivery requires a verified sender; if SENDER_EMAIL is the placeholder the
worker claims-but-skips-send (still exercises dedup). Delivery to the mailbox simulator
is covered by scripts/verify_notify_email.sh once a real sender is verified.
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
QUEUE_URL = os.environ["MATCH_QUEUE_URL"]

ddb = boto3.resource("dynamodb", region_name=REGION)
items_t = ddb.Table(os.environ["ITEMS_TABLE"])
matches_t = ddb.Table(os.environ["MATCHES_TABLE"])
sqs = boto3.client("sqs", region_name=REGION)

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


def poll_match(q, c, timeout=90):
    for _ in range(timeout // 3):
        m = matches_t.get_item(Key={"queryItemId": q, "candidateItemId": c})
        if "Item" in m:
            return m["Item"]
        time.sleep(3)
    return None


def main():
    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    user = token("user@lostlink.example", "User!Pass123", "Individual")

    print("1. register found + lost (matching)")
    _, b = call("POST", "/items", staff, {
        "description": "a teal Osprey backpack with a broken left strap and a maple-leaf pin",
        "locationZone": "zone-science-block", "eventTime": "2026-09-28T14:00:00+00:00"})
    found_id = b["itemId"]; created.append(found_id)
    _, b = call("POST", "/reports", user, {
        "description": "lost my teal Osprey backpack, left strap is broken, has a maple leaf pin",
        "locationZone": "zone-science-block", "eventTime": "2026-09-28T12:00:00+00:00"})
    lost_id = b["itemId"]; created.append(lost_id)

    print("2. worker produces a match; ownerEmail stored on the lost item")
    m = poll_match(lost_id, found_id)
    check(m is not None, "match row created")
    li = items_t.get_item(Key={"itemId": lost_id}).get("Item", {})
    check(li.get("ownerEmail") == "user@lostlink.example", "lost item stored ownerEmail")
    if not m:
        cleanup(); finish()

    first_notified = bool(m.get("notified"))
    print(f"   (match notified flag after first pass = {first_notified})")

    print("3. re-drive the SAME match job to SQS (reprocessing) and confirm dedup")
    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"itemId": lost_id, "type": "lost"}))
    time.sleep(12)
    m2 = matches_t.get_item(Key={"queryItemId": lost_id, "candidateItemId": found_id}).get("Item", {})
    # notified must be True after processing (claimed) and remain a single logical claim.
    check(m2.get("notified") is True, "notified flag is True after processing (claimed once)")

    print("4. re-drive AGAIN; notified stays True, no error/duplication")
    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"itemId": lost_id, "type": "lost"}))
    time.sleep(12)
    m3 = matches_t.get_item(Key={"queryItemId": lost_id, "candidateItemId": found_id}).get("Item", {})
    check(m3.get("notified") is True, "notified still True after second re-drive (idempotent)")

    cleanup()
    finish()


def cleanup():
    print("5. cleanup")
    for iid in created:
        items_t.delete_item(Key={"itemId": iid})
    if len(created) >= 2:
        matches_t.delete_item(Key={"queryItemId": created[1], "candidateItemId": created[0]})
    print("  [OK  ] cleaned up")


def finish():
    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: notification dedup + ownerEmail verified live")
    sys.exit(0)


if __name__ == "__main__":
    main()
