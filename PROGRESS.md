# LostLink — Build Progress

> Resumability log. A fresh session should read this file first to learn where the
> build stands, what is deployed, and how to verify the current state before
> continuing. Update this at the end of every task and whenever a task is left
> partially complete.

## How to resume

1. Read this file top to bottom.
2. Read `RATIONALE.md` for why decisions were made, and `ARCHITECTURE.md` for how
   components interact.
3. Find the first task below that is not `DONE` and continue from its "Next steps".
4. Run the "Verify current state" commands to confirm reality matches this log.

## Environment

- Project root (WSL): `/home/amritsat/ComputeOnClouds`
- Toolchain lives in **WSL Ubuntu**, not the Windows host. Run build commands via
  `wsl -d Ubuntu -- bash -lc "cd ~/ComputeOnClouds/... && <command>"`.
- Node v18.19.1, npm 9.2.0, Python 3.12.3 (WSL).
- CDK CLI: used via `npx cdk` from `infra/` (installed as a dev dep; no global install).
- Backend Python venv: `backend/.venv` (created by `scripts/verify_backend.sh`).
- AWS CLI: **installed** (v2.37.6) at `~/.local/bin/aws`. Credentials configured for
  IAM user `lostlink-dev`, account `757868239668`.
- AWS region: **ap-southeast-2** (Sydney) — chosen for free-tier usage. Set in the CLI
  config and `infra/lib/config.ts`. Override with `CDK_DEFAULT_REGION`.
- CDK **bootstrapped** in `aws://757868239668/ap-southeast-2`.
- **Bedrock caveat:** model availability varies by region — confirm Claude + Titan Text
  Embeddings exist in ap-southeast-2 before Task 7 (else configure a cross-region
  Bedrock call in the worker only).
- **Node version caveat:** CDK warns Node 18 support ended 2025-11-30. Deploy works
  today; upgrading WSL Node to 20+ is still advisable.

## Deployed AWS state

_Nothing deployed yet._ `cdk synth` succeeds locally and produces six stack templates
in `infra/cdk.out/`. No `cdk bootstrap`/`deploy` has run (needs AWS credentials + AWS
CLI, not yet installed in WSL).

| Stack | Deployed? | Region | Key resources / notes |
|-------|-----------|--------|-----------------------|
| AuthStack | **DEPLOYED** | ap-southeast-2 | UserPoolId `ap-southeast-2_iIvinG1MP`, ClientId `14vnbms968po4g5358nlsmb8jq`; seed verified live |
| DataStack | **DEPLOYED** | ap-southeast-2 | Items/Claims/Matches/Organisations tables; photos bucket (frontend bucket moved to FrontendStack); repository live-verified |
| ApiStack | **DEPLOYED** | ap-southeast-2 | HTTP API `https://1eqi1p0l9j.execute-api.ap-southeast-2.amazonaws.com`; JWT authorizer; reports (T4) + staff inventory (T5) handlers live-verified |
| MatchingStack | **DEPLOYED** | ap-southeast-2 | Worker Lambda consuming SQS (queue+DLQ in DataStack); end-to-end matching live-verified (score 0.927) |
| NotificationStack | **DEPLOYED** | ap-southeast-2 | SES sender identity (placeholder until real SENDER_EMAIL); dedup live-verified. Real email send needs a verified sender (user action). |
| FrontendStack | **DEPLOYED** | ap-southeast-2 | CloudFront `https://dyhlyloz80360.cloudfront.net`; owns the frontend bucket; config.json + login smoke-verified |

Manual steps performed (Bedrock access, SES verification, etc.): _none yet._

## Task status

Legend: `TODO` / `WIP` / `DONE`

| # | Task | Status |
|---|------|--------|
| 1 | Project scaffolding, CDK bootstrap, and working files | DONE |
| 2 | Authentication with Cognito and two roles | DONE (deployed + seed verified) |
| 3 | Data model and storage | DONE (deployed + repository live-verified) |
| 4 | Core API — individual lost-item reporting | DONE (deployed + integration-verified) |
| 5 | Core API — staff inventory management | DONE (deployed + integration-verified) |
| 6 | Frontend shell with auth and both portals | DONE (deployed + smoke-verified; browser render unclicked) |
| 7 | Pipeline stages — DescriptionSource and Embedder | DONE (unit + live Bedrock verified) |
| 8 | Async matching pipeline (SQS + worker) with pluggable CandidateRetriever | DONE (deployed + end-to-end verified) |
| 9 | Pipeline stages — Scorer and ProfileSelector (retrieval-agnostic) | DONE (hardened + 15 tests + purity proven) |
| 10 | Notifier stage — SES with deduplication | DONE (dedup live-verified; real email send pending verified sender) |
| 11 | Claims workflow — individual side | DONE (deployed + integration + privacy verified) |
| 12 | Claims workflow — staff side and handover | DONE (deployed + full-lifecycle live verified) |
| 13 | Evaluation harness and ground-truth data | DONE (offline + live-embedded; Claude gen gated) |
| — | Frontend restyle (CSS) | DONE (styles.css, cards/topbar/badges; redeployed) |
| — | SES real email delivery | DONE (verified sender + live email verified) |
| — | Code comments pass | DONE (frontend api/portals + eval metrics enriched) |
| — | RUNBOOK.md (deploy-to-any-account guide) | DONE (14-section runbook + troubleshooting) |
| 14 | System performance and cost measurement tooling | DONE (load test + cost report, live numbers) |
| 15 | Finalisation — working files and reproducible seed | DONE |

