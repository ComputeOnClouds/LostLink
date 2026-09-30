# LostLink — Decision Record

> Lightweight ADR-style log. Each entry states **what** we're implementing, **why**,
> the **alternatives** considered, and **why chosen**. Append new entries as
> decisions are made; avoid rewriting past entries (add a superseding entry instead).

---

## ADR-001: Infrastructure as code with AWS CDK (TypeScript)

**What:** Define all AWS infrastructure using AWS CDK in TypeScript, organised into
independent stacks (Auth, Data, Api, Matching, Notification, Frontend).

**Why:** CDK lets us express infra as composable class-based constructs, which maps
directly onto the "class component" structure we want. `cdk synth` produces the exact
resource list, which feeds the cloud-vs-on-premise cost comparison reproducibly.
TypeScript CDK is the most mature and best-documented flavour.

**Alternatives considered:**
- **AWS SAM** — great for pure serverless but weaker at multi-service composition and
  cross-stack references.
- **Terraform** — cloud-agnostic and powerful, but heavier for a single-cloud
  prototype and less integrated with AWS constructs.
- **Console click-ops** — fast to start, but not reproducible and impossible to
  document cleanly for grading.

**Why chosen:** Best fit for reproducibility, clean stack decomposition, and the cost
comparison deliverable.

---

## ADR-002: Lambda code in Python 3.12

**What:** All Lambda handlers and the matching worker are written in Python 3.12.
(CDK stays TypeScript; this deliberate split is standard and well-supported.)

**Why:** The matching pipeline is the technical core. Python is the natural fit for
Bedrock SDK usage, embedding math (numpy cosine similarity), and the evaluation
harness (pandas/numpy for Hit@1, Recall@5, MRR). One backend language reduces
cognitive load.

**Alternatives considered:**
- **Node/TypeScript Lambdas** — would unify language with CDK, but weaker for the
  numeric/evaluation work and less idiomatic for Bedrock data-science tasks.

**Why chosen:** Python's data/ML ecosystem is worth more here than language unification.

---

## ADR-003: Description generation — Option 1 (photo → text → text embedding)

**What:** When a photo is present, Claude (via Bedrock) generates a text description;
matching then runs on the **text** embedding of that description. No image embedding
contributes to the score today. If no photo, the user types the description.

**Why:** Staff (and users) should not have to type descriptions. AI-generated
descriptions also standardise vocabulary, which helps text similarity. Keeping the
matching signal purely textual keeps the scorer simple and human-inspectable.

**Alternatives considered:**
- **Option 2 (image embeddings in the score)** — embed the photo directly and add an
  image-similarity term. Richer visual signal, but more complex and adds a second
  scoring profile.
- **Staff type descriptions manually** — highest effort, defeats the value prop.

**Why chosen:** Lowest staff effort with a simple, explainable text-only match. The
pipeline is built so Option 2 can be re-enabled later by populating the reserved image
vector slot and raising `w_image` — no restructuring required.

---

## ADR-004: Matching score — weighted linear blend with reserved two-profile hook

**What:** `score = w_text·textSim + w_image·imageSim + w_loc·spatialSim +
w_time·temporalSim`. Today `w_image = 0` (single active profile: text + location +
time). A `ProfileSelector` centralises weight/threshold choice; a second image-present
profile is stubbed but inactive.

**Why:** Transparent, easy to explain in the report, and makes the evaluation variant
comparison trivial (zero out weights). The profile hook keeps the door open to the
image-present higher-confidence profile discussed in planning.

**Alternatives considered:**
- **Filter-then-rank** (hard-filter by location/time, then rank by embedding only) —
  simpler but less flexible for the variant experiments.

**Why chosen:** Flexibility for evaluation sweeps and future image scoring.

---

## ADR-005: Match config via Lambda environment variables

**What:** Weights and thresholds are supplied to the worker Lambda as environment
variables (set in CDK). The evaluation harness imports the pure Scorer and passes
weights in memory to sweep variants without redeploying.

**Why:** Simplest possible config mechanism, no extra service.

