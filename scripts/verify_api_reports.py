#!/usr/bin/env python3
"""Task 4 integration test: individual lost-item reporting API.

Signs in as two separate individual users via Cognito, then exercises the reports API
over HTTP:
  - create with typed description (no photo)
  - create with a photo (presigned upload first), description omitted
  - list own reports, get one
  - edit, withdraw
  - 403 when user B tries to read user A's report
  - 400 validation (missing location; missing both description and photo)

Env (set by verify_api_reports.sh): API_URL, USER_POOL_ID, CLIENT_ID, PHOTOS_BUCKET,
REGION. Uses the AWS CLI for auth token retrieval and admin user creation.
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
import uuid

API = os.environ["API_URL"].rstrip("/")
REGION = os.environ.get("REGION", "ap-southeast-2")
POOL = os.environ["USER_POOL_ID"]
CLIENT = os.environ["CLIENT_ID"]

failures = []


def check(cond, msg):
    print(f"  [{'OK  ' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


def aws(*args):
    out = subprocess.run(
        ["aws", *args, "--region", REGION], capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def ensure_individual(email, password):
    """Create + confirm an Individual user (idempotent) and return an ID token."""
    try:
        aws("cognito-idp", "admin-create-user", "--user-pool-id", POOL,
            "--username", email, "--message-action", "SUPPRESS",
            "--user-attributes", f"Name=email,Value={email}", "Name=email_verified,Value=true")
    except RuntimeError as e:
        if "UsernameExistsException" not in str(e):
            raise
    aws("cognito-idp", "admin-set-user-password", "--user-pool-id", POOL,
        "--username", email, "--password", password, "--permanent")
    aws("cognito-idp", "admin-add-user-to-group", "--user-pool-id", POOL,
        "--username", email, "--group-name", "Individual")
    res = aws("cognito-idp", "initiate-auth", "--auth-flow", "USER_PASSWORD_AUTH",
              "--client-id", CLIENT,
              "--auth-parameters", f"USERNAME={email},PASSWORD={password}")
    return json.loads(res)["AuthenticationResult"]["IdToken"]


def call(method, path, token, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def main():
    print("Signing in two individual users ...")
    token_a = ensure_individual("user@lostlink.example", "User!Pass123")
    token_b = ensure_individual("user2@lostlink.example", "User2!Pass123")

    print("1. create report with typed description (no photo)")
    st, body = call("POST", "/reports", token_a, {
        "description": "blue umbrella with wooden handle",
        "locationZone": "zone-bus-stop-A",
        "eventTime": "2026-09-29T08:30:00+00:00",
    })
    check(st == 201, f"POST /reports -> 201 (got {st})")
    item_a = body.get("itemId")
    check(bool(item_a), "response has itemId")

    print("2. request presigned upload URL, then create report with a photo (no desc)")
    st, up = call("POST", "/uploads", token_a, {"contentType": "image/jpeg"})
    check(st == 200 and "uploadUrl" in up and "photoKey" in up, f"POST /uploads -> 200 (got {st})")
    # actually upload some bytes to the presigned URL
    put = urllib.request.Request(up["uploadUrl"], data=b"fake-jpeg-bytes", method="PUT")
    put.add_header("Content-Type", "image/jpeg")
    with urllib.request.urlopen(put) as r:
        check(r.status in (200, 204), "presigned photo upload succeeds")
    st, body = call("POST", "/reports", token_a, {
        "locationZone": "zone-canteen",
        "photoKey": up["photoKey"],
    })
    check(st == 201, f"POST /reports (photo, no description) -> 201 (got {st})")
    item_a_photo = body.get("itemId")

    print("3. list own reports (expect >= 2)")
    st, body = call("GET", "/reports", token_a)
    ids = {r["itemId"] for r in body.get("reports", [])}
    check(st == 200, f"GET /reports -> 200 (got {st})")
    check(item_a in ids and item_a_photo in ids, "both created reports listed")

    print("4. get one own report")
    st, body = call("GET", f"/reports/{item_a}", token_a)
    check(st == 200 and body.get("itemId") == item_a, f"GET /reports/{{id}} -> 200 (got {st})")

    print("5. edit own report")
    st, body = call("PATCH", f"/reports/{item_a}", token_a, {"description": "blue umbrella, brass tip"})
    check(st == 200 and body.get("description") == "blue umbrella, brass tip", f"PATCH -> 200 (got {st})")
    check(body.get("status") == "pending_match", "edit resets status to pending_match")

    print("6. cross-user access is denied (privacy)")
    st, body = call("GET", f"/reports/{item_a}", token_b)
    check(st == 403, f"user B GET user A's report -> 403 (got {st})")
    st, body = call("PATCH", f"/reports/{item_a}", token_b, {"description": "hijack"})
    check(st == 403, f"user B PATCH user A's report -> 403 (got {st})")

    print("7. unauthenticated request is rejected")
    req = urllib.request.Request(f"{API}/reports", method="GET")
    try:
        with urllib.request.urlopen(req) as r:
            st = r.status
    except urllib.error.HTTPError as e:
        st = e.code
    check(st == 401, f"no-token GET /reports -> 401 (got {st})")

    print("8. validation errors")
    st, _ = call("POST", "/reports", token_a, {"description": "no location"})
    check(st == 400, f"missing locationZone -> 400 (got {st})")
    st, _ = call("POST", "/reports", token_a, {"locationZone": "zone-x"})
    check(st == 400, f"no description and no photo -> 400 (got {st})")

    print("9. withdraw own report")
    st, body = call("DELETE", f"/reports/{item_a}", token_a)
    check(st == 200 and body.get("status") == "withdrawn", f"DELETE -> 200 withdrawn (got {st})")

    print("10. cleanup created items")
    import boto3
    t = boto3.resource("dynamodb", region_name=REGION).Table(os.environ["ITEMS_TABLE"])
    for iid in [item_a, item_a_photo]:
        if iid:
            t.delete_item(Key={"itemId": iid})
    print("  [OK  ] cleaned up")

    print()
    if failures:
        print(f"RESULT: {len(failures)} check(s) FAILED")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: all checks passed")


if __name__ == "__main__":
    main()
