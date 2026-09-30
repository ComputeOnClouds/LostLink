#!/usr/bin/env python3
"""Task 10 REAL email delivery test (needs a verified SES sender AND recipient).

Creates a demo individual user whose email is RECIPIENT_EMAIL (must be SES-verified in
sandbox), files a matching found+lost pair, waits for the worker, and confirms SES
actually accepted+sent the match email (SentLast24Hours increments; match notified=true).
An email should arrive in that inbox.

Env (from verify_email_live.sh): API_URL, USER_POOL_ID, CLIENT_ID, ITEMS_TABLE,
MATCHES_TABLE, REGION, RECIPIENT_EMAIL.
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
RECIPIENT = os.environ["RECIPIENT_EMAIL"]
ddb = boto3.resource("dynamodb", region_name=REGION)
items_t = ddb.Table(os.environ["ITEMS_TABLE"])
matches_t = ddb.Table(os.environ["MATCHES_TABLE"])
ses = boto3.client("sesv2", region_name=REGION)

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
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read() or "{}")


def sent_count():
    return float(ses.get_account()["SendQuota"]["SentLast24Hours"])


def _worker_logged_send(lost_id, found_id, timeout=60):
    logs = boto3.client("logs", region_name=REGION)
    group = "/aws/lambda/LostLink-MatchWorker"
    needle = f"emailed"
    start = int((time.time() - 600) * 1000)
    for _ in range(timeout // 5):
        try:
            resp = logs.filter_log_events(
                logGroupName=group, startTime=start,
                filterPattern='"[notify] emailed"',
            )
            for e in resp.get("events", []):
                if lost_id in e["message"] and found_id in e["message"]:
                    return True
        except Exception as e:  # noqa: BLE001
            print(f"  (log check error: {e!r})")
        time.sleep(5)
    return False


def poll_match(q, timeout=90):
    for _ in range(timeout // 3):
        rows = matches_t.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("queryItemId").eq(q)
        ).get("Items", [])
        if rows:
            return rows[0]
        time.sleep(3)
    return None


def main():
    print(f"Recipient (must be SES-verified): {RECIPIENT}")
    before = sent_count()
    print(f"SES SentLast24Hours before: {before}")

    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    demo_pw = "Demo!Pass123"
    # Demo individual whose email is the verified recipient (Cognito username = email).
    user = token(RECIPIENT, demo_pw, "Individual")

    print("register found + report matching lost as the demo user")
    _, b = call("POST", "/items", staff, {
        "description": "a purple Anker power bank with a frayed usb-c cable and a star sticker",
        "locationZone": "zone-library", "eventTime": "2026-09-25T14:00:00+00:00"})
    found = b["itemId"]; created.append(found)
    _, b = call("POST", "/reports", user, {
        "description": "lost my purple Anker power bank, frayed usb-c cable, star sticker",
        "locationZone": "zone-library", "eventTime": "2026-09-25T12:00:00+00:00"})
    lost = b["itemId"]; created.append(lost)

    print("wait for match + email send")
    m = poll_match(lost)
    check(m is not None, "match produced")
    time.sleep(8)

    # Authoritative send signal = the worker log line, which only prints AFTER
    # ses.send_email returns without error. (SendQuota.SentLast24Hours is eventually
    # consistent and lags by minutes, so it is unreliable for an immediate assertion.)
    logged = _worker_logged_send(lost, found)
    check(logged, "worker logged a successful SES send ([notify] emailed ...)")
    if m:
        m2 = matches_t.get_item(Key={"queryItemId": lost, "candidateItemId": found}).get("Item", {})
        check(m2.get("notified") is True, "match marked notified=true after send")
    after = sent_count()
    print(f"  (SES SentLast24Hours {before} -> {after}; note: this counter lags, not asserted)")

    print("cleanup (test items; demo user left in place for re-runs)")
    for iid in created:
        items_t.delete_item(Key={"itemId": iid})
    matches_t.delete_item(Key={"queryItemId": lost, "candidateItemId": found})
    print("  [OK  ] cleaned up")

    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED"); [print(" -", f) for f in failures]
        sys.exit(1)
    print(f"RESULT: real email sent — check the {RECIPIENT} inbox (and spam).")


if __name__ == "__main__":
    main()