**Alternatives considered:**
- **SSM Parameter Store** — runtime-changeable without redeploy, but adds a service,
  IAM, and fetch/cache code.
- **DynamoDB config item** — runtime-changeable using tables we already have, but still
  more moving parts than env vars.

**Why chosen:** For the prototype, redeploy-to-change is acceptable for the deployed
worker, and the evaluation harness sidesteps the redeploy problem entirely by calling
the pure Scorer directly.

---

## ADR-006: Candidate retrieval — brute-force now, vector DB later (behind an interface)

**What:** A `CandidateRetriever` interface separates "which candidates to compare"
from "how to score them". `BruteForceRetriever` loads all org-scoped candidates from
DynamoDB and the Scorer scores every one. An `AnnRetriever` (vector DB) is stubbed and
documented but not built.

**Why:** At ~200 (up to a few thousand) items, brute-force cosine similarity is a few
ms in numpy — no latency problem to solve. A vector DB (OpenSearch Serverless) has a
high idle-cost floor (~hundreds of $/month) that would harm the cost comparison, and
the blended score would still need application-side re-ranking anyway.

**Alternatives considered:**
- **Vector database now (OpenSearch Serverless / pgvector / Pinecone)** — needed only
  at hundreds-of-thousands+ scale; unnecessary cost and complexity here.

**Why chosen:** Brute-force is exact, free, and sufficient at prototype scale. The
interface makes the future ANN swap a localised change (implement `AnnRetriever` as a
coarse top-K pre-filter; Scorer re-ranks exactly). Documented as the scaling path in
Future Work.

---

## ADR-007: Location as fixed campus/zone identifiers

**What:** Locations are a fixed set of campus/zone identifiers rather than free-text
geocoded coordinates. Spatial similarity is a zone-based decay function inside the
Scorer.

**Why:** Simpler and cheaper to compute at prototype scale, and easy to reason about in
evaluation. The spatial-similarity function lives behind the Scorer, so switching to
geocoded distance later is a localised change.

**Alternatives considered:**
- **Free-text geocoding** (lat/lng distance) — more realistic but adds a geocoding
  dependency and more variance in evaluation.

**Why chosen:** Prototype simplicity; geocoding noted as future work.

---

## ADR-008: Backend highly modular, frontend pragmatic

**What:** The backend is built around swappable stage interfaces — DescriptionSource,
Embedder, CandidateRetriever, Scorer, ProfileSelector, Notifier — plus an
ItemRepository hiding storage. CDK stacks are independent and reference each other via
exported outputs. The frontend is allowed to be more rigid; only its API-client layer
is kept deliberately clean.

**Why:** We explicitly anticipate changing scoring, comparison/retrieval, description
generation, and embeddings later. Interfaces localise those changes. The frontend only
consumes the API, so heavy abstraction there would not pay off.

**Alternatives considered:**
- **Monolithic worker** — faster to write initially, but every future change ripples.

**Why chosen:** Matches the stated goal of easy future change on the backend without
over-engineering the UI.

---

## ADR-009: Working files kept continuously up to date

**What:** Maintain PROGRESS.md (resumability), RATIONALE.md (this file),
ARCHITECTURE.md (interactions), README.md (how to run). Every task updates PROGRESS.md
on completion; decisions append here; component/interaction changes update
ARCHITECTURE.md; run/setup changes update README.md.

**Why:** A mid-build failure or a new session must be able to resume without
re-deriving state or reasoning.

**Alternatives considered:**
- **Single combined doc** — simpler but muddles distinct purposes (state vs reasoning
  vs interactions vs usage).

**Why chosen:** Separation of concerns keeps each file focused and useful.

---

## ADR-010: Role via Cognito groups; organisation via a custom attribute

**What:** User role is represented by Cognito group membership (`Individual`, `Staff`),
surfaced in the token as the `cognito:groups` claim. A staff member's organisation is a
custom user-pool attribute `custom:organisationId`. A public SPA app client (no secret)
is used with USER_PASSWORD and SRP auth flows.

