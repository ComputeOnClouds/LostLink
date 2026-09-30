#!/usr/bin/env python3
"""Task 14: system performance load test for the matching pipeline.

Submits N lost reports concurrently via the API and measures:
  - submit latency (API create): p50/p95/max
  - end-to-end match latency: from submit to the Match row appearing (worker done)
  - throughput: reports submitted per second
  - queue processing: how long the async worker takes to drain (approx via match times)

Also seeds a fixed found-item inventory first so every lost report has a true match,
exercising the cross-org brute-force retrieval at the configured inventory size.

Env (set by loadtest.sh): API_URL, USER_POOL_ID, CLIENT_ID, ITEMS_TABLE, MATCHES_TABLE,
REGION. Tunables: LT_REPORTS (default 20), LT_INVENTORY (default 20), LT_CONCURRENCY (10).
"""
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

API = os.environ["API_URL"].rstrip("/")
REGION = os.environ.get("REGION", "ap-southeast-2")
POOL = os.environ["USER_POOL_ID"]
CLIENT = os.environ["CLIENT_ID"]
ddb = boto3.resource("dynamodb", region_name=REGION)
items_t = ddb.Table(os.environ["ITEMS_TABLE"])
matches_t = ddb.Table(os.environ["MATCHES_TABLE"])

# NOTE: this AWS account has a TOTAL Lambda concurrency limit of 10 (see RATIONALE
# ADR-024). The async matching worker consumes slots from SQS, so high API concurrency
# collides with it and API Gateway returns 503. Defaults are conservative; the retry in
# post() absorbs transient collisions. On a normal account raise LT_CONCURRENCY.
N_REPORTS = int(os.environ.get("LT_REPORTS", "15"))
N_INVENTORY = int(os.environ.get("LT_INVENTORY", "15"))
CONCURRENCY = int(os.environ.get("LT_CONCURRENCY", "2"))

created_items = []


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


def post(path, tok, body, retries=7):
    """POST with retry+backoff on transient 5xx (throttling), so the load test
    measures steady-state latency rather than crashing on a transient throttle."""
    data = json.dumps(body).encode()
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(f"{API}{path}", data=data, method="POST")
        req.add_header("Authorization", tok)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read() or "{}")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s, 2s, 4s
                continue
            raise
    raise last


def pct(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = int(round((p / 100) * (len(xs) - 1)))
    return xs[k]


def main():
    print(f"Load test: {N_REPORTS} reports, {N_INVENTORY} inventory items, "
          f"concurrency {CONCURRENCY}\n")
    staff = token("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus")
    user = token("user@lostlink.example", "User!Pass123", "Individual")

    # 1. Seed a found-item inventory (distinct objects) so retrieval has volume.
    print(f"Seeding {N_INVENTORY} found items...")
    for i in range(N_INVENTORY):
        b = post("/items", staff, {
            "description": f"load-test object {i}: a distinctive item number {i} with tag {uuid.uuid4().hex[:6]}",
            "locationZone": f"zone-{i % 5}",
            "eventTime": "2026-09-20T10:00:00+00:00"})
        created_items.append(b["itemId"])
        time.sleep(0.3)  # pace seeding so the worker (shared 10-slot pool) can keep up
    print("Letting the match queue drain before measuring submit latency...")
    time.sleep(20)  # let seeded items' match jobs finish so slots are free

    # 2. Submit N lost reports concurrently; record submit latency + submit timestamp.
    print(f"Submitting {N_REPORTS} lost reports (concurrency {CONCURRENCY})...")
    submit_latencies = []
    submitted = {}  # itemId -> submit_epoch

    def submit_one(i):
        body = {"description": f"lost load-test object {i}: distinctive item number {i}",
                "locationZone": f"zone-{i % 5}", "eventTime": "2026-09-20T09:00:00+00:00"}
        t0 = time.time()
        b = post("/reports", user, body)
        dt = time.time() - t0
        return b["itemId"], t0, dt

    wall_start = time.time()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = [ex.submit(submit_one, i) for i in range(N_REPORTS)]
        for f in as_completed(futs):
            item_id, t0, dt = f.result()
            submit_latencies.append(dt)
            submitted[item_id] = t0
            created_items.append(item_id)
    submit_wall = time.time() - wall_start

    # 3. Poll for match rows; record end-to-end latency (submit -> match visible).
    print("Waiting for the async worker to produce matches...")
    e2e_latencies = []
    pending = set(submitted)
    deadline = time.time() + 180
    while pending and time.time() < deadline:
        for item_id in list(pending):
            rows = matches_t.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("queryItemId").eq(item_id)
            ).get("Items", [])
            if rows:
                e2e_latencies.append(time.time() - submitted[item_id])
                pending.discard(item_id)
        if pending:
            time.sleep(2)

    matched = N_REPORTS - len(pending)

    # ---- report -------------------------------------------------------------------
    print("\n===== RESULTS =====")
    print(f"Inventory size (found items):     {N_INVENTORY}")
    print(f"Reports submitted:                {N_REPORTS}")
    print(f"Reports matched within window:    {matched}/{N_REPORTS}")
    print(f"Submit throughput:                {N_REPORTS / submit_wall:.1f} reports/sec")
    print("Submit latency (API create), sec:")
    print(f"  p50={pct(submit_latencies,50):.3f}  p95={pct(submit_latencies,95):.3f}  max={max(submit_latencies):.3f}")
    if e2e_latencies:
        print("End-to-end match latency (submit->match visible), sec:")
        print(f"  p50={pct(e2e_latencies,50):.2f}  p95={pct(e2e_latencies,95):.2f}  max={max(e2e_latencies):.2f}")
        print(f"  mean={statistics.mean(e2e_latencies):.2f}")
    else:
        print("No matches observed within the window.")

    # machine-readable
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "loadtest.json"), "w") as f:
        json.dump({
            "inventory": N_INVENTORY, "reports": N_REPORTS, "matched": matched,
            "submit_throughput_rps": round(N_REPORTS / submit_wall, 2),
            "submit_latency_s": {"p50": pct(submit_latencies, 50), "p95": pct(submit_latencies, 95),
                                 "max": max(submit_latencies)},
            "e2e_latency_s": {"p50": pct(e2e_latencies, 50), "p95": pct(e2e_latencies, 95),
                              "max": max(e2e_latencies) if e2e_latencies else None,
                              "mean": statistics.mean(e2e_latencies) if e2e_latencies else None},
        }, f, indent=2)
    print(f"\nWrote {out_dir}/loadtest.json")

    print("\nCleaning up test items...")
    for iid in created_items:
        try:
            items_t.delete_item(Key={"itemId": iid})
        except Exception:
            pass
    # delete match rows for submitted lost items
    for item_id in submitted:
        rows = matches_t.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("queryItemId").eq(item_id)
        ).get("Items", [])
        for m in rows:
            matches_t.delete_item(Key={"queryItemId": m["queryItemId"],
                                       "candidateItemId": m["candidateItemId"]})
    print("Done.")


if __name__ == "__main__":
    main()
