# LostLink

A privacy-aware, cross-organisation Lost & Found matching SaaS.

A user reports a lost item once, and the system searches the authorised found-item
inventories of multiple participating organisations using text, location, and time
similarity. When a strong match is found, the user is notified that a partner
organisation may be holding their item, while sensitive item details stay hidden until
ownership is verified by staff.

Built for NUS CS5224 (Cloud Computing) group project.

> **Live app:** https://dyhlyloz80360.cloudfront.net (deployed in `ap-southeast-2`)
> **Public code repository:** _<add your Git URL here before submission>_
> **Deploying into your own AWS account?** Follow [`RUNBOOK.md`](./RUNBOOK.md) — it has the
> ordered procedure plus the account-specific steps (region, Bedrock access, SES, Lambda
> concurrency) and a troubleshooting table.

---

## Repository layout

```
ComputeOnClouds/
├── infra/            AWS CDK (TypeScript) — six independent stacks
│   ├── bin/lostlink.ts        app entry; wires the stacks
│   └── lib/*-stack.ts         Auth, Data, Api, Matching, Notification, Frontend
├── backend/          Python 3.12 Lambda code
│   ├── api/          HTTP API handlers (reports, staff, claims) + shared auth/responses
│   └── pipeline/     Swappable matching-pipeline stages (interfaces + impl) + worker
├── frontend/         React (Vite) SPA (Individual + Staff portals) + styles
├── eval/             Evaluation harness (metrics, ground-truth gen, load test, cost)
├── scripts/          Deploy + live-verification + seed scripts
├── RUNBOOK.md        Step-by-step deploy-to-any-AWS-account procedure + troubleshooting
├── PROGRESS.md       Resumability log — build state, per-task detail
├── RATIONALE.md      Decision record (ADRs) — what / why / alternatives
├── ARCHITECTURE.md   Component interactions (architecture + class level, diagrams)
└── README.md         This file
```

---

## Architecture at a glance

Fully serverless on AWS (see `ARCHITECTURE.md` for full diagrams):

- **Amazon Cognito** — auth; two groups (Individual, Staff); staff carry `organisationId`
- **Amazon API Gateway (HTTP API)** — validates Cognito JWTs; routes to Lambdas
- **AWS Lambda (Python 3.12)** — request handlers + async matching worker
- **Amazon DynamoDB** — items (lost+found), claims, matches, organisations
- **Amazon S3** — item photos (presigned upload) + static frontend hosting
- **Amazon SQS (+DLQ)** — async matching job queue
- **Amazon Bedrock** — Titan Text Embeddings (matching) + Claude (photo → description)
- **Amazon SES** — match/claim email notifications (deduplicated per report-item pair)
- **Amazon CloudFront** — CDN in front of the private frontend bucket (OAC)

The core differentiator is **cross-organisation matching with privacy**: a lost report is
matched against found items across *all* participating organisations, but item details
stay hidden from the claimant until staff verify ownership.

---

## Prerequisites

- An AWS account with credentials configured (`aws configure`)
- Node.js 18+ and npm (CDK app + frontend)
- Python 3.12+ (Lambda code + eval harness)
- AWS CDK CLI via `npx cdk` (installed as an infra dev-dependency; no global install)
- **Amazon Bedrock model access** in your region (auto-enabled on first use; the console
  "Model access" page is retired):
  - Amazon Titan Text Embeddings (`amazon.titan-embed-text-v2:0`) — required for matching
  - Anthropic Claude Haiku 4.5 (`anthropic.claude-haiku-4-5-20251001-v1:0`, invoked via
    the regional inference profile, e.g. `au.` in ap-southeast-2) — for photo→description.
    First-time Anthropic use requires submitting the "use case details" form (reachable
    from the Bedrock **Model catalog → Playground**). The worker's IAM must allow
    `bedrock:InvokeModel` across regions because the profile is cross-region (see ADR-025).
  - Both models are enabled and working on the reference deployment.
- **Amazon SES**: a verified sender identity; in the SES sandbox, verified recipients too
  (or use the mailbox simulator `success@simulator.amazonses.com`)

