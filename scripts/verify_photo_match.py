#!/usr/bin/env python3
"""End-to-end test of the PHOTO-DRIVEN matching path (needs Claude access).

Staff registers a found item with ONLY a photo (no typed description). The worker must
call Claude to turn the photo into a description, embed it, and match it against an
individual's typed lost report. Proves the full Option-1 photo->description->match flow.

Env (from verify_photo_match.sh): API_URL, USER_POOL_ID, CLIENT_ID, ITEMS_TABLE,
MATCHES_TABLE, PHOTOS_BUCKET, REGION.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

import boto3
from PIL import Image, ImageDraw

API = os.environ["API_URL"].rstrip("/")
REGION = os.environ.get("REGION", "ap-southeast-2")
POOL = os.environ["USER_POOL_ID"]
CLIENT = os.environ["CLIENT_ID"]
ddb = boto3.resource("dynamodb", region_name=REGION)
items_t = ddb.Table(os.environ["ITEMS_TABLE"])
matches_t = ddb.Table(os.environ["MATCHES_TABLE"])

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


def make_backpack_png(path):
    # A recognisable teal backpack shape so Claude produces a useful description.
    img = Image.new("RGB", (320, 360), "white")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([70, 90, 250, 320], radius=30, fill=(20, 140, 140), outline=(10, 90, 90), width=5)
    d.rounded_rectangle([110, 130, 210, 230], radius=15, fill=(15, 110, 110), outline=(10, 80, 80), width=4)  # front pocket
    d.arc([95, 40, 225, 140], start=180, end=360, fill=(10, 90, 90), width=10)  # top handle
    d.rectangle([90, 90, 100, 320], fill=(10, 90, 90))  # left strap
    d.rectangle([220, 90, 230, 320], fill=(10, 90, 90))  # right strap
    img.save(path)


def poll_match(q, timeout=120):
    for _ in range(timeout // 3):
        rows = matches_t.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("queryItemId").eq(q)
        ).get("Items", [])
        if rows:
            return rows[0]
        time.sleep(3)
    return None


def main():
    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    user = token("user@lostlink.example", "User!Pass123", "Individual")

    print("1. staff requests a presigned upload + PUTs a real backpack image")
    st, up = call("POST", "/items/uploads", staff, {"contentType": "image/png"})
    check(st == 200 and "photoKey" in up, f"presigned upload url (got {st})")
    make_backpack_png("/tmp/backpack.png")
    with open("/tmp/backpack.png", "rb") as f:
        put = urllib.request.Request(up["uploadUrl"], data=f.read(), method="PUT")
        put.add_header("Content-Type", "image/png")
    with urllib.request.urlopen(put) as r:
        check(r.status in (200, 204), "photo uploaded to S3")

    print("2. staff registers the found item with ONLY the photo (no description)")
    st, b = call("POST", "/items", staff, {
        "locationZone": "zone-library", "eventTime": "2026-09-24T14:00:00+00:00",
        "photoKey": up["photoKey"]})
    check(st == 201, f"register found (photo-only) -> 201 (got {st})")
    found_id = b["itemId"]; created.append(found_id)

    print("3. individual reports the matching item with a typed description")
    st, b = call("POST", "/reports", user, {
        "description": "lost my teal backpack with straps and a front pocket",
        "locationZone": "zone-library", "eventTime": "2026-09-24T12:00:00+00:00"})
    lost_id = b["itemId"]; created.append(lost_id)

    print("4. worker turns the photo into a description (Claude), embeds, and matches")
    m = poll_match(lost_id)
    check(m is not None, "match produced from a photo-only found item")

    # Confirm the worker generated + cached a description on the photo-only found item.
    found = items_t.get_item(Key={"itemId": found_id}).get("Item", {})
    desc = found.get("description")
    check(bool(desc), f"Claude generated a description for the found item: {str(desc)[:60]!r}")
    check(bool(found.get("vecText")), "found item got a text embedding from the generated description")
    if m:
        check(float(m.get("score", 0)) >= 0.7, f"match score >= threshold (score={m.get('score')})")

    print("5. cleanup")
    for iid in created:
        items_t.delete_item(Key={"itemId": iid})
    if m:
        matches_t.delete_item(Key={"queryItemId": lost_id, "candidateItemId": found_id})
    print("  [OK  ] cleaned up")

    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED"); [print(" -", f) for f in failures]
        sys.exit(1)
    print("RESULT: photo -> Claude description -> embedding -> match verified end-to-end")


if __name__ == "__main__":
    main()