## AWS access (RESOLVED)

AWS CLI v2 installed in WSL and credentials configured (IAM user `lostlink-dev`, account
`757868239668`, region `ap-southeast-2`). CDK bootstrapped. Live deploy + verification
are now possible and are being run as each stack lands.

Helper scripts:
- `scripts/aws_check.sh` — sets region ap-southeast-2 and prints caller identity.
- `scripts/deploy_auth.sh` — bootstrap (idempotent) + deploy LostLink-Auth.
- `scripts/seed_auth.sh` — seed + JWT-claim verification.

## Current work-in-progress detail

**Task 1 — DONE.** Monorepo scaffolded and verified.

**Task 2 — DONE (deployed + live-verified).**
- `infra/lib/auth-stack.ts`: Cognito user pool (email sign-in + email verification
  code), `custom:organisationId` attribute, groups `Individual` + `Staff`, public SPA
  app client (USER_PASSWORD + SRP), outputs `LostLink-UserPoolId` /
  `LostLink-UserPoolClientId`. `GROUP_INDIVIDUAL`/`GROUP_STAFF` exported for reuse.
- Deployed to ap-southeast-2. UserPoolId `ap-southeast-2_iIvinG1MP`, ClientId
  `14vnbms968po4g5358nlsmb8jq`.
- Live seed verification (`scripts/seed_auth.sh`): Staff user → `cognito:groups=['Staff']`,
  `custom:organisationId=org-nus`; Individual user → `cognito:groups=['Individual']`,
  no org. Both confirmed from decoded ID tokens.
- Seed users: `staff@lostlink.example` / `Staff!Pass123` (org-nus),
  `user@lostlink.example` / `User!Pass123`.

What exists now:
- `/infra` — CDK TS app with six independent stacks (Auth, Data, Api, Matching,
  Notification, Frontend) as valid empty stacks; `bin/lostlink.ts` wires them;
  `lib/config.ts` holds region + match weights/thresholds. `cdk synth` produces all
  six templates.
- `/backend/pipeline` — six stage interfaces (DescriptionSource, Embedder,
  CandidateRetriever, Scorer, ProfileSelector, Notifier) + ItemRepository, shared
  `models.py`, stub implementations (each raises NotImplementedError pointing at its
  task), a `factory.py` wiring impls from env vars, and a `worker.py` orchestrator
  skeleton. 7 smoke tests pass.
- `/frontend` — minimal Vite React app (placeholder), ready for Task 6. Deps NOT yet
  installed.
- `/eval` — placeholder README + requirements, ready for Tasks 13-14.
- `scripts/verify_backend.sh` — sets up `backend/.venv`, installs dev deps, runs tests.

**Task 3 — DONE (deployed + live-verified).**
- `infra/lib/data-stack.ts`: Items table (PK itemId; GSIs by-owner, by-org-type,
  by-type), Claims table (GSIs by-owner=claimantId, by-org-type=organisationId),
  Matches table (PK queryItemId, SK candidateItemId, `notified` dedup flag),
  Organisations table (PK organisationId). Photos bucket (private, CORS, presigned) +
  frontend bucket. All PAY_PER_REQUEST, RemovalPolicy.DESTROY, autoDeleteObjects.
  Exposes public readonly table/bucket handles + outputs (LostLink-ItemsTableName etc.).
  GSI name constants on DataStack (GSI_BY_OWNER/GSI_BY_ORG_TYPE/GSI_BY_TYPE).
- Deployed resources: tables LostLink-Items / LostLink-Claims / LostLink-Matches /
  LostLink-Organisations; buckets lostlink-photos-757868239668 /
  lostlink-frontend-757868239668.
- `backend/pipeline/impl/ddb_mapping.py`: canonical Item<->DDB encoder (vectors as JSON,
  floats as Decimal, derived orgType, createdAt preservation on re-save).
- `backend/pipeline/impl/repository.py`: DynamoItemRepository (get/save/list_candidates/
  save_match), reads ITEMS_TABLE / MATCHES_TABLE env vars, lazy boto3 import so the pure
  package still imports without boto3.
- Live verification (`scripts/verify_data.{py,sh}`): 17 checks pass — item round-trips,
  vector/photo/org preservation, cross-org + org-scoped retrieval (boundary enforced),
  match persistence with notified=false, presigned PUT/GET upload+download.
- **S3 307 gotcha:** presigned URLs must use the regional endpoint + SigV4 (baked into
  verify_data.py; request Lambdas in Tasks 4/5 must do the same).

**Task 4 — DONE (deployed + integration-verified).**
- `infra/lib/api-stack.ts`: HTTP API v2 (`LostLink-Api`), Cognito `HttpUserPoolAuthorizer`
  bound to the AuthStack pool/client. Exposes public `httpApi` + `authorizer` so Tasks
  5/11/12 attach more routes. `pythonHandler()` helper bundles `backend/` (excludes
  .venv/tests/__pycache__) as a Python 3.12 Lambda. Reports Lambda gets ITEMS_TABLE +
  PHOTOS_BUCKET env, grantReadWrite on table + photos bucket.
- Routes (all behind authorizer): POST /uploads, POST /reports, GET /reports,
  GET|PATCH|DELETE /reports/{itemId}.
- API URL: `https://1eqi1p0l9j.execute-api.ap-southeast-2.amazonaws.com` (output
  LostLink-ApiUrl).
