# LostLink — Operations Runbook

A step-by-step guide to deploying LostLink **into any AWS account from scratch**, running
it, verifying it, and tearing it down. If you are using your own AWS account (not the one
this was originally built in), follow every step — several are account-specific and are
the usual causes of "it didn't work for me."

> The `README.md` is the overview + command reference. This runbook is the ordered
> procedure with the account-specific gotchas called out.

---

## 0. What you are deploying

Six independent CloudFormation stacks (via AWS CDK), all serverless:

```
LostLink-Auth      Cognito user pool + groups
LostLink-Data      DynamoDB tables, S3 photo bucket, SQS match queue (+DLQ)
LostLink-Api       API Gateway HTTP API + Lambda handlers (reports/staff/claims)
LostLink-Matching  SQS-triggered matching worker Lambda (Bedrock + scoring)
LostLink-Notification  SES sender config
LostLink-Frontend  S3 (private) + CloudFront hosting the React app
```

Idle cost is ~$0. See `eval/cost_report.py` for the full breakdown.

---

## 1. Prerequisites (install once)

You need these available in the shell you deploy from (this project was developed in
**WSL Ubuntu**; if you use WSL, install these *inside* WSL, not on the Windows host):

| Tool | Version | Check |
|------|---------|-------|
| AWS CLI v2 | any recent | `aws --version` |
| Node.js + npm | 18+ | `node --version` |
| Python | 3.12+ | `python3 --version` |
| CDK CLI | via `npx cdk` (no global install) | `cd infra && npx cdk --version` |

> Node 18 works but is past CDK's preferred version; Node 20+ is recommended if you can.

---

## 2. Point the project at YOUR AWS account

### 2.1 Configure credentials

```bash
aws configure
# Access key ID / secret from an IAM user (or `aws configure sso` for SSO)
# Default region: pick ONE and use it everywhere (see 2.2)
# Default output: json
```

Confirm it works and note YOUR account id:

```bash
aws sts get-caller-identity      # prints your Account and user/role ARN
```

The deploying identity needs permission to create the services above (for a course
project, `AdministratorAccess` on a dedicated IAM user is simplest).

### 2.2 Choose your region (IMPORTANT)

The default region is `ap-southeast-2` (Sydney), set in `infra/lib/config.ts`. To use a
different region, either edit that file or export an override before every command:

```bash
export CDK_DEFAULT_REGION=us-east-1        # example
aws configure set region us-east-1
```

Pick a region where **Amazon Bedrock** offers the models you need (see step 4). Keep the
CLI region and CDK region the same, or you will deploy to one place and look in another.

### 2.3 The CloudFront URL is hard-coded — update it after first frontend deploy

`infra/lib/config.ts` has a `cloudFrontUrl` default from the original account. Yours will
differ. It is only used as a link inside notification emails, so it is not critical, but
after your first `LostLink-Frontend` deploy, copy the real `LostLink-CloudFrontUrl` output
into that file (or export `CLOUDFRONT_URL=...`) and redeploy `LostLink-Matching` so emails
link to your app.

---

## 3. Install dependencies

```bash
cd infra && npm install && cd ..
cd frontend && npm install && cd ..
bash scripts/verify_backend.sh    # creates backend/.venv, installs, runs unit tests
```

`verify_backend.sh` should end with all tests passing. If Python can't create the venv,
install `python3-venv` (`sudo apt-get install -y python3-venv`).

---

## 4. Enable Amazon Bedrock model access (account-specific)

Matching uses two Bedrock models. **Model access is per-account and per-region** and must
be enabled in the console before the worker can call them.

