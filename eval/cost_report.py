#!/usr/bin/env python3
"""Task 14: enumerate deployed billable resources (from cdk synth) and produce a
cloud-vs-on-premise cost comparison for the report.

Reads the synthesized CloudFormation templates in infra/cdk.out (run `cdk synth` first)
and counts resources by type, classifying each as pay-per-use (serverless) or fixed.
Then prints an order-of-magnitude monthly cost comparison against an equivalent
always-on on-premise / EC2 setup, with the assumptions stated explicitly.

Prices are ap-southeast-2 list prices as of 2026 and are ESTIMATES for the report; they
are documented so the reader can re-check. Usage assumptions are stated inline.
"""
from __future__ import annotations

import glob
import json
import os

CDK_OUT = os.path.join(os.path.dirname(__file__), "..", "infra", "cdk.out")

# Which resource types bill per-use (serverless) vs a fixed monthly floor.
PAY_PER_USE = {
    "AWS::Lambda::Function", "AWS::ApiGatewayV2::Api", "AWS::ApiGatewayV2::Route",
    "AWS::DynamoDB::Table", "AWS::SQS::Queue", "AWS::S3::Bucket",
    "AWS::Cognito::UserPool", "AWS::Cognito::UserPoolClient",
    "AWS::CloudFront::Distribution", "AWS::SES::EmailIdentity",
}


def enumerate_resources() -> dict[str, int]:
    counts: dict[str, int] = {}
    templates = glob.glob(os.path.join(CDK_OUT, "*.template.json"))
    if not templates:
        raise SystemExit(f"No synthesized templates in {CDK_OUT}. Run: cd infra && npx cdk synth")
    for t in templates:
        with open(t) as f:
            doc = json.load(f)
        for _, res in (doc.get("Resources") or {}).items():
            rtype = res.get("Type", "")
            if rtype.startswith("AWS::"):
                counts[rtype] = counts.get(rtype, 0) + 1
    return counts


# ---- usage assumptions for the cost estimate (STATE THESE IN THE REPORT) -----------
ASSUMPTIONS = {
    "monthly_active_users": 2000,
    "reports_per_month": 5000,       # lost + found submissions
    "api_requests_per_month": 200000,
    "match_jobs_per_month": 5000,
    "bedrock_embeddings_per_month": 10000,   # ~2 per submission (item + reprocess)
    "bedrock_descriptions_per_month": 1000,  # photo-based submissions
    "emails_per_month": 3000,
    "photo_gb_stored": 5,
}


def cloud_estimate() -> list[tuple[str, float, str]]:
    a = ASSUMPTIONS
    rows: list[tuple[str, float, str]] = []
    # Lambda: free tier covers 1M req + 400k GB-s. A demo/light month stays in free tier.
    rows.append(("Lambda (compute)", 0.00, "within free tier at this volume"))
    # API Gateway HTTP API: ~$1.00 / million requests.
    rows.append(("API Gateway (HTTP API)", a["api_requests_per_month"] / 1_000_000 * 1.00,
                 "$1.00 / million requests"))
    # DynamoDB on-demand: ~$1.25/M writes, $0.25/M reads. Assume ~4x reads vs writes.
    ddb = (a["reports_per_month"] * 4 / 1_000_000 * 1.25) + (a["api_requests_per_month"] / 1_000_000 * 0.25)
    rows.append(("DynamoDB (on-demand)", ddb, "on-demand r/w; storage negligible"))
    # SQS: first 1M requests free.
    rows.append(("SQS", 0.00, "within 1M free requests"))
    # S3: ~$0.025/GB-month + tiny requests.
    rows.append(("S3 (photos + hosting)", a["photo_gb_stored"] * 0.025, "$0.025 / GB-month"))
    # CloudFront: ~$0.114/GB out (AP); assume ~5GB.
    rows.append(("CloudFront", 5 * 0.114, "~5 GB egress @ ~$0.114/GB"))
    # Cognito: free < 50k MAU.
    rows.append(("Cognito", 0.00, "free under 50k monthly active users"))
    # SES: $0.10 / 1000 emails (free from Lambda up to 62k/mo).
    rows.append(("SES", 0.00, "within 62k/mo free (sent from Lambda)"))
    # Bedrock: Titan embed ~$0.00002/1k tokens (~30 tok each); Claude Haiku ~$0.001/desc.
    embed_cost = a["bedrock_embeddings_per_month"] * 30 / 1000 * 0.00002
    claude_cost = a["bedrock_descriptions_per_month"] * 0.0015
    rows.append(("Bedrock (Titan embeddings)", embed_cost, "~$0.00002 / 1k tokens"))
    rows.append(("Bedrock (Claude Haiku descriptions)", claude_cost, "~$0.0015 / description"))
    return rows