- Backend `api/` package: auth.py (Principal from JWT claims — sub/email/groups/
  custom:organisationId; require_individual/require_staff; NEVER trusts body for
  role/org), responses.py (respond/error/parse_body/route_key/path_param, Decimal-safe
  JSON, CORS), s3urls.py (presigned PUT/GET with regional endpoint + SigV4 — the 307
  fix), reports_handler.py (routes on routeKey; create/list/get/edit/withdraw + upload
  url; ownership enforced by ownerId==sub; text+location mandatory, photo optional;
  enqueues to MATCH_QUEUE_URL if set — absent until Task 8).
- Live verification (`scripts/verify_api_reports.{py,sh}`): 15 checks pass — typed-desc
  create, photo create (presigned upload first), list, get, edit(resets pending_match),
  cross-user 403 (GET+PATCH), unauth 401, validation 400s, withdraw. Backend units 7 pass.
- Created a 2nd individual seed user for the cross-user test: user2@lostlink.example /
  User2!Pass123.

**Task 15 — DONE. PROJECT COMPLETE (all 15 tasks + frontend restyle + real email).**
- README.md finalised: live app URL + repo-URL placeholder, full setup/deploy/seed/run/
  test/eval/teardown, code-explanation section (modular stage table + swap-by-env, API
  handlers, infra stacks, frontend seams, working-docs index).
- scripts/seed_demo.sh: one-command demo seed (4 users across 2 orgs; optional DEMO_EMAIL
  real-inbox individual). Verified live.
- Final reproducibility pass: 52 backend tests + 8 eval tests pass; `cdk synth` clean; all
  6 stacks UPDATE_COMPLETE live.
- REMAINING USER-OPTIONAL ITEMS (not blockers; everything works without them):
  (1) add the public Git repo URL to README before submission;
  (2) Claude photo→description needs the Anthropic use-case form in Bedrock (text matching
      unaffected); SES sender satpathy.amrit@u.nus.edu verified + real email proven.
- Run `cd infra && npx cdk destroy --all` when finished to stop all charges.

**Task 14 — DONE (load test + cost report, live numbers).**
- `eval/loadtest.py` + `scripts/loadtest.sh`: seeds N found items, submits N lost reports
  (concurrency-limited), measures submit latency (p50/p95/max), end-to-end match latency
  (submit->Match row visible), submit throughput; writes eval/output/loadtest.json;
  cleans up. post() has retry+backoff on 5xx. Tunables LT_REPORTS/LT_INVENTORY/
  LT_CONCURRENCY. LIVE RESULT (15 reports/15 inventory, conc 2): 15/15 matched, submit
  p50 0.78s/p95 0.92s, e2e match p50 6.5s/p95 8.4s/mean 6.5s, throughput 2.6 rps.