1. AWS Console → **Bedrock** (in YOUR region) → **Model access**.
2. Enable:
   - **Amazon Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`) — REQUIRED for
     matching. Amazon models usually enable instantly.
   - **Anthropic Claude** (a Haiku model) — OPTIONAL, only for the photo→description
     feature. Anthropic models require filling a short **"use case details"** form; access
     can take a few minutes to a few hours.
3. Newer Claude models must be invoked via a **regional inference profile**, not the plain
   model id. Find yours:
   ```bash
   aws bedrock list-inference-profiles --region <your-region> \
     --query "inferenceProfileSummaries[?contains(inferenceProfileId,'claude')].inferenceProfileId" \
     --output text
   ```
   The prefix is regional: `au.` in ap-southeast-2, `apac.`/`us.`/`eu.` elsewhere. Set the
   right id via the `DESCRIBE_MODEL_ID` env var on the worker (or edit
   `backend/pipeline/impl/description.py`'s default) if it differs from the built-in
   `au.anthropic.claude-haiku-4-5-20251001-v1:0`.

**Text matching works with Titan alone.** If you skip Claude, just have staff type a
description when registering found items (photos still upload and display).

> **New-account note:** a brand-new AWS account may return
> `AccessDeniedException: "Your account is currently being verified"` for Bedrock for up
> to ~2 hours. This clears on its own.

---

## 5. Bootstrap CDK (once per account+region)

```bash
cd infra
npx cdk bootstrap aws://<YOUR_ACCOUNT_ID>/<YOUR_REGION>
cd ..
```

---

## 6. Deploy the stacks (in order)

Use the wrapper scripts, or `cdk deploy` directly. Order matters (later stacks reference
earlier ones):

```bash
bash scripts/deploy_auth.sh        # LostLink-Auth
bash scripts/deploy_data.sh        # LostLink-Data
bash scripts/deploy_api.sh         # LostLink-Api

# Build the web app, then deploy hosting:
cd frontend && npm run build && cd ..
bash scripts/deploy_frontend.sh    # LostLink-Frontend  (prints LostLink-CloudFrontUrl)