**Why:** Groups are the native Cognito way to model coarse roles and appear in the JWT
with no extra code, so Lambdas can branch on role directly from the validated token.
Organisation is per-user data, not a role, so a custom attribute fits and is also
carried in the token, letting request Lambdas enforce org membership from the token
rather than trusting client input (the privacy core). A public SPA client matches a
browser frontend that cannot keep a secret; USER_PASSWORD enables the seed script and a
simple login path, SRP is available for the frontend.

**Alternatives considered:**
- **A `custom:role` attribute instead of groups** — works, but reinvents what groups
  provide and is easier to get inconsistent.
- **Confidential client with a secret** — inappropriate for a browser SPA.
- **Passing org id from the client per request** — insecure; a user could claim another
  org. Rejected in favour of reading it from the validated token.

**Why chosen:** Least-code, token-native role + org enforcement that keeps the
authorisation decision server-side.

---

## ADR-011: Seed users via Cognito admin APIs (no email round-trip)

**What:** `scripts/seed_auth.sh` uses `admin-create-user` (with `--message-action
SUPPRESS`), `admin-set-user-password --permanent`, and `admin-add-user-to-group` to
create confirmed users directly, then signs in and decodes the ID token to verify
claims.

**Why:** Seeding must be repeatable and non-interactive. The admin APIs avoid waiting on
a real verification email, while the normal self-signup + email-verification flow
(configured on the pool) still governs real user registration.

**Alternatives considered:**
- **Self-signup + emailed code in the seed script** — not automatable without a mailbox.

**Why chosen:** Deterministic, scriptable seeding without weakening the real
registration flow.

---

## ADR-012: Multi-table DynamoDB design; one Items table for lost + found

**What:** Separate tables for Items, Claims, Matches, Organisations (rather than a
single-table design). The Items table holds BOTH lost reports and found items,
distinguished by `itemType`. Three GSIs serve the access patterns: `by-owner`
(individual's reports), `by-org-type` (staff org inventory, org baked into the PK), and
`by-type` (cross-org candidate retrieval). All tables use on-demand
(PAY_PER_REQUEST) billing. Vectors are stored as JSON strings; scores as `Decimal`.

**Why:**
- **Multi-table over single-table:** clearer to read, document and grade at prototype
  scale; single-table's overloaded-key gymnastics buy scale we don't need.
- **One Items table for both types:** lost and found share the pipeline and shape, and
  the matcher compares one type against the other — co-locating them makes the `by-type`
  cross-org query trivial and keeps the mapping code single-sourced.
- **Org in the GSI PK (`orgType`):** makes the organisation boundary a property of the
  key, so a staff query physically cannot return another org's items (the privacy core,
  enforced at the data layer, not just in app logic).
- **On-demand billing:** no idle cost, free-tier friendly, matches the serverless cost
  story (RATIONALE ADR-006 context).
- **JSON vectors / Decimal scores:** DynamoDB rejects native floats; JSON keeps vectors
  compact and portable and well under the 400KB item limit at ~1536 dims.

**Alternatives considered:**
- **Single-table design** — idiomatic at scale but obscures the model here.
- **Separate lost and found tables** — would duplicate GSIs and the mapping code and
  complicate the cross-type query.
- **Provisioned capacity** — cheaper only at steady high throughput; adds idle cost.
- **Native DynamoDB number-set vectors** — larger items, per-element type overhead.

**Why chosen:** Clearest model that still enforces the org boundary in the keys and
keeps matching queries simple, at zero idle cost.

**Note (S3 presigned URLs):** New buckets outside us-east-1 return a 307 redirect on
presigned requests using the global endpoint. Presigned URLs are therefore generated
against the regional endpoint with SigV4 + virtual addressing. The request Lambdas
(Tasks 4/5) must do the same.

---

## ADR-013: HTTP API (API Gateway v2) with a Cognito JWT authorizer

**What:** Use API Gateway HTTP API (v2) with the built-in `HttpUserPoolAuthorizer`
rather than REST API (v1) or a custom Lambda authorizer.

