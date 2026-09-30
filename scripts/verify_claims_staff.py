#!/usr/bin/env python3
"""Task 12 integration test: staff claim review, approval lifecycle, handover, withdrawal.

Flow:
  - staff registers a found item; individual reports the match; worker matches; individual
    submits a claim.
  - staff GET /org/claims sees the claim + the claimant's evidence.
  - staff B (org-other) cannot see/act on org-nus's claim (403).
  - approve -> reserve -> handover; found item status goes reserved -> closed.
  - after approval the CLAIMANT's own claim view now reveals the item details (privacy
    gate opens only after approval).
  - reject path on a second claim.
  - withdrawal: staff withdraws a found item with an active claim -> claim becomes
    rejected (claimsAffected >= 1).
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
items_created = []
claims_created = []


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


def make_claim(staff_tok, user_tok, desc, user_desc, zone):
    _, b = call("POST", "/items", staff_tok, {
        "description": desc, "locationZone": zone, "eventTime": "2026-09-26T10:00:00+00:00"})
    found = b["itemId"]; items_created.append(found)
    _, b = call("POST", "/reports", user_tok, {
        "description": user_desc, "locationZone": zone, "eventTime": "2026-09-26T09:00:00+00:00"})
    lost = b["itemId"]; items_created.append(lost)
    m = poll_match(lost)
    if not m:
        return found, lost, None
    _, b = call("POST", "/claims", user_tok, {
        "queryItemId": lost, "candidateItemId": found,
        "evidenceText": "I can prove ownership: serial number and receipt."})
    cid = b.get("claimId"); claims_created.append(cid)
    return found, lost, cid


def main():
    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    staff_b = token("staff2@lostlink.example", "Staff2!Pass123", "Staff", "org-other")
    user = token("user@lostlink.example", "User!Pass123", "Individual")

    print("1. set up a matched claim (approval-path)")
    found1, lost1, claim1 = make_claim(
        staff, user,
        "a silver DJI Mini drone in a grey case with a cracked propeller guard",
        "lost my silver DJI Mini drone, grey case, cracked propeller guard", "zone-rooftop")
    check(claim1 is not None, "claim1 created after match")
    if not claim1:
        cleanup(); finish()

    print("2. staff sees the claim + claimant evidence via GET /org/claims")
    st, body = call("GET", "/org/claims", staff)
    check(st == 200, f"GET /org/claims -> 200 (got {st})")
    mine = [c for c in body.get("claims", []) if c["claimId"] == claim1]
    check(len(mine) == 1 and mine[0].get("evidenceText"), "staff sees claim with evidenceText")

    print("3. staff B (org-other) cannot see/act on org-nus claim")
    st, _ = call("GET", f"/org/claims/{claim1}", staff_b)
    check(st == 403, f"staff B GET org-nus claim -> 403 (got {st})")
    st, _ = call("POST", f"/org/claims/{claim1}/approve", staff_b, {})
    check(st == 403, f"staff B approve org-nus claim -> 403 (got {st})")

    print("4. approve -> reserve -> handover; item status reserved -> closed")
    st, b = call("POST", f"/org/claims/{claim1}/approve", staff, {"message": "verified"})
    check(st == 200 and b["state"] == "approved", f"approve -> approved (got {st})")

    print("5. claimant now sees the item details (privacy gate opens after approval)")
    st, cv = call("GET", f"/claims/{claim1}", user)
    check(st == 200 and cv.get("item") is not None, "approved claim reveals item to claimant")
    check(cv.get("item", {}).get("description", "").startswith("a silver DJI"), "item description now visible")

    st, b = call("POST", f"/org/claims/{claim1}/reserve", staff, {})
    check(st == 200 and b["state"] == "reserved", f"reserve -> reserved (got {st})")
    fi = items_t.get_item(Key={"itemId": found1}).get("Item", {})
    check(fi.get("status") == "reserved", "found item status = reserved")

    st, b = call("POST", f"/org/claims/{claim1}/handover", staff, {})
    check(st == 200 and b["state"] == "handed_over", f"handover -> handed_over (got {st})")
    fi = items_t.get_item(Key={"itemId": found1}).get("Item", {})
    check(fi.get("status") == "closed", "found item status = closed after handover")

    print("6. invalid transition (approve after handover) -> 409")
    st, _ = call("POST", f"/org/claims/{claim1}/approve", staff, {})
    check(st == 409, f"approve after handover -> 409 (got {st})")

    print("7. reject path on a second claim")
    found2, lost2, claim2 = make_claim(
        staff, user,
        "a red Herschel duffel bag with a broken buckle and airline tags",
        "lost red Herschel duffel, broken buckle, airline tags", "zone-terminal")
    if claim2:
        st, b = call("POST", f"/org/claims/{claim2}/reject", staff, {"message": "insufficient proof"})
        check(st == 200 and b["state"] == "rejected", f"reject -> rejected (got {st})")

    print("8. withdrawal rejects active claimants on the item")
    found3, lost3, claim3 = make_claim(
        staff, user,
        "a black Bose QC headphone case with a name sticker inside",
        "lost black Bose QC headphones case, name sticker inside", "zone-library-2")
    if claim3:
        st, b = call("DELETE", f"/items/{found3}", staff)
        check(st == 200 and b.get("claimsAffected", 0) >= 1, f"withdraw notifies/affects claims (got {st}, affected={b.get('claimsAffected')})")
        st, cv = call("GET", f"/claims/{claim3}", user)
        check(cv.get("state") == "rejected", "claim on withdrawn item is now rejected")

    cleanup(); finish()


def cleanup():
    print("cleanup")
    for iid in items_created:
        items_t.delete_item(Key={"itemId": iid})
    # matches: best-effort delete for each lost report
    for i in range(0, len(items_created), 2):
        try:
            found = items_created[i]; lost = items_created[i + 1]
            matches_t.delete_item(Key={"queryItemId": lost, "candidateItemId": found})
        except Exception:
            pass
    for cid in claims_created:
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
    print("RESULT: staff claims workflow + handover + withdrawal verified live")
    sys.exit(0)


if __name__ == "__main__":
    main()
