# Flow: Authentication

How a user gets an identity and how that identity is proven on every request.

Related: [`organisation-access.md`](organisation-access.md) (what a role/org is allowed to
do). Design rationale: `../RATIONALE.md` ADR-026.

---

## 1. Two ways to get an account

```mermaid
flowchart TD
  subgraph Individual (self-service)
    I1["Create account (email + password)"] --> I2["Cognito SignUp (unconfirmed)"]
    I2 --> I3["Cognito emails a 6-digit code"]
    I3 --> I4["Confirm code -> user CONFIRMED"]
    I4 --> I5["Post-confirmation Lambda adds<br/>user to 'Individual' group"]
  end
  subgraph Staff (admin-provisioned)
    S1["Admin: admin-create-user<br/>+ custom:organisationId"] --> S2["admin-set-user-password --permanent"]
    S2 --> S3["admin-add-user-to-group 'Staff'"]
  end
```

- **Individuals self-register** from the login screen. They have no organisation.
- **Staff are created by an administrator** (`scripts/seed_demo.sh`) because they act on
  behalf of a specific organisation — that trust is not self-service.

---

## 2. Why the post-confirmation trigger exists

Role in LostLink is carried by **Cognito group membership** (the `cognito:groups` claim),
not an attribute. Cognito's self sign-up creates a confirmed user but puts them in **no
group** — so without intervention a self-registered user would authenticate yet fail every
Individual API call (403) and not route to a portal.

`backend/api/post_confirmation.py` fixes this: on confirmation it adds the user to the
`Individual` group **only when they have no `custom:organisationId`**. Staff carry an org
id and are skipped, so they keep their admin-assigned `Staff` role.

```python
# post_confirmation.py (essence)
if attributes.get("custom:organisationId"):
    return event                      # staff -> leave to admin
cognito.admin_add_user_to_group(UserPoolId=..., Username=..., GroupName="Individual")
```

It is best-effort (wrapped in try/except) so a transient failure never blocks the user's
confirmation; an admin can always fix group membership later.

---

## 3. Login and the token

Frontend auth is `frontend/src/auth.ts` using `amazon-cognito-identity-js` (public SPA
client, no secret):

- `signUp` / `confirmSignUp` / `resendCode` — the registration flow (`Register.tsx`).
- `signIn` — authenticates and returns an `Identity` decoded from the **ID token**.
- `currentIdentity` — restores a session (with refresh) on reload; `signOut` clears it.
- `requestPasswordReset` / `confirmPasswordReset` — Cognito's email-only recovery flow.

The login screen links to a two-step recovery UI (`Recover.tsx`): request a code, then
enter the code and a policy-compliant new password. The request confirmation is neutral
so the UI does not reveal whether an address is registered. Codes and passwords stay in
component state only; no application Lambda or LostLink table handles them.

The ID token carries the three claims the app relies on:

| Claim | Meaning | Used for |
|-------|---------|----------|
| `sub` | stable user id | ownership of reports/claims |
| `cognito:groups` | role (`Individual` / `Staff`) | portal routing + API authorisation |
| `custom:organisationId` | staff's organisation | org-scoped access (empty for individuals) |

The frontend routes on the group: `isStaff = groups.includes('Staff')` →
`StaffPortal`, else `IndividualPortal` (`App.tsx`).

---

## 4. How requests are authenticated

API Gateway (HTTP API) has a **Cognito JWT authorizer** bound to the user pool + client.
It validates the token before any handler runs, then the Lambda reads the verified claims:

```
event["requestContext"]["authorizer"]["jwt"]["claims"]
   -> backend/api/auth.py: principal_from_event() -> Principal(user_id, email, groups, org)
```

Role and org are taken **only** from these validated claims — never from the request body.
That is the foundation of the access model described in
[`organisation-access.md`](organisation-access.md).

---

## 5. Files

| Concern | File |
|---------|------|
| User pool, groups, client, trigger wiring | `infra/lib/auth-stack.ts` |
| Post-confirmation role assignment | `backend/api/post_confirmation.py` |
| Frontend auth (sign up / in / out / recovery) | `frontend/src/auth.ts` |
| Register/confirm/recovery UI | `frontend/src/Register.tsx`, `Recover.tsx`, `Login.tsx`, `App.tsx` |
| Backend claim-reading / Principal | `backend/api/auth.py` |
| Staff/demo seeding | `scripts/seed_demo.sh` |

---

## 6. How to change it

- **Password policy / recovery / verification email**: `infra/lib/auth-stack.ts`
  (`passwordPolicy`, `accountRecovery`, `userVerification`); redeploy `LostLink-Auth`.
- **Collect extra sign-up fields** (e.g. a display name): add the standard/custom
  attribute in `auth-stack.ts`, pass it in `signUp` (`auth.ts`) and the `Register.tsx`
  form.
- **Change the default self-registered role / add org self-selection**: edit
  `post_confirmation.py` (currently every org-less confirmed user → `Individual`). Keep
  role assignment server-side — the public client must never self-assign a role.
- **Let staff self-register for an org**: not recommended without an approval step
  (privilege escalation); if needed, add a verification/approval path, don't just trust a
  client-supplied org.

## 7. Verify

```bash
wsl -d Ubuntu bash ~/ComputeOnClouds/scripts/verify_registration.sh
```
Signs up a throwaway user, confirms, checks the post-confirmation trigger added the
`Individual` group, logs in, and asserts the ID token carries `cognito:groups=[Individual]`
with no organisation. Self-cleans.