**Why:** HTTP API is cheaper (roughly a third of REST API pricing), lower latency, and
has a native JWT authorizer that validates Cognito tokens with no custom code. The
authorizer passes claims straight into the Lambda event, which is exactly what the
`Principal` helper needs. For a prototype SPA this is the least-effort, lowest-cost fit.

**Alternatives considered:**
- **REST API (v1)** — more features (request validation models, usage plans) we don't
  need; more expensive.
- **Custom Lambda authorizer** — unnecessary; Cognito JWT validation is built in.

**Why chosen:** Cheapest, simplest, and token-native — matches the serverless cost story
and the group/org claims model (ADR-010).

---

## ADR-014: One Lambda per role-area with internal routing

**What:** A single `reports_handler` Lambda serves all individual-reporting routes,
dispatching on the HTTP API `routeKey`. Staff and claims will follow the same pattern
(one handler each). Not one Lambda per route.

**Why:** Fewer functions to deploy, warm, and reason about at prototype scale, and the
routes in a role-area share validation and helpers. Internal routing on `routeKey` keeps
dispatch explicit and testable. Cold-start cost is negligible for the demo.

**Alternatives considered:**
- **One Lambda per route** — cleaner IAM per-route in theory, but more moving parts and
  duplicated bootstrapping for no real benefit here.
- **A single mega-handler for all roles** — would blur the role boundary; separate
  handlers per role-area keep authorisation intent clear.

**Why chosen:** Balances simplicity and clarity; role-area handlers map cleanly to the
route groups and their shared auth checks.

---

## ADR-015: Frontend auth via amazon-cognito-identity-js (not full Amplify)

**What:** The SPA authenticates with `amazon-cognito-identity-js` (USER_PASSWORD flow)
rather than the full `aws-amplify` library.

**Why:** We only need sign-in/out, session restore with token refresh, and reading the
group/org claims. The focused library does exactly that with a much smaller bundle and
no broad Amplify configuration surface. USER_PASSWORD matches the seed/login path
already verified server-side.

**Alternatives considered:**
- **aws-amplify** — convenient but heavy for a two-screen SPA; pulls in far more than
  auth.
- **Hand-rolled SRP against Cognito** — unnecessary complexity.

**Why chosen:** Smallest dependency that covers the need; consistent with the public SPA
client (ADR-010).

---

## ADR-016: Runtime config via /config.json (not build-time env)

**What:** The frontend fetches `/config.json` (apiUrl, region, Cognito ids) at startup.
The CDK `FrontendStack` generates it from deployed stack outputs during `BucketDeployment`.

**Why:** Decouples the build artifact from a specific deployment. The same bundle runs
against any environment, and resource-id changes need no rebuild — CDK writes the
correct values at deploy time. This also keeps the reproducible-deploy story clean
(deploy writes config; no manual .env editing).

**Alternatives considered:**
- **Vite build-time env vars** — bakes ids into the bundle; requires a rebuild per
  environment and risks stale ids.

**Why chosen:** Deployment-agnostic bundle and hands-off config wiring.

---

## ADR-017: Frontend hosting bucket lives in FrontendStack

**What:** The S3 hosting bucket was moved out of DataStack into FrontendStack (DataStack
keeps only the photos bucket + tables).

**Why:** Granting CloudFront read access mutates the bucket's resource policy. When the
bucket lived in DataStack and CloudFront in FrontendStack, this created a cross-stack
dependency cycle (Data→Frontend for the policy, Frontend→Data for the bucket domain).
Co-locating the bucket with the distribution keeps the policy mutation in-stack and
removes the cycle. Nothing else references the hosting bucket, so there is no downside.

**Alternatives considered:**
- **Keep the bucket in DataStack** — hits the CDK dependency-cycle error.
- **Manually manage the bucket policy to break the cycle** — more fragile than simply
  co-locating.

**Why chosen:** Simplest correct ownership; also uses CloudFront Origin Access Control
(the current best practice) instead of the deprecated S3Origin + OAI.

---

