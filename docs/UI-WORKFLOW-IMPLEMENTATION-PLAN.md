# LostLink UI workflow implementation plan

Status: proposed implementation plan; no application changes have been made.

## 1. Outcome and scope

Complete these workflows through the existing React portals:

1. Staff request ownership clarification; claimants read the request and reply; staff review the conversation.
2. Claimants upload evidence images/PDFs; authorised claimants and staff view those attachments.
3. Individuals edit lost reports and staff edit found items, including photos and AI-generated descriptions.
4. Users recover their account through a Cognito password-reset flow.

Keep the current visual identity. Replace browser prompts in the affected workflows with accessible forms and detail panels. Include the backend changes needed to make these UI flows correct; the existing endpoints are a starting point, not a guarantee that every flow is complete.

The required description disclosure is exactly:

> may be generated using Gen AI.

Render this footer deterministically in the UI. Do not ask an LLM to produce it.

## 2. Current implementation and gaps

| Area | Already present | Work required |
| --- | --- | --- |
| Report/item editing | `PATCH /reports/{itemId}` and `PATCH /items/{itemId}` | Client methods, edit forms, lifecycle validation, selective invalidation and rematching correctness |
| Claim conversations | Individual/staff claim-detail endpoints, staff request-info action, claimant response action | Detail panels, history display, reply form, validation and concurrent-update protection |
| Evidence | Presigned upload endpoint; claim creation/replies accept evidence keys | Upload controls, file metadata, authorised downloads, claimant attachment listing and validation |
| Account recovery | Cognito email recovery configuration | Client integration and recovery screens |
| Generated descriptions | Worker generates text from a photo when description is empty | Provenance, safe editing/replacement, explicit regeneration and UI disclosure |

Specific current limitations:

- Claim list responses do not contain the full conversation. Detail panels must request the corresponding detail endpoint.
- The claimant detail response currently omits evidence attachment keys.
- Staff receive attachment keys, not usable authorised viewing URLs.
- Evidence upload responses use `evidenceKey`; the existing photo helper expects `photoKey`. The client must handle these contracts explicitly.
- Image/PDF evidence is accepted, but PDF filenames currently fall through to the generic `.bin` extension helper.
- Editing currently clears all embeddings, including location/time-only edits.
- Photo replacement can retain the description generated from the previous photo.
- Matching saves qualifying results without removing obsolete suggestions.
- The current claim conversation update reads and rewrites a message list without a conditional state/version check.

## 3. UI disclosure: exact behaviour

Use one shared description field/display component, or a shared footer component used by both, containing the literal string `may be generated using Gen AI.`

- Display the footer beneath every visible lost/found item description in the affected portals: create/edit fields, report/inventory records, staff item details, and approved claimant item details.
- Display it for typed, generated, user-edited and legacy descriptions. The word “may” deliberately avoids depending on incomplete historical provenance.
- Display it beneath AI-description previews as well.
- Do not render a hidden found-item description or its description block before approval. Keep the existing privacy gate.
- Do not label claim messages, ownership evidence or staff notes as AI-generated item descriptions.
- Keep the footer outside editable text, persisted descriptions, API payloads, embeddings and model prompts. Users can edit the description without editing the footer.
- Render it once per description block as readable secondary text; associate it with an editable field using `aria-describedby`.
- Preserve this text even if generation fails or the user replaces the generated wording.

Acceptance: the exact disclosure appears consistently without any model call, and never becomes part of the text used for matching.

## 4. Description and photo behaviour

### 4.1 User-visible rules

AI-generated descriptions are fully editable. Once saved, the user's text is the description used for matching.

