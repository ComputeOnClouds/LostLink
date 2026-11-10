# Running LostLink locally (Docker)

The whole app runs on your machine with no AWS account. The backend handlers, matching
worker and frontend are the same code you deploy. Only the AWS services around them
are replaced:

| In AWS | Locally |
|---|---|
| Cognito, DynamoDB, S3, SQS, SES, Secrets Manager | [moto](https://github.com/getmoto/moto) emulator (`moto` container) |
| API Gateway + JWT authorizer, SQS → worker trigger, Cognito post-confirmation trigger | [`local/server.py`](../local/server.py) (`backend` container) |
| CDK stacks + `scripts/seed_demo.sh` | [`local/bootstrap.py`](../local/bootstrap.py), run when the backend starts |
| Bedrock (Titan embeddings, Claude vision) | An OpenAI-compatible API, NUS SoClaaS by default (`backend/pipeline/impl/openai_compat.py`) |
| S3 + CloudFront hosting | Vite dev server (`frontend` container), via [`local/vite.local.config.ts`](../local/vite.local.config.ts) |

## Quick start

1. Install Docker Desktop. On Windows, run everything inside WSL with Docker Desktop's
   WSL integration on. Keep the repo on the WSL filesystem, or code changes won't reload.
2. Create `.env` in the repo root (gitignored). Either symlink your SoClaaS env file
   (`ln -s /path/to/soclaas.env .env`), or copy [`.env.example`](../.env.example) and
   set `LLM_BASE_URL` / `LLM_API_KEY`. Any OpenAI-compatible server works, e.g. Ollama at
   `http://host.docker.internal:11434/v1`.
3. Run `docker compose up --build` and open **http://localhost:5173**. Sign in with a demo
   account from the [README](../README.md#seed-demo-data), e.g. `user@lostlink.example` /
   `User!Pass123` or `staff@lostlink.example` / `Staff!Pass123`.

Code changes reload automatically: Vite hot-reloads the frontend, and the backend
restarts when Python files change. Useful commands:

```bash
docker compose logs -f backend   # API + matching logs
docker compose down              # stop; all data is wiped (moto keeps it in memory)
docker compose build             # after changing package.json or requirements.txt
```

Sent emails (match and claim notifications) appear under `ses` → `Message` in
http://localhost:5050/moto-api/data.json.

## How local differs from AWS

- **Passwords aren't checked at sign-in.** moto doesn't verify the SRP login the
  frontend uses, so any password works for an existing account. Any email verification
  or reset code is accepted too.
- **Match scores differ.** Locally, text similarity comes from `bge-m3` instead of
  Titan. With the same place and time, unrelated items scored 0.80–0.85 in testing,
  just below the default threshold of 0.85, so a near miss can still cross it. Set
  `MATCH_THRESHOLD` in `.env` to tune this.
- **One process.** All handlers and the worker run one at a time in one process, with
  no 30-second timeout. S3 upload size limits aren't enforced.
- **Place search** needs `ONEMAP_EMAIL` / `ONEMAP_PASSWORD` in `.env`. Without them it
  returns 503 as in AWS, and choosing on the map still works.
- **After a restart**, sign out and back in: the old browser session refers to users that
  no longer exist. If only `moto` restarted, also run `docker compose restart backend`.

When the CDK app changes, update `ROUTES` in `local/server.py` (from `api-stack.ts`) and
`local/bootstrap.py` (from `data-stack.ts`, `auth-stack.ts`, `seed_demo.sh`).