## ADR-018: Bedrock models — Titan Text Embeddings v2 + Claude 4.5 Haiku (via inference profile)

**What:** Embeddings use `amazon.titan-embed-text-v2:0` (1024-dim, on-demand invoke).
Photo→description uses Claude 4.5 Haiku, invoked through the regional inference profile
`au.anthropic.claude-haiku-4-5-20251001-v1:0` in ap-southeast-2. Both model ids are
config-driven (`EMBED_MODEL_ID`, `DESCRIBE_MODEL_ID`, `BEDROCK_REGION`).

**Why:**
- **Titan Text v2** is the current Amazon text-embedding model, cheap, and supports
  plain on-demand `invoke_model`. 1024 dims is ample for brute-force cosine at prototype
  scale.
- **Claude Haiku tier** is the cheapest vision-capable Claude, which matters because the
  photo→description call runs on every photo ingest and during eval data generation.
- **Inference profile requirement:** Claude 4.5 Haiku rejects on-demand `invoke_model`
  with "Invocation ... with on-demand throughput isn't supported" and must be called via
  an inference profile. In ap-southeast-2 the correct id is prefixed `au.` (Australia),
  not `apac.` — verified by `bedrock list-inference-profiles`. This is pinned as the
  default and overridable.

**Alternatives considered:**
- **Titan Multimodal Embeddings** — would be needed for Option 2 (image vectors); not
  used under Option 1. The `image` VectorMap slot is reserved for it.
- **Claude Sonnet** — higher quality descriptions but more expensive; Haiku is
  sufficient for short catalogue-style descriptions.
- **Cross-region Bedrock (e.g. us-east-1)** — would have been the fallback if models were
  unavailable in ap-southeast-2; not needed since both are available and access is
  granted.

**Why chosen:** Cheapest models that meet the need, in-region, with the correct
invocation path pinned. Implication: the Task 8 worker's IAM must allow
`bedrock:InvokeModel` on both the Titan model ARN and the `au.` Claude inference-profile
ARN (and the underlying foundation-model ARN the profile routes to).

**Note:** New AWS accounts may show `AccessDeniedException: "Your account is currently
being verified"` for Bedrock for up to ~2 hours; this cleared for our account. The live
probe (`scripts/verify_bedrock.py`) skips gracefully while pending.

---

## ADR-019: SQS match-job queue lives in DataStack

**What:** The match-job SQS queue (+ DLQ) is created in DataStack, not MatchingStack.
The request Lambdas (ApiStack) produce to it; the worker (MatchingStack) consumes it.

**Why:** ApiStack is constructed before MatchingStack, and both need the same queue —
producers need its URL + send permission, the consumer needs it as an event source.
Creating it in MatchingStack would force Api → Matching (for the URL) while Matching
already depends on Data, risking an ordering/cycle problem. DataStack is created first
and both Api and Matching already depend on it, so the queue sits there naturally
alongside the tables it feeds, with no cycle.

**Alternatives considered:**
- **Queue in MatchingStack, pass to Api** — would require reordering the app so Matching
  precedes Api and passing the queue into ApiStack; more churn and couples the stacks.
- **A separate QueueStack** — extra stack for one resource; overkill.

**Why chosen:** Least-coupling placement; the queue is core data-flow plumbing like the
tables, so DataStack is a natural home.

---

## ADR-020: Scorer/ProfileSelector implemented in Task 8 (ahead of Task 9)

**What:** The plan slotted the Scorer + ProfileSelector into Task 9, but they were
implemented during Task 8 so the deployed worker could run and be verified end-to-end.
Task 9 becomes hardening + comprehensive unit tests (weight sweeps, boundaries, the
image-term hook, source-agnostic scoring) rather than first implementation.

**Why:** A worker that retrieves candidates but cannot score them can't be verified as a
pipeline. Implementing the pure Scorer now (no AWS deps) let Task 8 prove the whole
SQS→worker→Bedrock→score→persist path live (observed match score 0.927 for a true
match; a distractor correctly scored below threshold).

