#!/usr/bin/env python3
"""Task 7 LIVE integration check for the real pipeline stages.

Runs the actual TitanEmbedder against Bedrock (asserts a non-trivial vector with the
image slot empty) and, if a sample photo is uploaded, ClaudeDescriptionSource. Skips
gracefully (exit 0 with a notice) if the account is still pending Bedrock verification,
so it can be re-run later without editing.
"""
import os
import sys

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pipeline.models import Item, ItemType  # noqa: E402
from pipeline.impl.embedder import TitanEmbedder  # noqa: E402
from pipeline.impl.description import ClaudeDescriptionSource  # noqa: E402

failures = []


def check(cond, msg):
    print(f"  [{'OK  ' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


def _pending(e: ClientError) -> bool:
    return "being verified" in e.response["Error"].get("Message", "")


def main():
    print("1. Titan text embedding (live)")
    emb = TitanEmbedder()
    item = Item(item_id="probe", item_type=ItemType.LOST, organisation_id="individual",
                owner_id="u", description="black leather wallet with a red stripe")
    try:
        vm = emb.embed(item)
        check(vm.has_text() and len(vm.text) >= 256, f"embedding produced (dim={len(vm.text or [])})")
        check(not vm.has_image(), "image slot empty (Option 1)")
    except ClientError as e:
        if _pending(e):
            print("  [SKIP] Bedrock access still pending account verification — re-run later.")
            return
        raise

    print("2. Claude description from a photo (live, optional)")
    photos = os.environ.get("PHOTOS_BUCKET")
    sample = os.environ.get("SAMPLE_PHOTO_KEY")
    if not (photos and sample):
        print("  [SKIP] set PHOTOS_BUCKET + SAMPLE_PHOTO_KEY to test the vision path.")
    else:
        src = ClaudeDescriptionSource()
        desc = src.describe(Item(item_id="probe2", item_type=ItemType.FOUND,
                                 organisation_id="org-nus", owner_id="s",
                                 description="", photo_key=sample))
        check(bool(desc), f"generated description: {desc[:60]!r}")

    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED")
        sys.exit(1)
    print("RESULT: live Bedrock checks passed")


if __name__ == "__main__":
    main()