- `eval/cost_report.py`: reads infra/cdk.out/*.template.json, counts billable resources
  (45 pay-per-use instances, NO fixed-floor services), + monthly cost estimate CLOUD vs
  ON-PREM under stated assumptions. RESULT: cloud ~$2.48/mo at assumed usage (~$0.15 idle)
  vs on-prem ~$155/mo always-on. Writes eval/output/cost_report.json. Bedrock (Claude
  desc ~$1.50) is the main variable cost; everything else free-tier/pennies.
- **KEY FINDING (ADR-024): account Lambda concurrency limit = 10** (fresh-account cap, not
  1000). Async worker consuming SQS slots collides with API calls -> API GW 503 under
  load. Tried worker reservedConcurrentExecutions=3 -> AWS REJECTS (requires >=10
  unreserved to remain at this cap) -> stack rolled back, reverted. Load test runs within
  the cap (low concurrency + retry). On a normal account: raise the limit (Service Quotas)
  and set worker reservedConcurrentExecutions. This is a real, report-worthy finding.

**Task 13 — DONE (harness verified offline + on live Titan-embedded data).**
- `eval/metrics.py` (PURE): RankedQuery dataclass; hit_at_1, recall_at_k, mrr (over
  truth!=None queries), notification_metrics(threshold) -> alert_precision,
  false_alert_rate (over truth=None queries), missed_notification_rate, alert_burden.
- `eval/harness.py`: imports PURE BlendedScorer from backend/pipeline (sys.path); VARIANTS
  = text_only / text_location / text_location_time; rank_variant scores each lost vs all
  found + ranks; evaluate() -> VariantReport per variant. load_dataset.
- `eval/generate.py`: generate_dataset (GENERATE_SOURCE=claude default, seed fallback) +
  embed_dataset (Titan live). Claude path builds lost/found pairs + distractors; auto
  FALLS BACK to seed on any Claude error. main() writes eval/data/generated/dataset.json.
  Env EVAL_PAIRS/EVAL_DISTRACTOR_FOUND/EVAL_DISTRACTOR_LOST.
- `eval/seed_pairs.py`: 15 hand-authored lost/found description pairs + 10 distractor-found
  + 5 distractor-lost (Claude-free source so a real Titan-embedded dataset is producible
  without Anthropic access).
- `eval/run_eval.py`: loads dataset, evaluate at MATCH_THRESHOLD (0.7), prints table +
  writes eval/output/metrics.{csv,json}.
- `eval/data/sample_dataset.json`: tiny committed hand-vectored set (4 lost/4 found) for
  offline sanity — NO Bedrock needed.
- Tests: eval/tests/test_metrics.py (5) + test_harness_sample.py (3) = 8 pass. eval/
  pyproject.toml (pythonpath . + ../backend).
- LIVE: generated a real dataset (20 lost / 25 found) via seed pairs + LIVE Titan
  embeddings, ran run_eval.py. All variants Hit@1=Recall@5=MRR=1.0 (semantically distinct
  pairs). Notification metrics discriminate: on the sample, text_only false_alert_rate=1.0
  vs text_location 0.0 (location suppresses the distractor's false alert — demonstrates
  contextual signals help). On round-robin-zoned synthetic data the effect inverts (shared
  zones inflate location false alerts) — honest finding; real co-location data would favor
  location. Metrics harness works correctly either way.
- **NEW BEDROCK GATE:** Claude generate now returns ResourceNotFoundException "Model use
  case details have not been submitted for this account. Fill out the Anthropic use case
  details form." This appeared after Task 7 (Claude vision worked then). Blocks Claude
  DATASET GENERATION only. Titan embedding still works. Workaround: GENERATE_SOURCE=seed.
  USER ACTION to re-enable Claude generation: submit the Anthropic use-case form in the
  Bedrock console. (NOTE: this may also now affect the deployed matching worker's
  photo->description Claude call — verify at Task 15; text-only matching unaffected since
  reports carry typed descriptions.)

**Task 12 — DONE (deployed + full-lifecycle live verified). PRODUCT LOOP COMPLETE.**
- `backend/api/claims_handler.py` STAFF routes added: GET /org/claims (claims by-org-type
  GSI on principal.organisation_id; _staff_claim_view shows evidenceText/keys + found item),
  GET /org/claims/{id}, POST /org/claims/{id}/{request-info|approve|reject|reserve|handover}
  via _staff_transition(action) using cs.next_state. _load_org_claim enforces
  claim.organisationId==principal.organisation_id else 403. On reserve -> found item
  status "reserved"; on handover -> "closed" (_set_item_status). _notify_claimant emails
  claimant on each decision (privacy-safe, no item details; best-effort, needs verified
  sender). notify_withdrawn_claims(org, candidateId) module-level: rejects active claims on
  a withdrawn found item + notifies (skips terminal states).
- `backend/api/staff_handler.py` _withdraw_item now imports+calls notify_withdrawn_claims
  and returns claimsAffected.
- ApiStack: ClaimsFn +SENDER_EMAIL env + ses:SendEmail IAM; +7 staff routes /org/claims*.
  StaffFn +CLAIMS_TABLE env + claimsTable RW + ses:SendEmail (withdrawal notifications).
  Added `import iam`. Deployed UPDATE_COMPLETE.
- Tests: test_claims_staff_t12.py (6, FakeTable: approve->reserve->handover w/ item
  status side effects, reject, invalid-transition 409, cross-org 403, notify_withdrawn
  rejects-active-only). 50 total pass.
- LIVE integration (scripts/verify_claims_staff.{py,sh}, 15 checks): DJI drone claim ->
  staff sees evidence; staff B 403 on GET+approve; approve->reserve->handover with found
  status available->reserved->closed; claimant sees item ONLY after approval; approve-
  after-handover 409; reject path; withdrawal rejects active claim (claimsAffected=1,
  claimant sees rejected).
- Frontend: api.ts +StaffClaim + listOrgClaims/claimAction. StaffPortal.tsx +ClaimReview
  (claims list w/ evidence + contextual action buttons request-info/approve/reject/reserve/
  handover per state). Built ~248KB, FrontendStack redeployed UPDATE_COMPLETE.
- FULL PRODUCT LOOP now proven live: report -> cross-org match -> notify -> claim+evidence
  -> staff verify -> approve -> reserve -> handover, privacy enforced throughout.

**Task 11 — DONE (deployed + integration + privacy verified).**
- `backend/api/claim_state.py`: SHARED state machine (Tasks 11+12). States submitted /
  info_requested / approved / rejected / reserved / handed_over / cancelled. TRANSITIONS
  map {action -> (allowed_from, result, actor)}. next_state() raises InvalidTransition.
  can_transition, actor_for, details_visible (privacy gate: found details visible only
  when approved/reserved/handed_over). TERMINAL = rejected/handed_over/cancelled.
- `backend/api/claims_handler.py`: INDIVIDUAL routes (staff added T12). GET /matches
  (my lost reports via by-owner GSI -> their Matches rows; returns score+org+message
  ONLY, NO found description/photo), POST /claims/uploads (evidence presigned),
  POST /claims (validates report is mine + match exists; creates claim state=submitted;
  claimId, claimantId=sub, claimantEmail, query/candidate ids, org, evidenceText/Keys,
  messages[]), GET /claims (by-owner GSI on claimantId), GET /claims/{id} (own only),
  POST /claims/{id}/respond (info_requested->submitted, append message+evidence),
  POST /claims/{id}/cancel. _claim_view reveals found item ONLY if details_visible(state).
- ApiStack: ClaimsFn Lambda (env ITEMS/MATCHES/CLAIMS_TABLE + PHOTOS_BUCKET; items RW,
  matches read, claims RW, photos RW) + routes GET /matches, POST /claims/uploads,
  POST /claims, GET /claims, GET|respond|cancel /claims/{claimId}. ApiStack exposes
  public claimsFn + claimsIntegration (declared with `!`) for T12 to add staff routes.
- Tests: test_claim_state_t11.py (6, 45 total pass): valid individual+staff transitions,
  invalid raise, terminal states no outgoing, details_visible privacy gate, actor_for.
- LIVE integration (scripts/verify_claims_individual.{py,sh}, 14 checks): Kanken backpack
  pair -> match; /matches hides the secret description; cross-user claim 403; claim
  submitted; no-evidence 400; item HIDDEN while submitted (secret not leaked in claim
  view); respond-from-submitted 409; cancel->cancelled; respond-after-terminal 409.
- Frontend: api.ts +MatchSuggestion/Claim types + listMatches/submitClaim/listClaims/
  getClaim/cancelClaim. IndividualPortal.tsx +MatchesAndClaims component (shows
  suggestions w/ confidence%, submit claim via prompt, my claims w/ status, item hidden
  until approved). Rebuilt (bundle ~247KB) + FrontendStack redeployed.
- PRIVACY CORE fully enforced: found item details never exposed to claimant until staff
  approve. Proven live.

**Task 10 — DONE + REAL EMAIL DELIVERY NOW LIVE-VERIFIED.**
- SES sender VERIFIED: satpathy.amrit@u.nus.edu (verified in SES console, ap-southeast-2,
  status Verified=true). Deployed as SENDER_EMAIL to worker + ClaimsFn + StaffFn via
  scripts/deploy_notify.sh (default SENDER_EMAIL=satpathy.amrit@u.nus.edu). config.ts also
  added cloudFrontUrl (https://dyhlyloz80360.cloudfront.net) -> worker CLOUDFRONT_URL env
  so the match email links to the app.
- NotificationStack NO LONGER creates a CDK ses.EmailIdentity (removed) — identities are
  verified MANUALLY in the SES console; a CDK identity for an already-verified address
  would conflict. Stack just records senderEmail. Removed unused `ses` import.
- BUG FIXED (found when user asked to test): placeholder sender caused the worker to call
  SES, get MessageRejected, throw, fail the SQS msg, and (having already claimed
  notified=true) leave matches flaky. Fix (ADR-023): SesNotifier._can_send() skips send +
  does NOT claim when sender is missing/`.example` or recipient not an email; actual send
  wrapped in try/except (best-effort, non-fatal). claims_handler._notify_claimant same
  `.example` guard. Redeployed Matching+Api. Re-verified matching + both claims flows PASS.
- LIVE EMAIL PROVEN: scripts/verify_email_live.{py,sh} — demo individual user whose email
  IS the verified NUS address, matching pair -> worker log `[notify] emailed
  satpathy.amrit@u.nus.edu`, match notified=true. (SES SentLast24Hours counter LAGS/
  unreliable for immediate assert — script now asserts on the worker log line instead.)
  SES still in SANDBOX so recipients must be verified; the demo user uses the verified
  NUS address. To email arbitrary recipients: request SES production access.
- Tests now 52 pass (added test_no_send_when_sender_is_placeholder +
  test_ses_send_failure_is_non_fatal; updated no-send tests: no claim consumed when send
  impossible so email can go out later once sender verified).

**Task 10 — (superseded above) dedup live-verified; actual email delivery pending a verified SES sender.**
- `infra/lib/notification-stack.ts`: NotificationStack creates an SES EmailIdentity for
  the sender ONLY when a real address is configured (skips the `no-reply@lostlink.example`
  placeholder so deploy doesn't fail). Output LostLink-SenderEmail. Exposes .senderEmail.
- config.ts: added `senderEmail` (from SENDER_EMAIL env, default placeholder).
- MatchingStack: worker gets SENDER_EMAIL env + ses:SendEmail/SendRawEmail IAM (resource *).
- `backend/pipeline/impl/notifier.py` SesNotifier IMPLEMENTED (replaced log stub): reads
  MATCHES_TABLE, SENDER_EMAIL, CLOUDFRONT_URL. notify(recipient, match): _claim() does a
  DynamoDB conditional update on the Matches row (SET notified=:true if
  attribute_not_exists(notified) OR notified=:false) -> exactly-once claim; only sends
  SES email if claim won AND sender set AND recipient looks like an email. Email body
  HIDES item details (privacy) + links CLOUDFRONT_URL. ConditionalCheckFailed -> dedup skip.
- owner_email plumbed: Item.owner_email field + ddb_mapping ownerEmail; reports_handler +
  staff_handler set owner_email=principal.email at creation; worker _maybe_notify passes
  lost.owner_email (falls back to owner_id).
- Tests: test_notifier_t10.py (5): first send+claim, second deduped (1 send / 2 claim
  attempts), no-send-when-sender-unset (still claims), no-send-when-recipient-not-email,
  email body hides found-1 id + says "hidden" + includes app url. 39 total pass.
- LIVE dedup verify (scripts/verify_notify.{py,sh}): matching pair -> match row +
  ownerEmail stored; re-drove the SQS job TWICE -> notified stays True, idempotent, no
  errors. Claim-then-send ordering confirmed (notified=True even though placeholder
  sender skips actual send).
- **USER ACTION NEEDED for real email:** verify a real SES sender. Redeploy with
  `SENDER_EMAIL=you@example.com bash scripts/deploy_notify.sh`, click the SES link, then
  run scripts/verify_notify_email.sh. Recipients in sandbox must be verified OR use
  success@simulator.amazonses.com. I could not do this (no inbox to click the link).

**Task 9 — DONE (hardened + comprehensively tested; no redeploy needed).**
- Scorer/ProfileSelector were implemented in Task 8 (ADR-020) and are unchanged in logic;
  Task 9 locks behaviour with tests and proves purity.
- `backend/tests/test_scorer_t9.py` (15 tests): cosine maps to [0,1] (identical 1.0,
  opposite 0.0, orthogonal 0.5), cosine None on missing/mismatched/zero-norm, spatial
  zone match (1.0/0.1/None), temporal decay (1.0 same, 0.5 at 72h half-life, None
  missing), full text+location+time match = 1.0, present-only normalisation (absent
  components dropped from denominator), zero when no weight, IMAGE-TERM HOOK proven
  (w_image 0->inert, raising it changes score → Option 2 works with no code change),
  image ignored when only one side has image vec, weight-sweep monotonic between two
  signals, source-agnostic determinism (repeat calls equal), all-absent -> 0, profile
  reads env, profile defaults, threshold boundary (>= inclusive). 34 tests total pass.
- **PURITY PROVEN** (`scripts/verify_scorer_pure.sh`): scorer/profile/models import + run
  in a bare venv with NO deps installed, under an import guard that raises if boto3 is
  imported. Score computed correctly (0.9986). This is what the Task 13 eval harness
  needs (import the pure Scorer, sweep weights in memory, no AWS).
- No infra change; LostLink-Matching not redeployed (deployed scorer == tested scorer).

**Task 8 — DONE (deployed + end-to-end live-verified).**
- SQS `LostLink-match-jobs` + DLQ `LostLink-match-dlq` (maxReceiveCount 3, visibility
  180s) created in **DataStack** (not MatchingStack) so producers (Api Lambdas) +
  consumer (worker) share one queue with no cross-stack cycle — RATIONALE ADR-019.
  Output LostLink-MatchQueueUrl; DataStack exposes .matchQueue/.matchDlq.
- ApiStack: ReportsFn + StaffFn now get MATCH_QUEUE_URL env + matchQueue.grantSendMessages.
  So create/edit enqueues jobs (previously skipped).
- MatchingStack: MatchWorker Lambda (PYTHON_3_12, handler pipeline.lambda_worker.handler,
  512MB/30s, code asset = backend/ excluding api+tests+venv). Env: ITEMS_TABLE,
  MATCHES_TABLE, PHOTOS_BUCKET, BEDROCK_REGION, RETRIEVER, WEIGHT_* + MATCH_THRESHOLD
  from config.match. SqsEventSource(batchSize 5, reportBatchItemFailures). IAM: items+
  matches RW, photos read, queue consume, bedrock:InvokeModel on foundation-model/* +
  inference-profile/* (needed for the au. Claude profile + underlying FM).
- backend/pipeline/lambda_worker.py: unwraps SQS records, partial-batch-response
  (batchItemFailures) so one bad record DLQs without failing the batch.
- backend/pipeline/worker.py handle() IMPLEMENTED: load item, skip withdrawn/closed,
  _ensure_enriched (DescriptionSource if no desc -> Embedder if no text vector -> save),
  retrieve cross-org candidates (OrgScope all_authorised), score each via ProfileSelector
  + Scorer, persist matches >= threshold, _orient so query=lost/candidate=found
  regardless of trigger side, _maybe_notify(owner).
- backend/pipeline/impl/retriever.py BruteForceRetriever IMPLEMENTED (delegates to
  repository.list_candidates). AnnRetriever still stub (ADR-006).
- **Implemented early (originally Task 9) to make the pipeline runnable:**
  impl/scorer.py BlendedScorer (pure: cosine text/image remapped [0,1], spatial
  zone-match decay, temporal exp half-life 72h; weighted avg over PRESENT components,
  absent dropped from normaliser; image term only when both have image vec) and
  impl/profile.py DefaultProfileSelector (reads WEIGHT_TEXT/IMAGE/LOCATION/TIME +
  MATCH_THRESHOLD env, single "text_location_time" profile, image weight 0, multi-profile
  hook reserved). impl/notifier.py SesNotifier is a LOG-ONLY STUB until Task 10.
- Tests: test_worker_t8.py (6: retriever delegate+exclude-self, enrich+persist+orient+
  notify, found-triggers orientation, below-threshold no-match, skip-withdrawn) +
  updated scaffold tests (handle implemented no-ops on empty job; AnnRetriever stub). 19
  total pass.
- LIVE E2E (scripts/verify_matching.{py,sh}): registered a yellow Hydro Flask found item
  + matching lost report via API -> worker cached vectors on both -> Match row lost->found
  org-nus **score 0.927** notified=false; an unrelated umbrella report did NOT match. 9
  checks pass. The core cross-org matching differentiator is proven in production.

**Task 7 — DONE (unit + live Bedrock verified).**
- Bedrock IS available + access GRANTED in ap-southeast-2 (account verification cleared).
- `backend/pipeline/impl/embedder.py` (TitanEmbedder): Titan `amazon.titan-embed-text-v2:0`
  (1024-dim), invoke_model {inputText}, returns VectorMap(text=[...], image=None). Empty
  description -> empty VectorMap (no call). Config: EMBED_MODEL_ID, BEDROCK_REGION.
  Injectable client for tests.
- `backend/pipeline/impl/description.py` (ClaudeDescriptionSource): photo present -> fetch
  from S3 (PHOTOS_BUCKET) -> Claude vision (messages API, base64 image + prompt) ->
  description; no photo -> typed text; empty generation -> fallback to typed. Config:
  DESCRIBE_MODEL_ID, BEDROCK_REGION, PHOTOS_BUCKET. Injectable bedrock+s3 clients.
- **CRITICAL Bedrock finding:** Claude 4.5 Haiku does NOT support on-demand invoke_model;
  requires an inference-profile id. In ap-southeast-2 the correct prefix is `au.` (NOT
  `apac.` for this model). Default model id = `au.anthropic.claude-haiku-4-5-20251001-v1:0`.
  Titan embed uses the plain id `amazon.titan-embed-text-v2:0`. Task 8 worker IAM must
  allow bedrock:InvokeModel on both the model and the inference-profile ARN.
- Unit tests (`backend/tests/test_pipeline_stages_t7.py`, 6 new, mocked Bedrock/S3):
  assert Titan payload {inputText}+model id + vector parse + empty-desc no-call; Claude
  no-photo uses typed text, with-photo builds image+text message and parses content,
  empty-generation fallback, media-type-by-extension. 13 tests total pass.
- Live verify (`scripts/verify_bedrock.py` + `verify_bedrock_vision.sh`): real Titan
  embedding dim=1024 image-slot-empty; real Claude vision described an uploaded test
  image. Both pass. `scripts/check_bedrock.sh` + `list_inference_profiles.sh` +
  `probe_bedrock.py` are diagnostics.

**Task 6 — DONE (deployed + smoke-verified).**
- `frontend/`: React (Vite) app. `config.ts` loads /config.json at runtime; `auth.ts`
  (amazon-cognito-identity-js, USER_PASSWORD) sign in/out + decode groups/org from ID
  token; `api.ts` = the single clean ApiClient (reports + items, presigned photo upload
  via /uploads and /items/uploads); `App.tsx` role-gates on cognito:groups → Individual
  or Staff portal; `Login.tsx`, `IndividualPortal.tsx` (report form + my reports +
  withdraw), `StaffPortal.tsx` (register found item photo-first + inventory search +
  withdraw). Built clean (tsc + vite), bundle ~244KB.
- `infra/lib/frontend-stack.ts`: OWNS the frontend bucket (moved out of DataStack to
  break a cross-stack bucket-policy dependency cycle), CloudFront w/ OAC
  (S3BucketOrigin.withOriginAccessControl, not deprecated S3Origin+OAI), SPA 403/404 ->
  index.html fallback, BucketDeployment of frontend/dist + generated config.json from
  stack values (apiUrl/region/userPoolId/userPoolClientId) + CDN invalidation.
- CloudFront URL: `https://dyhlyloz80360.cloudfront.net` (output LostLink-CloudFrontUrl).
- Live smoke (`scripts/verify_frontend.sh`): 7 checks pass — index.html served + refs
  bundle, config.json valid w/ correct apiUrl/pool/client/region, JS bundle downloads,
  individual + staff login via the SPA client both work. Backend units still 7 pass.
- CAVEAT: in-browser UI render not clicked through (no browser here). Components compile
  clean and every API they call is live-verified (T4/T5). Open the CloudFront URL to
  confirm the rendered flows.
- DataStack was redeployed to drop the old frontend bucket; FrontendStack recreated it
  with the same name (lostlink-frontend-757868239668).

**Task 5 — DONE (deployed + integration-verified).**
- `backend/api/staff_handler.py`: register found item (photo-first; org from token, never
  body), list/search (?q= description substring, ?status=) scoped to org via by-org-type
  GSI, get/update/withdraw. `_load_in_org` enforces item.organisationId == principal org
  else 403; non-found or missing -> 404. status defaults to "available".
- `infra/lib/api-stack.ts`: StaffFn Lambda (ITEMS_TABLE + PHOTOS_BUCKET, RW grants) +
  routes POST /items/uploads, POST /items, GET /items, GET|PATCH|DELETE /items/{itemId}
  on the same HTTP API + authorizer. Redeployed (UPDATE_COMPLETE).
- Live verification (`scripts/verify_api_staff.{py,sh}`): 22 checks pass — register
  typed + photo-first, list/search/status filter, get/update, cross-org 403 (GET+PATCH+
  DELETE), org-boundary list exclusion, individual-on-staff-route 403, validation 400s,
  withdraw. Backend units still 7 pass.
- 2nd staff seed user for the negative test: staff2@lostlink.example / Staff2!Pass123
  (Staff, org-other).

**ALL 15 TASKS COMPLETE.** See per-task blocks below.

--- OBSOLETE (Task 13, kept for history) ---
**Was next: Task 13** — Evaluation harness + ground-truth data (in /eval, placeholder
only). The pure BlendedScorer is importable with NO boto3 (proven Task 9,
scripts/verify_scorer_pure.sh). Build: (1) ground-truth generation — use Claude (Bedrock,
au. inference profile) to generate ~100 lost + ~200 found descriptions with distractors;
optionally a few real photographed objects. (2) embed all via Titan (or reuse
TitanEmbedder). (3) import pure BlendedScorer + sweep weight maps in memory to compute
Hit@1, Recall@5, MRR across variants (text-only, text+location, text+location+time; image
variants once Option 2 on). (4) notification metrics (alert precision, false-alert rate,
missed rate, latency) from the threshold. (5) sanity test on a tiny labelled set. Output
machine-readable metric tables. eval/requirements.txt already has numpy/pandas/boto3.
eval/README.md is placeholder. NOTE Bedrock generation costs $ — keep small; Claude Haiku
cheap. Task 14 = perf+cost tooling, Task 15 = finalise docs/README/seed.

--- OBSOLETE (Task 12, kept for history) ---
**Was next: Task 12** — Claims workflow STAFF side + handover. Add staff routes to the
SAME claims_handler.py (ClaimsFn already has claims RW + items RW). Staff routes:
GET /org/claims (claims against principal.organisation_id via claims by-org-type GSI;
staff CAN see claimant evidence + the found item since it's their org), GET
/org/claims/{claimId}, POST /org/claims/{claimId}/request-info, /approve, /reject,
/reserve, /handover (use claim_state.next_state with staff actions). On approve/reserve/
handover update found item status (reserved/handed_over/closed). Withdrawing an
unavailable found item (staff_handler DELETE /items/{id}) should notify affected
claimants — add: find claims referencing that candidateItemId + notify via SesNotifier +
set claim state appropriately (rejected/cancelled?) — decide. Enforce claim.organisationId
== principal.organisation_id (403 cross-org). Add ORG routes in ApiStack using
this.claimsFn/claimsIntegration + grant matches read (already) — claimsFn may need SES
send for withdrawal notifications (add ses perms + SENDER_EMAIL + MATCHES_TABLE already
present). Frontend StaffPortal: claims review list, approve/reject/request-info/reserve/
handover buttons. Tests: full approve->reserve->handover path, reject path, cross-org
claim action 403, withdrawal-notifies-claimants. Deploy Api (+ Frontend). Then Tasks
13 (eval harness — pure Scorer already importable), 14 (perf+cost), 15 (finalise docs).

--- OBSOLETE (Task 11, kept for history) ---
**Was next: Task 11** — Claims workflow (individual side). APIs + UI for individual to
view/dismiss match suggestions, submit ownership evidence, answer staff questions, track
claim status. Item details HIDDEN until verification (privacy). Claims table exists
(LostLink-Claims, PK claimId, GSIs by-owner=claimantId, by-org-type=organisationId).
State machine module (submitted -> info_requested -> approved/rejected -> reserved ->
handed_over). New claims_handler.py in backend/api/ + routes on same HTTP API/authorizer.
Reuse presigned uploads for evidence. Individual sees match SUGGESTIONS (that a partner
org may hold their item) WITHOUT the found item's description/photo until staff approves.

--- OBSOLETE (Task 10, kept for history) ---
**Was next: Task 10** — Notifier: real SES + per-report-item-pair dedup. NotificationStack
(infra/lib/notification-stack.ts, empty stack w/ props config): verify an SES sender
identity (sandbox — verified recipients only; record assumption), config set optional.
Implement SesNotifier (currently log-only stub): send email to report owner when a match
exceeds threshold; BEFORE sending, check the Matches row's `notified` flag (or a
conditional update) so reprocessing doesn't resend; set notified=true after send. Worker
needs ses:SendEmail IAM + SENDER_EMAIL env. MatchingStack depends on NotificationStack
(already wired in props). Deploy Notification + Matching. Verify: submit matching pair,
confirm one email per report-item pair even when worker runs twice; no email below
threshold. SES sandbox: seed users are @lostlink.example (not real inboxes) — may need to
verify a real recipient identity or use the SES mailbox simulator (success@simulator.amazonses.com)
for the test.

--- OBSOLETE (Task 8, kept for history) ---
**Was next: Task 8** — MatchingStack: SQS queue + DLQ, worker Lambda. Wire
MATCH_QUEUE_URL into the reports + staff handlers (env) so create/edit enqueue jobs.
Worker: MatchWorker.handle runs DescriptionSource -> Embedder (cache desc+vectors on
item via repository.save) -> BruteForceRetriever (implement it in impl/retriever.py) ->
score (stub Scorer until Task 9, or implement minimal) -> save matches. Worker needs a
numpy layer/bundle (numpy in requirements). IAM: Bedrock InvokeModel on Titan model +
`au.` Claude inference profile ARN, DynamoDB RW, S3 read photos, SQS consume. Deploy +
test job processed end-to-end. NOTE: full scoring is Task 9 — Task 8 can persist raw
candidate matches or defer scoring; keep worker orchestration but Scorer/ProfileSelector
still NotImplementedError until T9. Decide: implement retrieval+embedding in T8, scoring
in T9.

## Verify current state

- Files exist: `ls -la ~/ComputeOnClouds` shows README.md, PROGRESS.md, RATIONALE.md,
  ARCHITECTURE.md, and infra/backend/frontend/eval/scripts dirs.
- Infra synth: `cd ~/ComputeOnClouds/infra && npx cdk synth --quiet` succeeds; six
  templates appear in `infra/cdk.out/`.
- Auth template: `bash ~/ComputeOnClouds/scripts/inspect_auth_template.sh` shows the
  expected Cognito resources + tokens.
- Backend: `bash ~/ComputeOnClouds/scripts/verify_backend.sh` → "pipeline import OK" +
  7 passed.
- (Deploy-blocked) Once AWS creds exist: `npx cdk deploy LostLink-Auth` then
  `bash scripts/seed_auth.sh` prints the seed users' group + org claims.

## Deviations from plan

- **CDK bootstrap / deploy not run (Tasks 1-2).** No AWS credentials or AWS CLI in this
  environment. All offline verification passes. Deploy + live verification are deferred
  until credentials are provided (see BLOCKER section above). Code for each stack is
  written and synth-verified so that a single `cdk deploy` + seed run will complete the
  live verification later.