**Alternatives considered:**
- **Ship a placeholder scorer for Task 8, real one in Task 9** — throwaway work and a
  worker that doesn't reflect real behaviour during its own verification.

**Why chosen:** Building the real pure Scorer once, early, gives a genuinely verifiable
pipeline and avoids rework; Task 9's testing focus is unchanged.

---

## ADR-021: Notification dedup via a DynamoDB conditional update (claim-then-send)

**What:** The SesNotifier deduplicates per report-item pair by doing a DynamoDB
conditional update on the Matches row — `SET notified = true` guarded by
`attribute_not_exists(notified) OR notified = false`. It sends the SES email only if it
won that update (the "claim"). Owner email is stored on the item at creation
(`ownerEmail`, from the Cognito `email` claim) rather than looked up per notification.

**Why:**
- **Exactly-once under redelivery:** SQS is at-least-once, and the same pair can be
  triggered by both the lost report and the found item. A conditional update is an
  atomic compare-and-set, so exactly one worker invocation sends the email regardless of
  reprocessing or DLQ retries.
- **Claim-then-send ordering:** claiming before sending means a crash after claiming, at
  worst, drops one email (no duplicate); duplicates are the worse failure for user trust.
- **Email on the item:** the worker has the item; storing `ownerEmail` at creation avoids
  a Cognito `admin-get-user` call per notification (cost + latency + extra IAM).

**Alternatives considered:**
- **A separate "notifications sent" table** — more storage + a second write; the Matches
  row already exists and has the flag.
- **Cognito lookup for the email each time** — extra API call and IAM for data we can
  cheaply denormalise at creation.
- **Send-then-mark** — risks duplicate emails if the mark write fails after send.

**Why chosen:** Simplest exactly-once mechanism using the row we already write, with the
safer failure mode.

**Sandbox constraint:** SES starts in sandbox (sender + recipient must be verified).
The sender is a config value (`SENDER_EMAIL`); the NotificationStack registers the SES
identity only for a real address (the `.example` placeholder is skipped). Recipients can
be the mailbox simulator (`success@simulator.amazonses.com`) without verification. Actual
delivery verification requires the operator to verify a real sender (click the SES link),
which cannot be automated here; the dedup/claim path is fully verified live regardless.

---

## ADR-022: Claim workflow as a shared, explicit state machine with a privacy gate

**What:** Claims move through an explicit state machine in `backend/api/claim_state.py`
(submitted, info_requested, approved, rejected, reserved, handed_over, cancelled) with a
fixed transition table keyed by action, including which actor (individual vs staff) may
perform each. Both handlers validate transitions through this one module. A
`details_visible(state)` predicate gates when the found item's details may be revealed to
the claimant (only approved onward).

**Why:**
- **One source of truth for transitions:** the individual and staff sides both mutate the
  same claim; centralising the allowed transitions prevents an invalid state change from
  either side and makes the lifecycle auditable and testable in isolation (pure, no AWS).
- **Privacy as an explicit gate, not scattered checks:** the product's core promise is
  that item details stay hidden until ownership is verified. Encoding that as a single
  `details_visible` predicate, applied in every claimant-facing response, makes the
  guarantee easy to reason about and hard to accidentally break. Verified live: the
  found item's description is never returned in `/matches` or a pre-approval claim view.
- **Claiming only surfaced matches:** a claim must reference an existing match against the
  claimant's own report, so a user cannot fish for arbitrary found items by id.

**Alternatives considered:**
- **Free-form status strings updated ad hoc** — easy to reach impossible states and
  duplicate/inconsistent privacy checks.
- **Separate individual and staff state logic** — risks the two sides disagreeing on what
  transitions are legal.

**Why chosen:** A shared explicit machine plus a single privacy predicate is the smallest
design that keeps the lifecycle correct and the privacy guarantee provable.

---

## ADR-023: Notifications are best-effort and decoupled from match persistence

**What:** The SesNotifier only attempts an SES send when a real (non-`.example`) sender is
configured and the recipient looks like an email; otherwise it records the match and
returns without consuming the dedup claim. Any SES send failure is caught and logged, not
raised.