| User action | Image LLM | Text embedding | Matching |
| --- | --- | --- | --- |
| Save an unchanged record | No | Reuse | No unnecessary job |
| Edit description only | No | Recompute if effective text changed | Recompute |
| Change location/time only | No | Reuse | Recompute |
| Add/replace photo with an existing description | Only if user selects generation | Recompute only if description changes | Recompute if relevant inputs change |
| Add/replace photo with an empty description | Generate once for the selected photo | Embed accepted/generated text | Recompute |
| Remove photo while retaining description | No | Reuse | Recompute only if relevant inputs change |
| Explicitly select “Generate description from photo” | Yes | Only after generated draft is saved | Recompute after save |
| Cancel an edit or generated draft | No additional call | No change to saved vector | No change to saved record |

“LLM call” here means the image-to-description operation. Text embedding is a separate operation and remains necessary when the actual description changes.

### 4.2 Photo replacement and user control

- Show the current photo and offer keep, replace and remove actions.
- When a photo changes, identify any retained description generated from the old photo. Require the user to confirm keeping that wording or generate a replacement before saving; do not silently treat it as a description of the new image.
- Preserve handwritten corrections. Generation produces a preview, never an automatic overwrite of a nonempty description.
- Preview actions: **Use description**, **Try again**, and **Cancel**. “Use description” fills the editable field; the ordinary Save action persists it.
- If description is empty and a photo is selected, begin one generation attempt and show an editable preview. On failure, preserve the photo and offer retry or manual typing.
- Prevent repeated automatic calls on rerenders, failed saves, unchanged photos or component remounts. Allow an intentional retry/regeneration request.
- Keep the existing description-or-photo rule. Photo removal must not leave a record with neither.

### 4.3 Backend support and provenance

Add backward-compatible optional fields for description source and generation context, for example:

- `descriptionSource`: `user`, `ai`, `ai_edited`, or `unknown`.
- `descriptionPhotoKey`: photo that produced the generated text, when applicable.
- `descriptionGeneratedAt`: generation timestamp, when applicable.
- `revision`: optimistic concurrency version for saved records.

Treat old records as `unknown`; do not infer AI provenance just because a photo exists. Provenance is used for correct editing/generation behaviour, not for deciding whether to render the required footer.

Provide an authenticated generation operation for a photo the caller is permitted to use. Reuse the existing description provider and prompt. Keep generation separate from saving so cancelling a preview cannot overwrite the record.

Proposed API contract: `POST /descriptions/generate` accepts an authorised uploaded-photo reference and a request identifier; returns draft text and server-issued generation metadata. Exact route placement can follow the existing handler structure. The server must verify photo ownership and handle duplicate requests without unintentionally repeating generation. An explicit “Try again” uses a new request identifier.

Update the background worker to preserve user-edited descriptions, reuse valid embeddings, and avoid saving enrichment over a newer user revision. Its existing photo-only creation fallback must remain compatible with the new provenance rules.

## 5. Stage 1: complete claim conversations

### UI

- Add **View claim** to individual claims and staff review cards.
- Open a responsive detail panel with claim status, original ownership evidence, conversation history and available actions.
- Show messages in chronological order with sender and local timestamp.
- Staff use an inline **Request information** form with a required question.
- Claimants see an **Information requested** notice and a reply form only in `info_requested` state.
- A successful reply returns the claim to `submitted`; display **Awaiting staff review** and refresh detail/list data.
- Keep terminal claims readable, with no reply controls.
- Provide refresh/on-reopen fetching so users can discover actions taken in another session. WebSockets are not needed for this scope.

### API and backend

- Add typed client methods for staff claim details and claimant replies; extend shared message/detail types.
- Use `GET /claims/{claimId}` and `GET /org/claims/{claimId}` for conversation data.
- Use the existing staff request-info and claimant respond endpoints.
- Reject blank questions and replies containing neither text nor valid attachments.
- Protect conversation changes using expected revision/state conditions. On conflict, return a clear conflict response and refetch without losing the user's unsent draft.
- Continue enforcing claimant ownership and staff organisation access on the server.

### Acceptance

An individual submits evidence; staff ask a question; the individual reads it and replies; staff read the answer and proceed to approve/reject. Both parties retain the history after reload. Another user or organisation cannot open the claim.

## 6. Stage 2: evidence attachments

### UI