# Notifications: pass a sender you will verify in step 8:
SENDER_EMAIL=you@youremail.com bash scripts/deploy_notify.sh   # Notification + Api + Matching
```

Or all at once after building the frontend:

```bash
cd infra
SENDER_EMAIL=you@youremail.com npx cdk deploy --all --require-approval never
```

Check everything is up:

```bash
bash scripts/stack_status.sh       # all six should be CREATE_COMPLETE / UPDATE_COMPLETE
```

> The `scripts/*.sh` default to region `ap-southeast-2`; they read `AWS_REGION` if set, so
> `export AWS_REGION=<your-region>` first if you changed regions.

---

## 7. Seed demo users

```bash
bash scripts/seed_demo.sh
# optional real-inbox individual (must be SES-verified — see step 8):
DEMO_EMAIL=you@youremail.com bash scripts/seed_demo.sh
```

Creates:

| Role | Email | Password | Org |
|------|-------|----------|-----|
| Individual | `user@lostlink.example` | `User!Pass123` | — |
| Staff | `staff@lostlink.example` | `Staff!Pass123` | org-nus |
| Staff | `staff2@lostlink.example` | `Staff2!Pass123` | org-other |
| Individual | `user2@lostlink.example` | `User2!Pass123` | — |

---

## 8. Set up email (Amazon SES) — account-specific

SES starts in **sandbox** mode: it will only send **from** and **to** verified addresses.

1. AWS Console → **SES** (YOUR region) → **Identities** → **Create identity** → **Email
   address** → enter the address you'll send *from* → click the link SES emails you.
2. Redeploy so the worker uses it (if you didn't already in step 6):
   ```bash
   SENDER_EMAIL=you@youremail.com bash scripts/deploy_notify.sh
   ```
3. To actually **receive** a match email while in sandbox, the recipient must also be
   verified. Easiest for a demo: verify the same address and use a Gmail `+alias`
   (`you+demo@gmail.com`) as the demo individual's email, or use the mailbox simulator
   `success@simulator.amazonses.com` (accepted but not readable).
4. To email arbitrary recipients: SES console → **Account dashboard** → **Request
   production access** (removes the recipient-verification requirement).

Notifications are **best-effort**: if no verified sender is configured, matching and
claims still work — no email is just sent. So you can skip SES entirely and still demo the
full app.

---

## 9. Verify the deployment (live checks)

Each script creates test data, asserts behaviour, and cleans up:

```bash
bash scripts/verify_data.sh              # DynamoDB repo + presigned S3
bash scripts/verify_api_reports.sh       # individual reporting API
bash scripts/verify_api_staff.sh         # staff inventory + org boundary
bash scripts/verify_matching.sh          # end-to-end async matching (the core loop)
bash scripts/verify_notify.sh            # notification dedup
bash scripts/verify_claims_individual.sh # individual claims + privacy gate
bash scripts/verify_claims_staff.sh      # staff approve → reserve → handover
bash scripts/verify_frontend.sh          # deployed site + config + login
bash scripts/verify_email_live.sh        # REAL email (needs a verified sender)
```

`verify_matching.sh` passing is the key signal that the whole pipeline works in your
account.

---

## 10. Use the app

Open the `LostLink-CloudFrontUrl` (from step 6) in a browser. Walkthrough:

1. Staff window: sign in as `staff@lostlink.example`, register a found item (description +
   `zone-library`).
2. Individual window (incognito): sign in as `user@lostlink.example`, report the matching
   lost item.
3. Wait ~10s, refresh → a potential match appears. Submit a claim with evidence.
4. Staff window: Ownership claims → approve → reserve → handover. The individual now sees
   the item details.

---

## 11. Evaluation, performance, and cost (for the report)

```bash
bash scripts/verify_eval.sh                          # metrics unit tests + sample sweep
cd eval && GENERATE_SOURCE=seed python3 generate.py  # real Titan-embedded dataset (no Claude)
python3 run_eval.py data/generated/dataset.json      # Hit@1 / Recall@5 / MRR per variant
cd ..
bash scripts/loadtest.sh                             # submit/match latency + throughput
cd infra && npx cdk synth --quiet && cd .. && python3 eval/cost_report.py   # cost table
```

Results land in `eval/output/`.

> **Lambda concurrency:** a fresh AWS account often caps total Lambda concurrency at 10
> (vs the normal 1000). Under load the async worker and the API compete for slots and you
> may see HTTP 503. Keep `LT_CONCURRENCY` low, or raise the limit via **Service Quotas →
> Lambda → Concurrent executions**, then set the worker's `reservedConcurrentExecutions`
> in `infra/lib/matching-stack.ts` (see RATIONALE ADR-024).

---

## 12. Tear down (stop all charges)

```bash
cd infra
npx cdk destroy --all
```

Buckets auto-empty on delete and tables use `RemovalPolicy.DESTROY`, so nothing billable
is left behind. (SES identities you verified are free and can be left, or removed in the
SES console.)

---

## 13. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `cdk bootstrap` needed | Run step 5 for your account+region. |
| Deploy fails, wrong region | CLI region ≠ CDK region. Align them (step 2.2). |
| Matching produces no match | Titan model access not enabled (step 4), or the found item has no text (staff uploaded only a photo but Claude access isn't enabled). |
| Worker error `on-demand throughput isn't supported` | Claude needs a regional **inference profile** id, not the plain model id (step 4.3). |
| `MessageRejected: not verified` (email) | SES sandbox: verify sender and recipient, or request production access (step 8). |
| HTTP 503 under load | Account Lambda concurrency limit (step 11 note). |
| Presigned upload returns 307 | Handled in code (regional endpoint + SigV4); if you see it, confirm the bucket region matches your deploy region. |
| Frontend shows old version | CloudFront cache — hard refresh (Ctrl+Shift+R); deploys invalidate `/*` automatically. |
| Scripts hit the wrong region | `export AWS_REGION=<your-region>` before running them. |

---

## 14. Quick reference — one-shot fresh deploy

```bash
# prerequisites installed, credentials configured, region chosen, Bedrock Titan enabled
cd infra && npm install && cd ..
cd frontend && npm install && npm run build && cd ..
bash scripts/verify_backend.sh
cd infra && npx cdk bootstrap && cd ..
SENDER_EMAIL=you@youremail.com  # optional
cd infra && npx cdk deploy --all --require-approval never && cd ..
bash scripts/seed_demo.sh
bash scripts/stack_status.sh
bash scripts/verify_matching.sh      # confirm the core loop
# open the LostLink-CloudFrontUrl output in a browser
```