**Why (bug found in testing):** With the placeholder sender `no-reply@lostlink.example`,
the notifier attempted a real send, SES sandbox rejected it (`MessageRejected: not
verified`), the exception propagated out of the SQS worker, the message failed and
retried, and the earlier dedup claim (`notified=true`) made retries no-op — so matches
appeared flaky/undelivered. Notification is a side effect of matching, not part of it;
a match must be persisted regardless of whether an email can be sent. Not consuming the
claim when send is impossible also means alerts can still be delivered later once a real
sender is verified.

**Alternatives considered:**
- **Claim-then-send, let failures raise** — couples email delivery to match success;
  a sandbox rejection breaks the pipeline (the observed bug).
- **Send even with the placeholder** — always fails in sandbox; pointless.

**Why chosen:** Matching correctness must not depend on email deliverability. Best-effort,
send-only-when-possible, and non-fatal failures keep the core pipeline robust.

---

## ADR-024: Lambda concurrency on a capped account; worker vs API contention

**What (finding, not a design choice):** This AWS account has a total Lambda concurrency
limit of 10 (a fresh/unverified-account cap; the normal default is 1000). The async
matching worker consumes concurrency from SQS while interactive API Lambdas also need it,
so bursts of API traffic during matching return HTTP 503 from API Gateway once the 10
slots are exhausted.

**Intended fix and why it couldn't apply here:** Cap the worker with
`reservedConcurrentExecutions` (e.g. 3) so the interactive API path always has slots.
AWS rejected this: when the account limit is 10, AWS requires at least 10 unreserved
concurrent executions to remain, so any reservation fails and the stack rolls back. The
code documents where to set it once the account limit is raised.

**Workarounds used:** The load test runs within the cap (low concurrency + retry/backoff)
and still produces clean latency/throughput numbers. On a normal account the fix is:
raise the concurrency limit via Service Quotas, then set the worker's reserved concurrency.

**Why documented:** It's a genuine operational constraint that shaped the load-test
methodology and is worth stating in the evaluation section (a real cloud gotcha), rather
than hidden. It does not affect correctness — matching, claims, and notifications all
work; only sustained high-concurrency throughput is capped.

---

## ADR-025: Bedrock IAM must span regions for cross-region inference profiles

**What:** The matching worker's `bedrock:InvokeModel` permission grants the
foundation-model resource across ALL regions (`arn:aws:bedrock:*::foundation-model/*`),
not just the deploy region, plus the inference-profile ARN across regions.

**Why (bug found enabling the photo path):** The Claude model is invoked via the `au.`
*cross-region inference profile*, which load-balances the actual invocation across the
Australia region group — it routed to `ap-southeast-4` (Melbourne) even though the stack
is deployed in `ap-southeast-2` (Sydney). Invoking an inference profile requires
`InvokeModel` on both the profile ARN and the underlying foundation-model ARN *in
whichever region the profile routes to*. The original policy scoped the foundation-model
ARN to the deploy region only, so the cross-region hop produced
`AccessDeniedException ... on resource arn:aws:bedrock:ap-southeast-4::foundation-model/...`.
The photo→description step silently failed (found items with only a photo got no
description → no embedding → no match) while text-only matching kept working.

**Alternatives considered:**
- **Pin to a single-region (non-profile) model id** — avoids the cross-region issue, but
  newer Claude models on Bedrock require an inference profile for on-demand invocation
  (plain model-id invoke is rejected), so this isn't available.
- **Enumerate the exact profile regions** — more precise, but brittle if AWS changes the
  profile's region set; the wildcard region on the foundation-model resource (still scoped
  to the `bedrock:InvokeModel` action and this account for profiles) is acceptable for the
  prototype.

**Why chosen:** Cross-region inference profiles are the only supported way to call the
chosen Claude model, so the IAM must cover the regions they can route to. Verified live:
a photo-only found item now gets a Claude-generated description, is embedded, and matches
(score 0.79). See `scripts/verify_photo_match.sh`.
