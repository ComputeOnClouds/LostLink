#!/usr/bin/env python3
"""Task 5 integration test: staff inventory management API.

Signs in as two staff users in DIFFERENT organisations, plus an individual, then:
  - register a found item (typed description)
  - register a found item photo-first (presigned upload, no description)
  - list org inventory; search by ?q=; filter by ?status=
  - get / update / withdraw own-org item
  - NEGATIVE: staff B (org-other) cannot GET/PATCH/DELETE staff A's (org-nus) item -> 403
  - NEGATIVE: an Individual cannot use staff routes -> 403
  - org boundary on list: staff B's inventory does not include staff A's item

Env (from verify_api_staff.sh): API_URL, USER_POOL_ID, CLIENT_ID, ITEMS_TABLE, REGION.
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

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
    out = subprocess.run(["aws", *args, "--region", REGION], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def ensure_user(email, password, group, org=None):
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


def call(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def main():
    print("Signing in staff A (org-nus), staff B (org-other), and an individual ...")
    staff_a = ensure_user("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    staff_b = ensure_user("staff2@lostlink.example", "Staff2!Pass123", "Staff", "org-other")
    individual = ensure_user("user@lostlink.example", "User!Pass123", "Individual")

    created = []

    print("1. staff A registers a found item (typed description)")
    st, body = call("POST", "/items", staff_a, {
        "description": "black leather wallet with red stripe",
        "locationZone": "zone-central-library",
        "eventTime": "2026-09-29T15:00:00+00:00",
    })
    check(st == 201, f"POST /items -> 201 (got {st})")
    item_a = body.get("itemId"); created.append(item_a)
    check(bool(item_a), "response has itemId")

    print("2. staff A registers a found item photo-first (no description)")
    st, up = call("POST", "/items/uploads", staff_a, {"contentType": "image/png"})
    check(st == 200 and "uploadUrl" in up, f"POST /items/uploads -> 200 (got {st})")
    put = urllib.request.Request(up["uploadUrl"], data=b"fake-png", method="PUT")
    put.add_header("Content-Type", "image/png")
    with urllib.request.urlopen(put) as r:
        check(r.status in (200, 204), "presigned photo upload succeeds")
    st, body = call("POST", "/items", staff_a, {"locationZone": "zone-gym", "photoKey": up["photoKey"]})
    check(st == 201, f"POST /items (photo, no description) -> 201 (got {st})")
    item_a_photo = body.get("itemId"); created.append(item_a_photo)

    print("3. staff A lists org inventory + search + status filter")
    st, body = call("GET", "/items", staff_a)
    ids = {i["itemId"] for i in body.get("items", [])}
    check(st == 200 and item_a in ids and item_a_photo in ids, "both items listed for org")
    check(all(i["organisationId"] == "org-nus" for i in body.get("items", [])), "all items are org-nus")
    st, body = call("GET", "/items?q=wallet", staff_a)
    q_ids = {i["itemId"] for i in body.get("items", [])}
    check(item_a in q_ids and item_a_photo not in q_ids, "?q=wallet matches only the wallet")
    st, body = call("GET", "/items?status=available", staff_a)
    check(all(i["status"] == "available" for i in body.get("items", [])), "?status=available filters")

    print("4. staff A gets / updates / (later) withdraws own item")
    st, body = call("GET", f"/items/{item_a}", staff_a)
    check(st == 200 and body.get("itemId") == item_a, f"GET own item -> 200 (got {st})")
    st, body = call("PATCH", f"/items/{item_a}", staff_a, {"description": "dark leather wallet, red stripe, brass studs"})
    check(st == 200 and "brass studs" in (body.get("description") or ""), f"PATCH own item -> 200 (got {st})")

    print("5. NEGATIVE: staff B (org-other) cannot access staff A's (org-nus) item")
    st, _ = call("GET", f"/items/{item_a}", staff_b)
    check(st == 403, f"staff B GET org-nus item -> 403 (got {st})")
    st, _ = call("PATCH", f"/items/{item_a}", staff_b, {"description": "hijack"})
    check(st == 403, f"staff B PATCH org-nus item -> 403 (got {st})")
    st, _ = call("DELETE", f"/items/{item_a}", staff_b)
    check(st == 403, f"staff B DELETE org-nus item -> 403 (got {st})")

    print("6. NEGATIVE: staff B's inventory excludes org-nus items (boundary)")
    st, body = call("GET", "/items", staff_b)
    b_ids = {i["itemId"] for i in body.get("items", [])}
    check(item_a not in b_ids and item_a_photo not in b_ids, "org-other inventory excludes org-nus items")

    print("7. NEGATIVE: an Individual cannot use staff routes")
    st, _ = call("POST", "/items", individual, {"description": "x", "locationZone": "z"})
    check(st == 403, f"individual POST /items -> 403 (got {st})")
    st, _ = call("GET", "/items", individual)
    check(st == 403, f"individual GET /items -> 403 (got {st})")

    print("8. validation errors")
    st, _ = call("POST", "/items", staff_a, {"description": "no location"})
    check(st == 400, f"missing locationZone -> 400 (got {st})")
    st, _ = call("POST", "/items", staff_a, {"locationZone": "zone-x"})
    check(st == 400, f"no description and no photo -> 400 (got {st})")

    print("9. staff A withdraws own item")
    st, body = call("DELETE", f"/items/{item_a}", staff_a)
    check(st == 200 and body.get("status") == "withdrawn", f"DELETE own item -> 200 withdrawn (got {st})")

    print("10. cleanup")
    import boto3
    t = boto3.resource("dynamodb", region_name=REGION).Table(os.environ["ITEMS_TABLE"])
    for iid in created:
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