> **Environment note:** developed inside WSL Ubuntu. The Node/npm/AWS-CLI/CDK toolchain
> must live in WSL. Run commands as
> `wsl -d Ubuntu -- bash -lc "bash ~/ComputeOnClouds/scripts/<script>.sh"`.
> Region defaults to `ap-southeast-2` (set in `infra/lib/config.ts`; override with
> `CDK_DEFAULT_REGION`).

---

## Setup (one-time)

```bash
# 1. AWS CLI + credentials (region ap-southeast-2)
aws configure

# 2. Install deps
cd infra && npm install && cd ..
cd frontend && npm install && cd ..
bash scripts/verify_backend.sh   # creates backend/.venv, installs, runs unit tests

# 3. Bootstrap CDK (once per account/region)
cd infra && npx cdk bootstrap && cd ..

# 4. Bedrock: models auto-enable on first use. Titan is enough for text matching; for
#    photo→description, first-time Anthropic use needs the use-case form (Bedrock →
#    Model catalog → Claude Haiku 4.5 → Playground → run once). See RUNBOOK step 4.

# 5. Verify an SES sender identity (SES console → Identities). In sandbox, also verify
#    any recipient address you want to actually receive mail.
```

## Deploy

Stacks deploy independently in dependency order. Convenience scripts wrap each:

```bash
bash scripts/deploy_auth.sh                         # LostLink-Auth      (Cognito)
bash scripts/deploy_data.sh                         # LostLink-Data      (DynamoDB, S3, SQS)
bash scripts/deploy_api.sh                          # LostLink-Api       (HTTP API + handlers)
bash scripts/deploy_frontend.sh                     # LostLink-Frontend  (build + S3 + CloudFront)
SENDER_EMAIL=you@verified.example bash scripts/deploy_notify.sh   # Notification + wires SES sender
```

Or everything at once (after building the frontend):

```bash
cd frontend && npm run build && cd ..
cd infra && SENDER_EMAIL=you@verified.example npx cdk deploy --all --require-approval never
```

## Seed demo data

Creates the demo users (individual + staff across two orgs) with confirmed passwords:

```bash
bash scripts/seed_demo.sh
# optional: also create an individual whose email is a real SES-verified inbox
DEMO_EMAIL=you@verified.example bash scripts/seed_demo.sh
```

Demo accounts:

| Role | Email | Password | Org |
|------|-------|----------|-----|
| Individual | `user@lostlink.example` | `User!Pass123` | — |
| Individual | `user2@lostlink.example` | `User2!Pass123` | — |
| Staff | `staff@lostlink.example` | `Staff!Pass123` | org-nus |
| Staff | `staff2@lostlink.example` | `Staff2!Pass123` | org-other |

## Run the frontend

Open the CloudFront URL (the `LostLink-CloudFrontUrl` stack output) and sign in with a
demo account. Walkthrough:

1. As **staff**, register a found item (e.g. "black leather wallet, red stripe", zone
   `zone-library`).
2. As an **individual** (separate browser/incognito), report the matching lost item.
3. Wait ~10s; refresh — a **potential match** appears (details hidden). Submit a claim
   with evidence.
4. As **staff**, open Ownership claims → approve → reserve → handover. The claimant now
   sees the item details.

Local dev: `cd frontend && npm run dev` (fetches `/config.json`; point it at the deployed
API by serving a local config).

## Run tests

```bash
# Backend + pipeline unit tests (offline, no AWS)
bash scripts/verify_backend.sh          # pipeline smoke tests
cd backend && . .venv/bin/activate && python3 -m pytest -q   # full suite (52 tests)

# Live integration checks against the deployed stacks (each self-cleans):
bash scripts/verify_data.sh              # DynamoDB repo + presigned S3
bash scripts/verify_api_reports.sh       # individual reporting API (auth, ownership)
bash scripts/verify_api_staff.sh         # staff inventory (org boundary, roles)
bash scripts/verify_matching.sh          # end-to-end async matching (text)
bash scripts/verify_photo_match.sh       # photo → Claude description → embed → match
bash scripts/verify_notify.sh            # notification dedup (exactly-once)
bash scripts/verify_claims_individual.sh # individual claims + privacy gate
bash scripts/verify_claims_staff.sh      # staff review → approve → reserve → handover
bash scripts/verify_frontend.sh          # deployed site + config + login
bash scripts/verify_email_live.sh        # REAL email send (needs a verified sender)
```

