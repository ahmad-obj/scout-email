# Scout Email V1

Local-first, evidence-backed outreach system for WEBERAISE. The backend owns business logic and safety decisions; n8n is used only for orchestration and Gmail transport. Real sending is disabled by default.

## Requirements

- Docker Engine with Docker Compose v2
- Git
- Optional: a Gemini API key or an Ollama server for model-backed stages

## First run

1. Copy the environment template:

   ```bash
   cp .env.example .env
   mkdir -p data n8n_data
   ```

2. Keep `SCOUT_EMAIL_SEND_MODE=mock`. Configure an optional LLM provider in `.env` if required. Ollama defaults to `http://host.docker.internal:11434`; Gemini uses `SCOUT_EMAIL_GEMINI_API_KEY`.

3. Build and start the local stack:

   ```bash
   docker compose up --build -d
   docker compose ps
   ```

   Operator-facing services are local-only:

   - API: `http://localhost:8000`
   - n8n: `http://localhost:5678`
   - browser-worker: internal Docker network only

4. Apply database migrations:

   ```bash
   docker compose exec outreach-api alembic upgrade head
   curl -fsS http://localhost:8000/health
   ```

5. Import the JSON workflows from `n8n/workflows/` into n8n. They are intentionally disabled by default. Keep Gmail workflows disabled while using mock mode.

6. Create a campaign, for example:

   ```bash
   curl -fsS -X POST http://localhost:8000/campaigns \
     -H 'Content-Type: application/json' \
     -d '{"name":"Local dental scout","searches":["dentist"],"locations":["Daska, Pakistan"],"target_leads":3}'
   ```

7. Start Scout with the returned campaign ID:

   ```bash
   curl -fsS -X POST http://localhost:8000/campaigns/1/scout
   ```

8. Inspect jobs through their returned `status_url` values. Review generated drafts at `http://localhost:8000/review`. Human approval remains mandatory.

9. Use mock sending first. Do not enable Gmail merely to test the application.

## Gmail enablement and owned-address smoke test

Real Gmail transport is fail-closed. `SCOUT_EMAIL_SEND_MODE=gmail` is rejected unless both `SCOUT_EMAIL_N8N_SEND_WEBHOOK_URL` and `SCOUT_EMAIL_N8N_WEBHOOK_SECRET` are configured.

Only after the quality gates have passed:

1. Configure Gmail OAuth inside n8n for the imported Gmail workflows.
2. Configure the n8n webhook/header credential with the same shared secret as `SCOUT_EMAIL_N8N_WEBHOOK_SECRET`.
3. Set `SCOUT_EMAIL_N8N_SEND_WEBHOOK_URL=http://n8n:5678/webhook/send-approved`.
4. Change `SCOUT_EMAIL_SEND_MODE=gmail` deliberately and recreate the API container:

   ```bash
   docker compose up -d --force-recreate outreach-api n8n
   ```

5. Enable only the required n8n Gmail workflow.
6. Send the first live smoke test only to an email address owned by the operator. Never use a real prospect as a development test recipient.
7. Reply from that owned address and verify threading, reply classification, and follow-up cancellation before any low-volume campaign use.

Switch back to `SCOUT_EMAIL_SEND_MODE=mock` whenever live transport is not explicitly required.

## Safety defaults

- Real Gmail is off by default.
- Live Maps smoke is off by default.
- Human approval is required for outbound copy.
- Approval is bound to the exact subject/body hash.
- DNC and hard-bounce blocks cannot be overridden by campaign state.
- Public contact details require source provenance; email addresses are never guessed.
- n8n workflows remain orchestration/transport only and are imported disabled.
- Browser navigation applies the backend/browser-worker public-network safety policy.

## Persistent data

The compose stack binds:

- `./data` -> `/data` for SQLite, evidence, screenshots, and browser artifacts
- `./n8n_data` -> `/home/node/.n8n` for n8n state and credentials

Back up both directories before destructive local changes. On Linux, if a bind-mount permission error occurs, ensure the repository user owns them:

```bash
sudo chown -R "$(id -u):$(id -g)" data n8n_data
```

## Useful commands

```bash
docker compose ps
docker compose logs -f outreach-api
docker compose logs -f browser-worker
docker compose logs -f n8n
docker compose restart outreach-api
docker compose down
```

## Troubleshooting

**browser-worker unavailable** — Check `docker compose ps` and `docker compose logs browser-worker`. Confirm its health endpoint succeeds inside the Docker network and that `/data/browser-artifacts` is writable.

**Google Maps selector smoke failure** — Do not enable broad live traffic. Run only the opt-in bounded Maps smoke described by the test suite, with at most three results, and inspect selectors before changing extraction logic.

**Model rate limit/provider unavailable** — Check the configured provider and model, retry only through the bounded backend job policy, or use the alternate configured provider. Do not bypass structured-output validation.

**Crawl timeout** — Inspect the job state and browser-worker logs. The crawler is bounded; do not remove SSRF/public-network guards or timeout limits to make a site pass.

**Invalid model JSON** — The LLM gateway permits the defined repair attempt only. Repeated invalid output should remain failed/reviewable rather than being accepted as free-form text.

**n8n callback failure** — Confirm `SCOUT_EMAIL_N8N_WEBHOOK_SECRET` matches in both services and that n8n can reach `http://outreach-api:8000`. Failed provider callbacks must remain visible; never mark an unknown send as successful.

**DNC block** — This is expected safety behavior. A global DNC match cannot be overridden by approval, campaign settings, or sender intent.

**Gmail mode refuses startup** — Supply both the n8n send webhook URL and shared secret, or return to `SCOUT_EMAIL_SEND_MODE=mock`. There is no silent live-send fallback.