- Replace prompt-based claim submission with a form containing evidence text and optional attachments.
- Support JPEG, PNG, WebP and PDF, consistent with the existing backend allowlist.
- Reuse the uploader in claim creation and clarification replies.
- Show filename, type, size, per-file upload state, failure/retry, and removal before submission.
- Preserve text and successful uploads when another upload fails; disable final submission while required uploads are pending.
- Show image thumbnails and PDF open/download actions in claim detail panels for authorised parties.
- Keep existing attachments available after subsequent replies; distinguish newly selected files from submitted evidence.

### Backend

- Keep the S3 bucket private. Issue short-lived download URLs only after checking access to the parent claim and membership of the requested attachment in that claim.
- Return evidence metadata to the claimant as well as staff. Do not offer an endpoint that signs arbitrary client-supplied S3 keys.
- Validate that submitted evidence keys belong to uploads authorised for the claimant; verify existence, allowed type and size before attachment association.
- Preserve filename, content type and size for new attachments. Render sensible fallback labels for legacy keys.
- Correct PDF extension handling without breaking old `.bin` references.
- Proposed initial limits: five attachments per submission/reply, 10 MiB per file, and twenty attachments per claim. Keep these server-configured and apply the same values in the UI.
- Prevent oversized uploads using an upload mechanism with a size condition, and retain server-side checks when finalising attachments.
- Refresh expired viewing links through the authorised API.

### Acceptance

The claimant submits an image and PDF, staff view both, the claimant adds evidence with a reply, and both see all submitted evidence after reload. Invalid files, another user's upload keys and unauthorised downloads are rejected. A failed upload does not discard the written response.

## 7. Stage 3: editing lost reports and found items

### UI

- Add **Edit** to eligible report and inventory cards.
- Reuse form fields for description, location, event time and photo, prefilled from fresh server data.
- Provide Save/Cancel, validation, submission feedback and unsaved-change handling.
- Apply all generation and disclosure rules from sections 3–4.
- Preserve time correctly between stored timestamps and local date/time inputs.
- After saving, refresh relevant reports/items and suggestions. Indicate rematching only when matching inputs changed.
- Surface save conflicts with a reload/review option instead of silently overwriting another update.

### Backend

- Add client methods for the existing PATCH endpoints.
- Compare old/new values to invalidate only changed derived data. Location/time edits reuse the text vector.
- Validate editable states on the server. Initial policy: reports can be edited while active; withdrawn/completed reports cannot reopen through editing. Found-item content editing is restricted to available items; reservation/handover remain dedicated actions.
- Preserve immutable creation metadata and use conditional revision updates.
- Make worker enrichment/status updates revision-aware so an older queued job cannot overwrite a newer edit or withdrawal.
- Invalidate outdated match suggestions on relevant edits, then recompute them. Filter inactive reports/items when presenting suggestions; cover both lost-side and found-side edits.
- Preserve notification history when matches are rescored, preventing an edit from resetting the per-pair deduplication flag. Comprehensive email-delivery recovery remains a separate task.

### Acceptance

Both roles edit their own permitted records through the UI. Description edits update matching text; location/time edits reuse embeddings; unchanged saves do no generation work. Photo replacement cannot silently reuse obsolete generated wording. Cancel preserves saved data. Forbidden edits are rejected even through direct API calls.

## 8. Stage 4: password recovery

- Add **Forgot password?** to the existing login screen.
- Build the flow: email entry → code and new-password entry → success → login.
- Integrate the existing Cognito client library's recovery operations in `auth.ts`; no application Lambda is expected.
- Offer resend-code, change-email and back-to-login actions.
- Validate confirmation and display the deployed password policy.
- Handle expired/incorrect codes, throttling, network errors and policy rejection with actionable messages.
- Use neutral request-code confirmation text that does not disclose whether an account exists.
- Do not store reset codes or passwords outside the form's temporary state, or log them.

Acceptance: an eligible user receives a code, resets their password, signs in with the new password, and cannot sign in with the old password. Invalid-code and resend paths work through the UI.

