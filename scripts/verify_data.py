#!/usr/bin/env python3
"""Task 3 live verification.

Exercises the DynamoItemRepository against the deployed tables and tests presigned-URL
upload/download against the photos bucket. Run inside the backend venv with AWS creds.

Usage (via scripts/verify_data.sh which sets env + venv):
    python3 scripts/verify_data.py
"""
import os
import sys
import uuid
import urllib.request

import boto3

# Make the backend package importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pipeline.models import Item, ItemType, VectorMap, MatchResult, OrgScope  # noqa: E402
from pipeline.impl.repository import DynamoItemRepository  # noqa: E402

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
PHOTOS_BUCKET = os.environ["PHOTOS_BUCKET"]

failures = []


def check(cond, msg):
    status = "OK  " if cond else "FAIL"
    print(f"  [{status}] {msg}")
    if not cond:
        failures.append(msg)


def main():
    repo = DynamoItemRepository()

    org = "org-nus"
    lost_id = f"lost-{uuid.uuid4().hex[:8]}"
    found_id = f"found-{uuid.uuid4().hex[:8]}"

    print("1. Write + read a lost report (individual, no photo, text vector cached)")
    lost = Item(
        item_id=lost_id,
        item_type=ItemType.LOST,
        organisation_id=org,  # loss reported near this org's zone
        owner_id="user@lostlink.example",
        description="black leather wallet with red stripe",
        location_zone="zone-central-library",
        event_time="2026-09-29T10:00:00+00:00",
        photo_key=None,
        vectors=VectorMap(text=[0.1, 0.2, 0.3]),
    )
    repo.save(lost)
    got = repo.get(lost_id)
    check(got.item_id == lost_id, "lost report round-trips by id")
    check(got.item_type is ItemType.LOST, "item_type preserved")
    check(got.vectors.text == [0.1, 0.2, 0.3], "text vector preserved")
    check(not got.vectors.has_image(), "image slot empty (no photo)")
    check(got.description == lost.description, "description preserved")

    print("2. Write + read a found item (staff, with photo key + text vector)")
    found = Item(
        item_id=found_id,
        item_type=ItemType.FOUND,
        organisation_id=org,
        owner_id="staff@lostlink.example",
        description="dark wallet, leather, found at library entrance",
        location_zone="zone-central-library",
        event_time="2026-09-29T15:00:00+00:00",
        photo_key=f"{org}/{found_id}.jpg",
        vectors=VectorMap(text=[0.11, 0.19, 0.31]),
    )
    repo.save(found)
    gotf = repo.get(found_id)
    check(gotf.photo_key == found.photo_key, "photo key preserved")
    check(gotf.organisation_id == org, "org preserved")

    print("3. list_candidates: cross-org retrieval returns opposing type")
    cands = repo.list_candidates(lost, OrgScope(all_authorised=True))
    cand_ids = {c.item_id for c in cands}
    check(found_id in cand_ids, "found item is a candidate for the lost report")
    check(all(c.item_type is ItemType.FOUND for c in cands), "all candidates are FOUND")
    check(lost_id not in cand_ids, "query item excluded from its own candidates")

    print("4. list_candidates: org-scoped retrieval stays within org")
    scoped = repo.list_candidates(lost, OrgScope(all_authorised=False, org_ids=[org]))
    check(found_id in {c.item_id for c in scoped}, "org-scoped retrieval finds the item")
    other = repo.list_candidates(lost, OrgScope(all_authorised=False, org_ids=["org-other"]))
    check(found_id not in {c.item_id for c in other}, "different org sees nothing (boundary)")

    print("5. save_match persists a match result")
    repo.save_match(
        MatchResult(
            query_item_id=lost_id,
            candidate_item_id=found_id,
            organisation_id=org,
            score=0.82,
            profile_name="text_location_time",
            breakdown={"text": 0.9, "location": 1.0, "time": 0.5},
        )
    )
    matches_table = boto3.resource("dynamodb").Table(os.environ["MATCHES_TABLE"])
    m = matches_table.get_item(Key={"queryItemId": lost_id, "candidateItemId": found_id})
    check("Item" in m, "match row persisted")
    check(m.get("Item", {}).get("notified") is False, "match starts un-notified (dedup ready)")

    print("6. presigned URL upload + download on the photos bucket")
    # Use the regional endpoint + SigV4 so the presigned URL targets the region host
    # directly and avoids the 307 redirect newly-created buckets return outside
    # us-east-1. This is also how the request Lambdas will generate URLs.
    from botocore.config import Config as BotoConfig

    s3 = boto3.client(
        "s3",
        region_name=REGION,
        endpoint_url=f"https://s3.{REGION}.amazonaws.com",
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )
    key = f"{org}/verify-{uuid.uuid4().hex[:8]}.txt"
    payload = b"lostlink-presigned-test"
    put_url = s3.generate_presigned_url(
        "put_object", Params={"Bucket": PHOTOS_BUCKET, "Key": key}, ExpiresIn=300
    )
    req = urllib.request.Request(put_url, data=payload, method="PUT")
    with urllib.request.urlopen(req) as r:
        check(r.status in (200, 204), "presigned PUT upload succeeds")
    get_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": PHOTOS_BUCKET, "Key": key}, ExpiresIn=300
    )
    with urllib.request.urlopen(get_url) as r:
        body = r.read()
    check(body == payload, "presigned GET returns the uploaded bytes")

    print("7. cleanup test artifacts")
    items_table = boto3.resource("dynamodb").Table(os.environ["ITEMS_TABLE"])
    items_table.delete_item(Key={"itemId": lost_id})
    items_table.delete_item(Key={"itemId": found_id})
    matches_table.delete_item(Key={"queryItemId": lost_id, "candidateItemId": found_id})
    s3.delete_object(Bucket=PHOTOS_BUCKET, Key=key)
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