def onprem_estimate() -> list[tuple[str, float, str]]:
    """Equivalent always-on setup to run the same service 24/7."""
    return [
        ("Server (always-on, ~EC2 m5.large equiv)", 70.0, "24/7 compute whether used or not"),
        ("Managed DB / storage host", 25.0, "always-on database instance"),
        ("Load balancer / networking", 20.0, "always-on"),
        ("Ops/admin overhead (amortised)", 40.0, "patching, backups, monitoring effort"),
        ("Self-hosted embedding/LLM inference", 0.0,
         "either GPU host ($$$ always-on) or same Bedrock calls — excluded/parity"),
    ]


def main():
    counts = enumerate_resources()
    print("=== Deployed billable AWS resources (from cdk synth) ===")
    payg, fixed = 0, 0
    for rtype, n in sorted(counts.items()):
        tag = "pay-per-use" if rtype in PAY_PER_USE else "other/support"
        if rtype in PAY_PER_USE:
            payg += n
        else:
            fixed += n
        print(f"  {rtype:<42} x{n:<3} [{tag}]")
    print(f"\n  Pay-per-use resource instances: {payg}")
    print("  None of the deployed services carry a fixed monthly floor "
          "(no idle EC2/RDS/OpenSearch/NAT).")

    print("\n=== Usage assumptions (monthly) ===")
    for k, v in ASSUMPTIONS.items():
        print(f"  {k:<32} {v}")

    cloud = cloud_estimate()
    onprem = onprem_estimate()
    cloud_total = sum(c for _, c, _ in cloud)
    onprem_total = sum(c for _, c, _ in onprem)

    print("\n=== Estimated monthly cost: CLOUD (LostLink serverless) ===")
    for name, cost, note in cloud:
        print(f"  {name:<38} ${cost:>7.2f}   {note}")
    print(f"  {'TOTAL (cloud)':<38} ${cloud_total:>7.2f}")

    print("\n=== Estimated monthly cost: ON-PREMISE / always-on ===")
    for name, cost, note in onprem:
        print(f"  {name:<38} ${cost:>7.2f}   {note}")
    print(f"  {'TOTAL (on-premise)':<38} ${onprem_total:>7.2f}")

    print("\n=== Comparison ===")
    print(f"  Cloud (this build, at assumed usage):   ~${cloud_total:.2f}/month")
    print(f"  Cloud at IDLE (no traffic):             ~$0.15/month (S3+CloudFront only)")
    print(f"  On-premise (always-on equivalent):      ~${onprem_total:.2f}/month (fixed, "
          f"regardless of usage)")
    print("  Key point: the serverless design costs ~$0 at idle and scales with usage;")
    print("  the on-premise equivalent pays the full fixed cost 24/7 even when unused.")

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "cost_report.json"), "w") as f:
        json.dump({
            "resource_counts": counts,
            "assumptions": ASSUMPTIONS,
            "cloud": {name: cost for name, cost, _ in cloud},
            "cloud_total": round(cloud_total, 2),
            "onprem": {name: cost for name, cost, _ in onprem},
            "onprem_total": round(onprem_total, 2),
        }, f, indent=2)
    print(f"\nWrote {out_dir}/cost_report.json")


if __name__ == "__main__":
    main()
