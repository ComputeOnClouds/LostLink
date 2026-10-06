# Plan: matching vs verification fields + ID check at handover

Status: proposed; no code written. Based on `main` @ 2748d45.
Coordinate with PR #1 (Harsh): it edits `models.py`, `ddb_mapping.py`, `repository.py`,
`staff_handler.py`, `claims_handler.py` and the portal components. Phase 4 (frontend) waits
for it to merge; agree field names with Harsh before Phase 1.

## Goal

Split item data into two kinds so a claimant cannot claim an item just by repeating
details back:

| Kind | Fields | Used for | Who sees it |
|------|--------|----------|-------------|
| Matching | `description`, `locationZone`, `eventTime`, `category` (new) | Scoring | Claimant sees only `category`, date found, area before approval; description + photo after approval |
| Verification (new) | found item `verificationDetails`; lost report `privateDetails` | Staff test a claim | Staff only. Never claimants, never embeddings, never the LLM prompt |

Verification method: in-app claim (already built) **plus** an ID check at handover.

## Decisions to confirm with the team

1. `category` is a fixed list (e.g. wallet, phone, bag, keys, card, electronics, clothing,
   other). Confirm the list.
2. Before approval the claimant sees category, date found, and zone (area). Brand/colour
   stay hidden.
3. `verificationDetails` is never returned to claimants, even after approval.
4. `hand_over` requires `idChecked: true` (staff confirm they checked ID).

## Phase 1: data model (no behaviour change)

- `backend/pipeline/models.py`: add optional `category`, `verification_details` to `Item`.
  Lost reports reuse `verification_details` for the claimant's private details (one field,
  two meanings by `item_type`) to avoid a second field.
- `backend/pipeline/impl/ddb_mapping.py`: map to `category` / `verificationDetails` in
  `item_to_ddb` and `ddb_to_item`. Optional, so old records stay valid; no infra change
  (DynamoDB is schemaless).

## Phase 2: write path

- `backend/api/staff_handler.py` (create at ~L66-85): accept `category`,
  `verificationDetails`; validate category against the list; cap text length.
- `backend/api/reports_handler.py` (create + the PATCH path): accept `category`,
  `privateDetails`; same validation.
- `backend/pipeline/impl/description.py`: change `_PROMPT` to drop "any distinctive marks"
  so AI text does not carry verification material.
- Leave `embedder.py` alone: it embeds `item.description` only. The regression test in
  Phase 5 guards this.

## Phase 3: read path and claim flow

- `backend/api/claims_handler.py`:
  - `_list_matches` (L61-90): load the found item; return `category`, `eventTime`,
    `locationZone` only. Never description/photo/verification.
  - `_claim_view` (L376-410): keep the post-approval reveal; never add verification fields.
  - `_staff_claim_view` (L339-362): add found `verificationDetails` and the lost report's
    private details so staff compare them beside `evidenceText`.
  - `_staff_transition` (L222-255): for `hand_over`, require `idChecked is True` else 400;
    store `idChecked`, staff note, timestamp on the claim.
- `backend/api/claim_state.py`: no change.

## Phase 4: frontend (after PR #1 merges)

- `frontend/src/api.ts`: new fields on item/report/claim types; `idChecked` on hand-over.
- `StaffPortal.tsx`: category select + verification details on found-item form; staff
  claim panel shows found secrets next to claimant's private details/evidence; hand-over
  confirmation checkbox.
- `IndividualPortal.tsx`: category select + optional private details on report form;
  match card shows category / date found / area only.

## Phase 5: tests (offline, existing FakeTable pattern)

- **Privacy regression (most important):** for a claim in every state, no claimant-facing
  response contains `verificationDetails` or the other party's private details; embedder
  input never contains them.
- `_list_matches` returns exactly the allowed fields.
- `hand_over` without `idChecked` returns 400; with it, succeeds and records it.
- Category validation rejects unknown values; length caps enforced.
- Run: `bash scripts/verify_backend.sh`.

## Phase 6: live verification (optional, needs a deployed stack)

- Extend `scripts/verify_claims_staff.py` / `verify_claims_individual.py` for the new
  fields and the handover rule, then deploy to **your own** AWS account (not the team's)
  once Bedrock verification clears. UI testing needs a deployed API + Cognito
  (`/config.json`).

## Docs to update

`docs/flows/decision-and-status.md`, `docs/RATIONALE.md` (new ADR: matching vs
verification fields, ID check at handover), `README.md` privacy section.

## Out of scope

Automatic AI verification of claim answers, image matching, journey/visited places.