## 9. Shared implementation structure

Expected existing files to update:

- `frontend/src/api.ts`: editing, detailed claims, response/upload/download/generation contracts.
- `frontend/src/IndividualPortal.tsx`: report editing and complete claimant workflow.
- `frontend/src/StaffPortal.tsx`: inventory editing and claim detail/review workflow.
- `frontend/src/auth.ts`, `Login.tsx`, `App.tsx`: account recovery integration and navigation.
- `frontend/src/styles.css`: styles for panels, conversations, attachment states and disclosure.
- `backend/api/claims_handler.py`: detail responses, evidence validation/access and conversation concurrency.
- `backend/api/reports_handler.py`, `staff_handler.py`: edit validation, revisions and photo access.
- `backend/api/s3urls.py`: authorised upload/download support and correct file metadata handling.
- `backend/pipeline/models.py`, `impl/ddb_mapping.py`, `impl/repository.py`, `worker.py`: provenance, selective embedding reuse, revision safety and match invalidation.
- `infra/lib/api-stack.ts` and relevant CDK wiring: additional routes and narrowly scoped permissions required by generation/attachment access.

Extract shared components where both portals use the same behaviour: description field/display/footer, item editor, claim detail/conversation, attachment picker/gallery and generation preview. Keep role-specific actions explicit.

Accessibility and error behaviour:

- Label every field; connect help text and errors to it.
- Support keyboard use and focus management in panels/dialogs.
- Announce submission/error states without relying on colour alone.
- Prevent duplicate submissions and preserve drafts on recoverable failures.
- Handle session expiry with a clear reauthentication path.
- Ensure long messages, filenames and histories remain usable on mobile.

## 10. Verification plan

### Automated checks

- Run existing backend tests and frontend TypeScript/build checks.
- Add targeted regression tests for message state/version conflicts and ownership/organisation boundaries.
- Test attachment upload validation, claim association, metadata, authorised viewing and legacy evidence keys.
- Test editing state restrictions, selective vector invalidation, stale worker writes and obsolete match removal.
- Test the footer's exact string and its absence from saved/embedded description text.
- Test that typing, location/time changes, unchanged saves and repeated rendering do not trigger image generation.
- Test photo replacement, explicit regeneration, cancellation and generated-description editing.
- Test recovery screen state transitions with mocked Cognito responses; verify actual delivery separately.

### Browser and integration checks

1. Use separate individual and staff sessions for claim submission → question → reply with evidence → review → approval.
2. Repeat access checks with a second individual and staff from another organisation.
3. Exercise report/item edits, photo-only and text-plus-photo cases, generation failure/retry and disclosure rendering.
4. Verify private found details remain hidden before approval, including image viewing links.
5. Exercise real password recovery with a suitable test inbox when deployed configuration is available.
6. Review desktop and mobile together; fix observed issues in one batch and confirm once.

Report local test results separately from live AWS verification. Do not claim live email delivery, Bedrock invocation or deployed access controls were verified without executing those checks.

## 11. Delivery order and completion criteria

1. Complete conversation UI and the minimal validation/concurrency changes it needs.
2. Add evidence attachment submission and authorised viewing to that workflow.
3. Implement description provenance/generation rules, the shared deterministic footer and both edit forms, including matching consistency changes.
4. Add Cognito password recovery.
5. Run the combined acceptance walkthroughs, update relevant flow documentation and prepare deployment changes.

Each stage should be independently reviewable. Backend changes must remain compatible with existing records and the current frontend while the new UI is being introduced.

The scope is complete when all four workflows are usable from the UI, the exact description footer is rendered consistently, descriptions can be edited without unnecessary image-model calls, and the relevant permissions/error paths are tested.

Not included in this implementation: true image-vector matching, journey matching, billing, SSO, a broad visual redesign, general-purpose chat, or a full notification-delivery redesign. Competing-claim ownership consistency identified in the earlier review remains a separate known issue; this plan does not imply it is resolved.