## Run the evaluation harness

```bash
bash scripts/verify_eval.sh                         # eval unit + sanity tests + sample sweep

# Generate a real Titan-embedded dataset (Claude generation is optional):
cd eval && GENERATE_SOURCE=seed python3 generate.py # uses hand-authored seed pairs
python3 run_eval.py data/generated/dataset.json     # Hit@1 / Recall@5 / MRR per variant

# Performance + cost (Task 14):
bash scripts/loadtest.sh                            # submit/match latency + throughput
cd infra && npx cdk synth --quiet && cd .. && \
  python3 eval/cost_report.py                       # billable resources + cloud-vs-onprem
```

Outputs land in `eval/output/` (`metrics.{csv,json}`, `loadtest.json`, `cost_report.json`).

## Teardown

```bash
cd infra && npx cdk destroy --all
```

DynamoDB tables and S3 buckets use `RemovalPolicy.DESTROY` with `autoDeleteObjects`, so
teardown is clean and leaves no lingering billable resources.

---

## Code explanation

### Backend — modular matching pipeline

The matching backend is built around **swappable stages behind interfaces**
(`backend/pipeline/interfaces.py`), so scoring, retrieval, description generation,
embedding, notification and storage can each be replaced without touching the rest. The
`MatchWorker` depends only on the interfaces; `factory.py` wires concrete implementations
from environment variables.

| Stage (interface) | Implementation | Swap by |
|-------------------|----------------|---------|
| `DescriptionSource` | `ClaudeDescriptionSource` (photo→text, or typed) | env `DESCRIPTION_SOURCE` |
| `Embedder` | `TitanEmbedder` (text vector; image slot reserved) | env `EMBEDDER` |
| `CandidateRetriever` | `BruteForceRetriever` (`AnnRetriever` stub for scale) | env `RETRIEVER` |
| `Scorer` | `BlendedScorer` (weighted text+location+time; pure) | env `SCORER` |
| `ProfileSelector` | `DefaultProfileSelector` (weights/threshold from env) | env `PROFILE_SELECTOR` |
| `Notifier` | `SesNotifier` (SES + per-pair dedup) | env `NOTIFIER` |
| `ItemRepository` | `DynamoItemRepository` | env `REPOSITORY` |

The `Scorer` is a **pure function** (no AWS deps) so the evaluation harness imports it
directly to sweep weights offline. Matching weights and the notification threshold are
injected as Lambda env vars (`WEIGHT_TEXT/IMAGE/LOCATION/TIME`, `MATCH_THRESHOLD`).

Design decisions and their alternatives are recorded as ADRs in `RATIONALE.md`
(24 entries), and all component interactions are diagrammed in `ARCHITECTURE.md`.

### API handlers (`backend/api/`)

- `auth.py` — builds a `Principal` (id, email, group, org) **only** from validated JWT
  claims; role/org are never trusted from the request body (the privacy core).
- `reports_handler.py` (individual), `staff_handler.py` (organisation inventory),
  `claims_handler.py` (individual + staff claim workflow), `claim_state.py` (shared claim
  state machine + the `details_visible` privacy gate).

### Infra (`infra/lib/`)

Six independent CDK stacks with cross-stack references (see `ARCHITECTURE.md §1.4`):
`AuthStack`, `DataStack` (tables + buckets + SQS), `ApiStack`, `MatchingStack` (worker),
`NotificationStack`, `FrontendStack`.

### Frontend (`frontend/src/`)

React SPA; the one deliberately-clean seam is `api.ts` (the `ApiClient`). `config.ts`
loads runtime config from `/config.json` (written by CDK at deploy time), `auth.ts` wraps
Cognito. `IndividualPortal` and `StaffPortal` are role-gated on the `cognito:groups` claim.

### Working documents

- `PROGRESS.md` — per-task status, deployed resource IDs, how to verify, deviations.
- `RATIONALE.md` — architecture decision records (ADR-001…024).
- `ARCHITECTURE.md` — architecture- and class-level interaction diagrams + contracts.
