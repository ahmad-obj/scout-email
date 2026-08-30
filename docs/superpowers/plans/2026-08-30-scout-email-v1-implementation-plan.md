# Scout Email V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete local-first WEBERAISE outreach pipeline from campaign creation through Google Maps scouting, evidence-backed research, personalized draft generation, human approval, Gmail sending, reply tracking, and one approval-gated follow-up.

**Architecture:** n8n is the orchestration/control plane. A Python/FastAPI application owns campaign, lead, evidence, AI, approval, messaging, and persistence logic; a separately runnable Playwright/Chromium browser service owns Google Maps and rendered-page browser work. SQLite is the only V1 database and job queue. Every AI artifact is schema-validated and evidence-linked; every outbound message fails closed unless human approval, contact provenance, DNC checks, duplicate-send checks, sender health, and campaign limits all pass.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, SQLite/aiosqlite, httpx, Playwright + Chromium, Crawl4AI, BeautifulSoup/lxml, RapidFuzz, tldextract, custom LLM gateway, Gemini-compatible hosted provider adapter, Ollama HTTP adapter, pytest/pytest-asyncio/respx, self-hosted n8n Community, Gmail API/OAuth through n8n, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-30-scout-email-system-design.md`

## Global Constraints

- V1 is local-first, self-hosted, and zero-cost-first.
- V1 requires explicit human approval before every first-touch email and follow-up.
- Google Maps browser automation is the primary V1 discovery adapter, not the system architecture itself.
- V1 only uses publicly presented business contact addresses; it does not silently guess individual email addresses.
- Every personalized claim must resolve to stored evidence or an explicitly allowed reasonable inference.
- `UNVERIFIED` claims are forbidden in outgoing copy.
- The Writer cannot send email; the Sender cannot rewrite approved copy.
- Global do-not-contact rules override every campaign and are rechecked immediately before sending.
- Human replies, opt-outs, bounces, invalid contacts, or manual stops cancel incompatible scheduled follow-ups.
- No production business module calls a model SDK directly; all model use goes through the LLM gateway.
- Model outputs used for workflow control must validate against Pydantic schemas.
- Raw crawls must be reduced into task-specific bounded context before most LLM calls.
- SQLite uses migrations from the first implementation task; no ad-hoc schema creation in application code.
- Long-running browser/research work uses persisted jobs; n8n must not hold a request open for the entire operation.
- All write/send operations must be idempotent.
- Real sending is disabled by default. Development and automated tests use a mock sender until the M4 quality gate is explicitly passed and Gmail is configured.
- V1 sends at most one automated follow-up candidate per thread, and that candidate still requires human approval.
- Do not add Redis, PostgreSQL, Kubernetes, LangChain, a vector database, fine-tuning, multi-account rotation, or a full CRM to V1.

---

## Repository Map

The implementation should converge on this structure. A task may add a directory earlier than another task, but responsibilities must remain as listed.

```text
scout-email/
├── README.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Makefile
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/
│   ├── src/scout_email/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── settings.py
│   │   ├── logging.py
│   │   ├── common/
│   │   │   ├── enums.py
│   │   │   ├── errors.py
│   │   │   ├── ids.py
│   │   │   └── time.py
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   ├── models.py
│   │   │   └── repositories.py
│   │   ├── campaigns/
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   ├── jobs/
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   ├── worker.py
│   │   │   └── routes.py
│   │   ├── leads/
│   │   │   ├── schemas.py
│   │   │   ├── normalize.py
│   │   │   ├── dedupe.py
│   │   │   ├── scoring.py
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   ├── browser/
│   │   │   ├── client.py
│   │   │   └── schemas.py
│   │   ├── scout/
│   │   │   ├── maps.py
│   │   │   ├── service.py
│   │   │   └── jobs.py
│   │   ├── enrichment/
│   │   │   ├── website.py
│   │   │   ├── contacts.py
│   │   │   ├── social.py
│   │   │   └── service.py
│   │   ├── crawling/
│   │   │   ├── crawler.py
│   │   │   ├── discover.py
│   │   │   ├── extract.py
│   │   │   ├── audit.py
│   │   │   └── service.py
│   │   ├── evidence/
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── provenance.py
│   │   ├── llm/
│   │   │   ├── gateway.py
│   │   │   ├── schemas.py
│   │   │   ├── context.py
│   │   │   ├── prompts.py
│   │   │   └── providers/
│   │   │       ├── base.py
│   │   │       ├── gemini.py
│   │   │       └── ollama.py
│   │   ├── research/
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── jobs.py
│   │   ├── strategy/
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── jobs.py
│   │   ├── writing/
│   │   │   ├── schemas.py
│   │   │   ├── playbook.py
│   │   │   ├── writer.py
│   │   │   ├── critic.py
│   │   │   └── similarity.py
│   │   ├── approval/
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   ├── messaging/
│   │   │   ├── schemas.py
│   │   │   ├── eligibility.py
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   ├── replies/
│   │   │   ├── schemas.py
│   │   │   ├── classifier.py
│   │   │   ├── followup.py
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   ├── metrics/
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   └── ui/
│   │       ├── routes.py
│   │       └── templates/
│   │           ├── queue.html
│   │           └── lead.html
│   └── tests/
│       ├── fixtures/
│       ├── unit/
│       ├── integration/
│       └── e2e/
│
├── browser-worker/
│   ├── pyproject.toml
│   ├── src/browser_worker/
│   │   ├── app.py
│   │   ├── settings.py
│   │   ├── maps.py
│   │   ├── render.py
│   │   └── schemas.py
│   └── tests/
│       ├── fixtures/
│       └── test_maps_extract.py
│
├── config/weberaise/
│   ├── company_context.md
│   ├── writing_rules.md
│   ├── banned_phrases.md
│   ├── cta_rules.md
│   ├── approved_examples.json
│   └── rejected_patterns.json
│
├── n8n/
│   └── workflows/
│       ├── campaign-scout.json
│       ├── lead-research.json
│       ├── send-approved.json
│       ├── reply-sync.json
│       └── follow-up.json
│
├── data/                     # gitignored runtime database/artifacts
└── docs/superpowers/
    ├── specs/
    └── plans/
```

---

## Milestone Gate Policy

Implementation is intentionally staged. Do not start the next milestone if the previous gate fails.

| Gate | Required proof before continuing |
|---|---|
| M0 Foundation | migration succeeds on empty DB; full foundation tests pass; app health endpoint works |
| M1 Scout | deterministic fixtures pass; opt-in live Maps smoke test returns normalized leads; duplicate insert is idempotent |
| M2 Enrichment | controlled fixtures produce website/contact/crawl/screenshot evidence with provenance; failures isolate per lead |
| M3 Intelligence | Research/Strategy outputs validate; every selected angle references evidence IDs; SKIP path works |
| M4 Writing | Writer/Critic pipeline rejects unsupported claims; 20–30 manually inspected drafts completed before real sending is enabled |
| M5 Approval + Send | mock sending proves fail-closed eligibility; Gmail cannot send an unapproved/duplicate/DNC-blocked message |
| M6 Replies | simulated reply/bounce/opt-out attaches to correct thread and cancels follow-up atomically |
| M7 Follow-up + E2E | one approval-gated follow-up works; complete fixture E2E and one explicitly authorized live smoke campaign pass |

---

# M0 — Foundation

### Task 1: Bootstrap project, configuration, logging, and health API

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Makefile`
- Create: `backend/pyproject.toml`
- Create: `backend/src/scout_email/__init__.py`
- Create: `backend/src/scout_email/settings.py`
- Create: `backend/src/scout_email/logging.py`
- Create: `backend/src/scout_email/app.py`
- Create: `backend/tests/unit/test_settings.py`
- Create: `backend/tests/integration/test_health.py`

**Interfaces:**
- Produces: `Settings` loaded from environment; FastAPI `app`; `GET /health -> {"status":"ok"}`.
- Runtime paths: `SCOUT_EMAIL_DATA_DIR`, `SCOUT_EMAIL_DATABASE_URL`, `BROWSER_WORKER_URL`, `SEND_MODE`.

- [ ] **Step 1: Write settings tests**

```python
from scout_email.settings import Settings


def test_defaults_fail_safe(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert settings.send_mode == "mock"
    assert settings.maps_live_smoke_enabled is False
    assert settings.max_browser_concurrency <= 3
```

- [ ] **Step 2: Write health integration test**

```python
from fastapi.testclient import TestClient
from scout_email.app import app


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run tests and verify they fail before implementation**

Run:

```bash
cd backend
uv sync --dev
uv run pytest tests/unit/test_settings.py tests/integration/test_health.py -q
```

Expected: import/module failures.

- [ ] **Step 4: Implement minimal project bootstrap**

`Settings` must use Pydantic Settings and default to:

```python
send_mode: Literal["mock", "gmail"] = "mock"
maps_live_smoke_enabled: bool = False
max_browser_concurrency: int = 2
http_crawl_concurrency: int = 8
```

`.env.example` must contain names only/example-safe values, never credentials:

```dotenv
SCOUT_EMAIL_DATA_DIR=../data
SCOUT_EMAIL_DATABASE_URL=sqlite+aiosqlite:///../data/scout_email.db
BROWSER_WORKER_URL=http://browser-worker:8010
SEND_MODE=mock
GEMINI_API_KEY=
OLLAMA_BASE_URL=http://host.docker.internal:11434
N8N_WEBHOOK_SECRET=
```

- [ ] **Step 5: Add developer commands**

`Makefile` must provide:

```make
sync:
	cd backend && uv sync --dev

test:
	cd backend && uv run pytest -q

api:
	cd backend && uv run uvicorn scout_email.app:app --reload --port 8000
```

- [ ] **Step 6: Run tests**

```bash
make sync
make test
```

Expected: both foundation tests pass.

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example Makefile backend
git commit -m "chore: bootstrap Scout Email backend"
```

---

### Task 2: Create database models and first Alembic migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_initial_schema.py`
- Create: `backend/src/scout_email/db/base.py`
- Create: `backend/src/scout_email/db/session.py`
- Create: `backend/src/scout_email/db/models.py`
- Create: `backend/src/scout_email/common/enums.py`
- Create: `backend/tests/integration/test_migrations.py`
- Create: `backend/tests/unit/test_model_constraints.py`

**Interfaces:**
- Produces: async SQLAlchemy session factory `get_session()` and V1 tables from the spec.
- Critical unique constraints: canonical contact email where appropriate, message `idempotency_key`, Gmail `message_id`, source identity `(source, source_external_id)` when present.

- [ ] **Step 1: Write migration smoke test**

```python
async def test_upgrade_from_empty_database(alembic_runner):
    await alembic_runner.upgrade("head")
    tables = await alembic_runner.table_names()
    assert {"campaigns", "leads", "evidence", "jobs", "email_drafts", "outbound_messages", "email_threads", "replies", "do_not_contact"} <= tables
```

- [ ] **Step 2: Define enums before models**

Include exact V1 workflow enums:

```python
class LeadState(StrEnum):
    DISCOVERED = "DISCOVERED"
    QUALIFIED = "QUALIFIED"
    LOW_PRIORITY = "LOW_PRIORITY"
    REJECTED = "REJECTED"
    RESEARCH_PENDING = "RESEARCH_PENDING"
    RESEARCHING = "RESEARCHING"
    RESEARCHED = "RESEARCHED"
    CONTACTABLE = "CONTACTABLE"
    NO_CONTACT = "NO_CONTACT"
    SKIPPED = "SKIPPED"

class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    RETRY = "RETRY"
    SKIPPED = "SKIPPED"

class ClaimClass(StrEnum):
    OBSERVED_FACT = "OBSERVED_FACT"
    REASONABLE_INFERENCE = "REASONABLE_INFERENCE"
    UNVERIFIED = "UNVERIFIED"
```

Also define strategy, approval, reply, website, and contact states exactly as specified.

- [ ] **Step 3: Implement the initial schema**

The migration must create all core tables listed in spec §35, with foreign keys, timestamps, and queue/status indexes. `email_drafts` must be immutable after approval except through explicit edit/review service logic; `outbound_messages` must carry a unique `idempotency_key`.

- [ ] **Step 4: Verify foreign keys are enabled on every SQLite connection**

Register a SQLAlchemy connection event issuing:

```sql
PRAGMA foreign_keys=ON;
```

Test deleting a parent with protected dependents fails rather than creating orphans.

- [ ] **Step 5: Run migration and tests**

```bash
cd backend
uv run alembic upgrade head
uv run pytest tests/integration/test_migrations.py tests/unit/test_model_constraints.py -q
```

Expected: pass on a fresh temporary database.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic.ini backend/migrations backend/src/scout_email/db backend/src/scout_email/common backend/tests
git commit -m "feat: add persistent V1 data model"
```

---

### Task 3: Add repository layer and transactional state transitions

**Files:**
- Create: `backend/src/scout_email/db/repositories.py`
- Create: `backend/src/scout_email/common/errors.py`
- Create: `backend/tests/unit/test_state_transitions.py`
- Create: `backend/tests/integration/test_repositories.py`

**Interfaces:**
- Produces: typed repositories and `transition_lead_state(lead_id, expected_state, new_state)` using compare-and-set semantics.
- Produces: `DuplicateOperationError`, `InvalidStateTransitionError`, `NotFoundError`.

- [ ] **Step 1: Test illegal state transitions**

```python
async def test_lead_cannot_jump_from_discovered_to_researched(lead_repo, lead):
    with pytest.raises(InvalidStateTransitionError):
        await lead_repo.transition(lead.id, LeadState.RESEARCHED)
```

- [ ] **Step 2: Encode allowed transition graph**

Keep the graph explicit in one module. Example path:

```text
DISCOVERED -> QUALIFIED | LOW_PRIORITY | REJECTED
QUALIFIED -> RESEARCH_PENDING | NO_CONTACT | SKIPPED
RESEARCH_PENDING -> RESEARCHING
RESEARCHING -> RESEARCHED | RESEARCH_PENDING | SKIPPED
RESEARCHED -> CONTACTABLE | NO_CONTACT | SKIPPED
```

- [ ] **Step 3: Implement transactional repositories**

Repositories must accept a caller-owned `AsyncSession`; services own transaction boundaries. Do not commit inside low-level repository methods.

- [ ] **Step 4: Test concurrent compare-and-set behavior**

Two workers claiming the same pending job/lead must result in exactly one winner.

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
uv run pytest tests/unit/test_state_transitions.py tests/integration/test_repositories.py -q
git add backend/src/scout_email backend/tests
git commit -m "feat: add transactional repositories and state guards"
```

---

### Task 4: Implement campaign API and safe campaign defaults

**Files:**
- Create: `backend/src/scout_email/campaigns/schemas.py`
- Create: `backend/src/scout_email/campaigns/service.py`
- Create: `backend/src/scout_email/campaigns/routes.py`
- Modify: `backend/src/scout_email/app.py`
- Create: `backend/tests/integration/test_campaign_api.py`

**Interfaces:**
- Produces: `POST /campaigns`, `GET /campaigns/{id}`, `POST /campaigns/{id}/pause`, `POST /campaigns/{id}/resume`.
- `CampaignCreate` contains `name`, `searches`, `locations`, `target_leads`, qualification policy, `max_per_day`, approval mode, follow-up configuration.

- [ ] **Step 1: Write API test for safe defaults**

```python
def test_create_campaign_defaults_to_human_approval(client):
    response = client.post("/campaigns", json={
        "name": "Lahore Dentists",
        "searches": ["dentist", "dental clinic"],
        "locations": ["Lahore"],
        "target_leads": 50,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["sending"]["human_approval"] is True
    assert body["sending"]["max_per_day"] == 10
    assert body["follow_up"]["max_followups"] == 1
```

- [ ] **Step 2: Validate dangerous values**

Reject empty search/location arrays, `target_leads < 1`, `max_per_day < 1`, and `max_followups > 1` in V1.

- [ ] **Step 3: Implement persistence and routes**

Campaign pause must prevent new scout/research/send jobs without deleting existing records.

- [ ] **Step 4: Run tests and commit**

```bash
cd backend
uv run pytest tests/integration/test_campaign_api.py -q
git add backend/src/scout_email/campaigns backend/src/scout_email/app.py backend/tests/integration/test_campaign_api.py
git commit -m "feat: add safe campaign management"
```

---

# M1 — Scout

### Task 5: Implement lead normalization, canonicalization, deduplication, and deterministic scoring

**Files:**
- Create: `backend/src/scout_email/leads/schemas.py`
- Create: `backend/src/scout_email/leads/normalize.py`
- Create: `backend/src/scout_email/leads/dedupe.py`
- Create: `backend/src/scout_email/leads/scoring.py`
- Create: `backend/src/scout_email/leads/service.py`
- Create: `backend/src/scout_email/leads/routes.py`
- Create: `backend/tests/unit/test_normalize.py`
- Create: `backend/tests/unit/test_dedupe.py`
- Create: `backend/tests/unit/test_scoring.py`

**Interfaces:**
- Produces: `normalize_lead(raw: RawLead) -> NormalizedLead`.
- Produces: `match_existing_lead(candidate, candidates) -> MatchResult | None`.
- Produces: decomposable `LeadScore(total: int, components: dict[str, int])`.

- [ ] **Step 1: Test phone/domain/name normalization**

```python
def test_domain_canonicalization():
    assert canonical_domain("https://www.Example.com/about?x=1") == "example.com"


def test_phone_normalization_keeps_country_code():
    assert normalize_phone("+92 300-1234567") == "+923001234567"
```

- [ ] **Step 2: Test dedupe precedence**

Exact normalized phone or canonical domain must outrank fuzzy name similarity. A similar name with a different phone/domain must not merge automatically.

- [ ] **Step 3: Implement deterministic score components**

Return both total and component reasons. Never accept an opaque model-generated number in this stage.

- [ ] **Step 4: Add idempotent upsert service**

Repeated ingestion of the same Maps listing must add/update `lead_sources` without producing duplicate `leads`.

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
uv run pytest tests/unit/test_normalize.py tests/unit/test_dedupe.py tests/unit/test_scoring.py -q
git add backend/src/scout_email/leads backend/tests/unit
git commit -m "feat: normalize deduplicate and score leads"
```

---

### Task 6: Add SQLite-backed job queue with leases, bounded retries, and idempotent handlers

**Files:**
- Create: `backend/src/scout_email/jobs/schemas.py`
- Create: `backend/src/scout_email/jobs/service.py`
- Create: `backend/src/scout_email/jobs/worker.py`
- Create: `backend/src/scout_email/jobs/routes.py`
- Modify: `backend/src/scout_email/app.py`
- Create: `backend/tests/integration/test_job_queue.py`

**Interfaces:**
- Produces: `enqueue_job(kind, payload, idempotency_key) -> Job`.
- Produces: `claim_next_job(worker_id, kinds) -> Job | None` using atomic lease.
- Produces: `complete_job`, `retry_job`, `fail_job`.
- API: `GET /jobs/{id}` for n8n polling.

- [ ] **Step 1: Test one-winner job claiming**

Create one PENDING job and race two claim attempts; assert one receives it and one receives `None`.

- [ ] **Step 2: Test duplicate enqueue**

The same `idempotency_key` returns the existing job rather than creating another.

- [ ] **Step 3: Implement lease recovery**

A RUNNING job whose lease expires becomes claimable again only if retry count remains below configured maximum.

- [ ] **Step 4: Implement bounded exponential retry metadata**

Persist `attempt_count`, `next_attempt_at`, `last_error_code`, and a sanitized `last_error_message`.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/integration/test_job_queue.py -q
git add backend/src/scout_email/jobs backend/src/scout_email/app.py backend/tests/integration/test_job_queue.py
git commit -m "feat: add durable SQLite job queue"
```

---

### Task 7: Build isolated Playwright browser worker and Google Maps fixture extractor

**Files:**
- Create: `browser-worker/pyproject.toml`
- Create: `browser-worker/src/browser_worker/app.py`
- Create: `browser-worker/src/browser_worker/settings.py`
- Create: `browser-worker/src/browser_worker/schemas.py`
- Create: `browser-worker/src/browser_worker/maps.py`
- Create: `browser-worker/src/browser_worker/render.py`
- Create: `browser-worker/tests/fixtures/maps_results.html`
- Create: `browser-worker/tests/fixtures/maps_listing.html`
- Create: `browser-worker/tests/test_maps_extract.py`

**Interfaces:**
- Produces HTTP `POST /maps/search` accepting `{query, max_results}` and returning `list[BrowserMapLead]`.
- Produces HTTP `POST /render` accepting `{url, viewport, screenshot_path}`.
- Extraction internals accept DOM snapshots/locator adapters so fixture tests do not require Google Maps.

- [ ] **Step 1: Create fixture-based extraction tests**

Tests must prove extraction tolerates missing phone/website/rating and still returns a valid lead.

- [ ] **Step 2: Implement browser lifecycle with strict concurrency**

Use one browser process and bounded page/context concurrency. Every navigation receives an explicit timeout. Browser crashes produce typed failures instead of hanging.

- [ ] **Step 3: Implement Maps search flow**

Flow:

```text
open Maps -> search query -> wait for results pane -> scroll until max/no new results -> open result -> extract visible fields -> continue
```

Selectors must be centralized in `maps.py`; fallback strategies should prefer accessible labels/roles and stable semantic attributes over deeply nested CSS chains.

- [ ] **Step 4: Add opt-in live smoke test**

The live test runs only when `MAPS_LIVE_SMOKE_ENABLED=true` and should request at most 3 results. It must never be part of default CI/unit tests.

- [ ] **Step 5: Run fixture tests and commit**

```bash
cd browser-worker
uv sync --dev
uv run playwright install chromium
uv run pytest -q
git add browser-worker
git commit -m "feat: add isolated Google Maps browser worker"
```

---

### Task 8: Wire Scout jobs from campaign to Maps worker to persisted leads

**Files:**
- Create: `backend/src/scout_email/browser/schemas.py`
- Create: `backend/src/scout_email/browser/client.py`
- Create: `backend/src/scout_email/scout/maps.py`
- Create: `backend/src/scout_email/scout/service.py`
- Create: `backend/src/scout_email/scout/jobs.py`
- Modify: `backend/src/scout_email/campaigns/routes.py`
- Create: `backend/tests/integration/test_scout_pipeline.py`

**Interfaces:**
- API: `POST /campaigns/{campaign_id}/scout -> 202 + job_ids`.
- Job handler consumes campaign searches × locations and persists normalized deduplicated leads/sources.

- [ ] **Step 1: Test mocked browser response to persisted leads**

Mock two queries returning one duplicate business. Assert one lead, two source/search records, and deterministic score components.

- [ ] **Step 2: Implement browser client with timeout/retry boundary**

Retry network-level worker failures; do not retry malformed semantic output indefinitely.

- [ ] **Step 3: Enforce target lead count and campaign pause**

Do not enqueue additional Maps query work after the target unique lead count has been reached or campaign is paused.

- [ ] **Step 4: Run test and optional smoke**

```bash
cd backend
uv run pytest tests/integration/test_scout_pipeline.py -q
```

If explicitly enabled:

```bash
MAPS_LIVE_SMOKE_ENABLED=true uv run pytest -m live_maps -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/scout_email/browser backend/src/scout_email/scout backend/src/scout_email/campaigns backend/tests/integration/test_scout_pipeline.py
git commit -m "feat: connect campaigns to Maps scouting"
```

**M1 gate:** Run the full backend and browser-worker suites. With live smoke explicitly enabled, confirm at least one real query returns normalized leads. Repeat the same scout job and verify no duplicate leads or duplicate job side effects appear.

---

# M2 — Enrichment and Evidence

### Task 9: Implement website verification and public business-contact discovery

**Files:**
- Create: `backend/src/scout_email/enrichment/website.py`
- Create: `backend/src/scout_email/enrichment/contacts.py`
- Create: `backend/src/scout_email/enrichment/social.py`
- Create: `backend/src/scout_email/enrichment/service.py`
- Create: `backend/tests/fixtures/websites/live_home.html`
- Create: `backend/tests/fixtures/websites/contact.html`
- Create: `backend/tests/unit/test_contact_extraction.py`
- Create: `backend/tests/integration/test_enrichment.py`

**Interfaces:**
- Produces `verify_website(url) -> WebsiteVerification` with exact states LIVE/BROKEN/NO_WEBSITE/SOCIAL_ONLY/PARKED/UNCERTAIN.
- Produces `extract_public_contacts(pages) -> list[ContactCandidate]` with `source_url`, `type`, and confidence.

- [ ] **Step 1: Test contact provenance**

```python
def test_contact_requires_public_source():
    contacts = extract_contacts("<a href='mailto:hello@example.com'>Email us</a>", "https://example.com/contact")
    assert contacts[0].email == "hello@example.com"
    assert contacts[0].source_url == "https://example.com/contact"
    assert contacts[0].confidence == 1.0
```

- [ ] **Step 2: Test that guessed addresses are impossible in V1**

There must be no code path that constructs an address from person/company names. The service only persists discovered addresses from public source material.

- [ ] **Step 3: Implement website state verification**

Follow bounded redirects; canonicalize final domain; detect common parked/social-only signals; preserve `UNCERTAIN` rather than coercing it to `NO_WEBSITE`.

- [ ] **Step 4: Implement social URL discovery only from verified sources**

Store source URL and verification status for each social profile.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_contact_extraction.py tests/integration/test_enrichment.py -q
git add backend/src/scout_email/enrichment backend/tests
git commit -m "feat: verify websites and discover public contacts"
```

---

### Task 10: Implement bounded crawler, page discovery, extraction, and deterministic technical audit

**Files:**
- Create: `backend/src/scout_email/crawling/discover.py`
- Create: `backend/src/scout_email/crawling/crawler.py`
- Create: `backend/src/scout_email/crawling/extract.py`
- Create: `backend/src/scout_email/crawling/audit.py`
- Create: `backend/src/scout_email/crawling/service.py`
- Create: `backend/tests/unit/test_page_discovery.py`
- Create: `backend/tests/unit/test_page_extract.py`
- Create: `backend/tests/unit/test_audit.py`
- Create: `backend/tests/integration/test_crawl_fallback.py`

**Interfaces:**
- Produces `discover_priority_urls(homepage, sitemap, links, max_pages=20)`.
- Produces `crawl_page(url) -> CrawlResult`, with direct/Crawl4AI first and browser fallback only on defined failures.
- Produces `PageExtract` matching spec §11.3 and `TechnicalAudit` matching §12.

- [ ] **Step 1: Test priority ordering and hard page cap**

Homepage/contact/about/services/pricing must outrank archives/blog tags. Assert returned URL count never exceeds configured max.

- [ ] **Step 2: Test boilerplate reduction**

Fixture with repeated nav/footer must yield unique meaningful page text and preserve CTAs/forms/headings.

- [ ] **Step 3: Test audit facts**

Verify title/meta/viewport/canonical/OpenGraph/structured-data/CTA/social-link extraction against deterministic fixtures.

- [ ] **Step 4: Implement fallback policy**

Only transient/network/render-required failures trigger browser fallback. A valid 404/contact absence is data, not a retry storm.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_page_discovery.py tests/unit/test_page_extract.py tests/unit/test_audit.py tests/integration/test_crawl_fallback.py -q
git add backend/src/scout_email/crawling backend/tests
git commit -m "feat: add bounded website crawling and audit"
```

---

### Task 11: Implement screenshots, evidence records, claim classes, and provenance validation

**Files:**
- Create: `backend/src/scout_email/evidence/schemas.py`
- Create: `backend/src/scout_email/evidence/service.py`
- Create: `backend/src/scout_email/evidence/provenance.py`
- Modify: `backend/src/scout_email/browser/client.py`
- Create: `backend/tests/unit/test_provenance.py`
- Create: `backend/tests/integration/test_evidence_bundle.py`

**Interfaces:**
- Produces stable `EvidenceRecord` IDs and `assert_claim_supported(evidence_ids, claim_class)`.
- Browser client captures desktop 1440×900 and mobile 390×844 homepage screenshots to lead-specific artifact paths.

- [ ] **Step 1: Test artifact paths are lead/campaign scoped and traversal-safe**

Reject `..`, absolute user-provided paths, or paths escaping the configured data directory.

- [ ] **Step 2: Test `UNVERIFIED` cannot become outgoing evidence**

```python
def test_unverified_claim_is_not_sendable():
    with pytest.raises(UnverifiedClaimError):
        validate_outgoing_claim(ClaimClass.UNVERIFIED, evidence_ids=[])
```

- [ ] **Step 3: Implement evidence creation for technical, textual, and screenshot observations**

Evidence always stores source type, source URL when applicable, artifact path when applicable, confidence, and timestamp.

- [ ] **Step 4: Test complete bundle creation**

A controlled lead must produce at least website-verification evidence, contact provenance, page extracts/audit facts, and desktop/mobile screenshot records.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_provenance.py tests/integration/test_evidence_bundle.py -q
git add backend/src/scout_email/evidence backend/src/scout_email/browser/client.py backend/tests
git commit -m "feat: add evidence provenance and screenshot artifacts"
```

**M2 gate:** Process multiple controlled leads including one broken website. Confirm one failure does not stop others, every stored business email has provenance, screenshots stay inside `data/`, and no lead is marked `CONTACTABLE` without a verified contact.

---

# M3 — Intelligence

### Task 12: Build provider-neutral LLM gateway, structured-output repair, prompt versioning, and context boundaries

**Files:**
- Create: `backend/src/scout_email/llm/providers/base.py`
- Create: `backend/src/scout_email/llm/providers/gemini.py`
- Create: `backend/src/scout_email/llm/providers/ollama.py`
- Create: `backend/src/scout_email/llm/gateway.py`
- Create: `backend/src/scout_email/llm/schemas.py`
- Create: `backend/src/scout_email/llm/context.py`
- Create: `backend/src/scout_email/llm/prompts.py`
- Create: `backend/tests/unit/test_llm_gateway.py`
- Create: `backend/tests/unit/test_context_limits.py`

**Interfaces:**

```python
result = await gateway.generate(
    task="researcher",
    context=context,
    response_model=ResearchOutput,
    prompt_version="researcher:v1",
)
```

- [ ] **Step 1: Define provider protocol**

```python
class LLMProvider(Protocol):
    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult: ...
```

No business-domain module imports Gemini/Ollama libraries directly.

- [ ] **Step 2: Test valid, invalid, and repairable structured output**

Gateway gets at most one schema-repair attempt after an invalid response. A second invalid response becomes a typed failed result/job, never arbitrary prose routing.

- [ ] **Step 3: Test context builder excludes raw crawl noise**

The Writer context must not contain raw HTML and must include only persuasion brief, allowed evidence, WEBERAISE context/rules/examples, and recent correction metadata.

- [ ] **Step 4: Record generation metadata**

Persist provider, model, prompt version, generation timestamp, and generation status for every production artifact.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_llm_gateway.py tests/unit/test_context_limits.py -q
git add backend/src/scout_email/llm backend/tests/unit
git commit -m "feat: add structured provider-neutral LLM gateway"
```

---

### Task 13: Implement Researcher dossier generation with bounded input and valid terminal outcomes

**Files:**
- Create: `backend/src/scout_email/research/schemas.py`
- Create: `backend/src/scout_email/research/service.py`
- Create: `backend/src/scout_email/research/jobs.py`
- Create: `backend/tests/fixtures/intelligence/dental_evidence.json`
- Create: `backend/tests/unit/test_research_schema.py`
- Create: `backend/tests/integration/test_research_service.py`

**Interfaces:**
- Produces `ResearchOutput` with business, business_model, presence, strengths, website_findings, technical_findings, contact, confidence, and outcome `COMPLETE|INSUFFICIENT_EVIDENCE|NO_CLEAR_OPPORTUNITY|RESEARCH_MORE`.

- [ ] **Step 1: Encode Pydantic dossier schema**

Make confidence `[0,1]`; findings reference evidence IDs where applicable; contact references a persisted contact ID rather than free-form invented email.

- [ ] **Step 2: Add evidence sufficiency precheck**

If no useful site/public evidence exists, return `INSUFFICIENT_EVIDENCE` without asking the model to invent a dossier.

- [ ] **Step 3: Test fixture-to-dossier integration with a fake provider**

Assert output includes both strengths and weaknesses and references only known evidence IDs.

- [ ] **Step 4: Persist outcome and transition lead state transactionally**

A failure/repairable outcome must not leave a lead stuck indefinitely in RESEARCHING.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_research_schema.py tests/integration/test_research_service.py -q
git add backend/src/scout_email/research backend/tests
git commit -m "feat: generate structured research dossiers"
```

---

### Task 14: Implement combined V1 Auditor/Strategist with evidence-linked opportunity selection

**Files:**
- Create: `backend/src/scout_email/strategy/schemas.py`
- Create: `backend/src/scout_email/strategy/service.py`
- Create: `backend/src/scout_email/strategy/jobs.py`
- Create: `backend/tests/unit/test_strategy_schema.py`
- Create: `backend/tests/integration/test_strategy_service.py`

**Interfaces:**
- Produces candidate audit findings plus selected `PersuasionBrief`.
- Decision is exactly `CONTACT|RESEARCH_MORE|LOW_PRIORITY|SKIP`.
- Every `CONTACT` strategy contains at least one persisted safe evidence ID.

- [ ] **Step 1: Test CONTACT cannot validate without evidence**

```python
def test_contact_requires_supporting_evidence():
    with pytest.raises(ValidationError):
        StrategyOutput(decision="CONTACT", supporting_evidence_ids=[] , ...)
```

- [ ] **Step 2: Encode decomposable opportunity score**

Store components for severity, evidence confidence, likely business impact, WEBERAISE fit, explainability, and generic/speculation risk. Overall score is derived in deterministic Python from bounded component values.

- [ ] **Step 3: Enforce one-primary-angle output**

Candidate angles may exist, but the persuasion brief has exactly one `primary_angle` and a `do_not_use` list.

- [ ] **Step 4: Test SKIP and RESEARCH_MORE paths**

Excellent-site fixture -> SKIP. Missing-evidence fixture -> RESEARCH_MORE. Neither progresses to Writer.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_strategy_schema.py tests/integration/test_strategy_service.py -q
git add backend/src/scout_email/strategy backend/tests
git commit -m "feat: select evidence-backed outreach strategies"
```

**M3 gate:** Run fixture datasets for good-fit, weak-evidence, and excellent-presence businesses. No CONTACT output may contain unknown evidence IDs. Verify SKIP prevents draft job creation.

---

# M4 — Writing and Critique

### Task 15: Add WEBERAISE knowledge/playbook as version-controlled content

**Files:**
- Create: `config/weberaise/company_context.md`
- Create: `config/weberaise/writing_rules.md`
- Create: `config/weberaise/banned_phrases.md`
- Create: `config/weberaise/cta_rules.md`
- Create: `config/weberaise/approved_examples.json`
- Create: `config/weberaise/rejected_patterns.json`
- Create: `backend/src/scout_email/writing/playbook.py`
- Create: `backend/tests/unit/test_playbook.py`

**Interfaces:**
- Produces immutable loaded `WritingPlaybook` with content hash/version recorded on generated drafts.

- [ ] **Step 1: Seed company context only with verified WEBERAISE facts from the approved project context**

At minimum encode: web design/development focus, premium modern positioning, branding/SEO where actually offered, no invented guarantees, no invented portfolio performance metrics, no fake claims of prior familiarity.

- [ ] **Step 2: Seed writing rules**

Include the spec rules: short, specific, one observation, no fake compliments/familiarity, low-pressure CTA, avoid generic agency/AI language, and no unsupported business-loss claims.

- [ ] **Step 3: Seed banned phrases and empty example arrays safely**

`approved_examples.json` may begin as `[]`; `rejected_patterns.json` should include the generic phrases already approved in the spec.

- [ ] **Step 4: Test loading and hash stability**

Same files -> same version hash. Content change -> new hash.

- [ ] **Step 5: Commit**

```bash
git add config/weberaise backend/src/scout_email/writing/playbook.py backend/tests/unit/test_playbook.py
git commit -m "feat: add WEBERAISE outreach playbook"
```

---

### Task 16: Implement Writer with claim-to-evidence mapping and recent-email similarity checks

**Files:**
- Create: `backend/src/scout_email/writing/schemas.py`
- Create: `backend/src/scout_email/writing/writer.py`
- Create: `backend/src/scout_email/writing/similarity.py`
- Create: `backend/tests/unit/test_writer_schema.py`
- Create: `backend/tests/unit/test_similarity.py`
- Create: `backend/tests/integration/test_writer.py`

**Interfaces:**
- Produces `EmailDraftOutput(subject, body, claims, strategy_label, prompt_version, playbook_hash)`.
- Every material `claims[]` entry includes `text`, `claim_class`, and `evidence_ids`.

- [ ] **Step 1: Test Writer schema rejects unsupported observed claims**

Observed claims require evidence IDs. Reasonable inferences require source evidence and must be phrased probabilistically; `UNVERIFIED` is invalid for draft output.

- [ ] **Step 2: Implement bounded Writer context**

Input contains only dossier summary, persuasion brief, allowed evidence, company context, writing rules, relevant approved examples, relevant human corrections, and recent sent-email structures.

- [ ] **Step 3: Add deterministic banned-phrase scan**

The draft is invalid before Critic if it contains exact configured banned phrases unless a human intentionally removed that phrase from the banned file.

- [ ] **Step 4: Add recent-structure similarity score**

Use lightweight text/token similarity. Do not add embeddings/vector DB in V1. High similarity becomes Critic context rather than silently discarding the draft.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_writer_schema.py tests/unit/test_similarity.py tests/integration/test_writer.py -q
git add backend/src/scout_email/writing backend/tests
git commit -m "feat: generate evidence-linked personalized drafts"
```

---

### Task 17: Implement independent Critic, bounded rewrite loop, and hard rejection rules

**Files:**
- Create: `backend/src/scout_email/writing/critic.py`
- Create: `backend/tests/unit/test_critic_rules.py`
- Create: `backend/tests/integration/test_writer_critic_loop.py`

**Interfaces:**
- Critic result is `APPROVE|REWRITE|REJECT` with scores and specific issues.
- Writer/Critic loop allows at most 2 rewrite cycles in V1 before sending the draft to manual review/rejection state.

- [ ] **Step 1: Implement deterministic hard-fail checks before model critique**

Reject immediately on: unknown evidence ID, unverified claim, wrong lead/contact association, DNC hit, duplicate outreach state, banned fake-familiarity pattern.

- [ ] **Step 2: Test genericness fixture**

A draft that can be reused unchanged for an unrelated business must produce REWRITE or REJECT.

- [ ] **Step 3: Test unsupported revenue claim fixture**

`"You're losing 40% of bookings"` without evidence must always reject regardless of model score.

- [ ] **Step 4: Implement specific rewrite feedback**

On REWRITE, pass only issue list + original bounded writer context back to Writer. Do not ask "try again" without constraints.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_critic_rules.py tests/integration/test_writer_critic_loop.py -q
git add backend/src/scout_email/writing backend/tests
git commit -m "feat: independently critique and repair outreach drafts"
```

**M4 gate:** Generate 20–30 draft packages from controlled or explicitly permitted live research. Review each against evidence. Record results. Real sending remains disabled until at least the last 10 human-approved candidates contain zero unsupported personalized claims, zero wrong-company/contact associations, and no DNC/duplicate violations. Quality wording can still be edited; evidence-integrity failures must be zero before M5 live Gmail setup.

---

# M5 — Human Approval and Sending

### Task 18: Implement approval service, edit history, and minimal local review UI

**Files:**
- Create: `backend/src/scout_email/approval/schemas.py`
- Create: `backend/src/scout_email/approval/service.py`
- Create: `backend/src/scout_email/approval/routes.py`
- Create: `backend/src/scout_email/ui/routes.py`
- Create: `backend/src/scout_email/ui/templates/queue.html`
- Create: `backend/src/scout_email/ui/templates/lead.html`
- Modify: `backend/src/scout_email/app.py`
- Create: `backend/tests/integration/test_approval.py`

**Interfaces:**
- API actions: approve, edit, regenerate, reject.
- Approval record captures reviewer action, exact content hash, subject/body snapshot, timestamp, and edit diff metadata.

- [ ] **Step 1: Test approval is bound to exact content**

Edit after approval must invalidate the old approval and require a new explicit approval for the edited content hash.

- [ ] **Step 2: Test REJECT prevents queueing**

A rejected draft cannot become an outbound message without a new draft/review/approval cycle.

- [ ] **Step 3: Implement minimal review screens**

Show lead/category/location, opportunity score/angle, concise evidence links/screenshots, subject, editable body, and the four actions. Do not build a SPA.

- [ ] **Step 4: Persist human edit examples**

Store original/edited text, context category when determinable, lead industry, and playbook/prompt versions.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/integration/test_approval.py -q
git add backend/src/scout_email/approval backend/src/scout_email/ui backend/src/scout_email/app.py backend/tests/integration/test_approval.py
git commit -m "feat: add approval queue and immutable approvals"
```

---

### Task 19: Implement fail-closed sender eligibility and mock sender handoff

**Files:**
- Create: `backend/src/scout_email/messaging/schemas.py`
- Create: `backend/src/scout_email/messaging/eligibility.py`
- Create: `backend/src/scout_email/messaging/service.py`
- Create: `backend/src/scout_email/messaging/routes.py`
- Create: `backend/tests/unit/test_send_eligibility.py`
- Create: `backend/tests/integration/test_mock_send.py`

**Interfaces:**
- Produces `evaluate_send_eligibility(draft_id, recipient_id) -> EligibilityResult`.
- `POST /messages/{draft_id}/queue` only succeeds when all hard checks pass.
- In `SEND_MODE=mock`, dispatch records a synthetic provider/thread/message ID without contacting Gmail.

- [ ] **Step 1: Parametrize hard-block tests**

Every case below must fail:

```text
no approval
approval hash does not match current content
unverified contact
DNC email/domain/business match
duplicate equivalent outreach
existing human reply making message obsolete
campaign paused
daily limit reached
sender disabled/unhealthy
```

- [ ] **Step 2: Implement single transactional pre-send check**

Immediately before dispatch, reread current approval, DNC, thread, campaign, sender, and quota state in one transaction. Do not rely only on earlier UI state.

- [ ] **Step 3: Add idempotency key**

Derive from campaign + lead + recipient + approved-content hash + sequence stage. Repeated queue/dispatch must not create a second send.

- [ ] **Step 4: Prove mock sending**

Approved eligible draft -> one outbound message/thread. Repeat call -> same result/no second message.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_send_eligibility.py tests/integration/test_mock_send.py -q
git add backend/src/scout_email/messaging backend/tests
git commit -m "feat: add fail-closed message eligibility and mock sender"
```

---

### Task 20: Integrate n8n Gmail send contract without giving Writer direct Gmail access

**Files:**
- Create: `n8n/workflows/send-approved.json`
- Modify: `backend/src/scout_email/messaging/routes.py`
- Modify: `backend/src/scout_email/messaging/service.py`
- Create: `backend/tests/integration/test_n8n_send_contract.py`

**Interfaces:**
- Backend produces a signed/secret-protected n8n handoff payload containing immutable approved subject/body, recipient, and backend message ID.
- n8n sends through Gmail OAuth and calls backend completion endpoint with Gmail `message_id` and `thread_id`.

- [ ] **Step 1: Test handoff payload cannot override approved copy**

Completion endpoint accepts provider identifiers/status only. It must never accept replacement subject/body.

- [ ] **Step 2: Implement n8n workflow**

Workflow sequence:

```text
Webhook -> verify shared secret -> Gmail Send -> callback success/failure -> return result
```

Use Gmail credentials in n8n credential storage, not repository files.

- [ ] **Step 3: Add sender health/config gate**

Real Gmail mode requires explicit `SEND_MODE=gmail`, configured n8n webhook, enabled sender record, and operational checklist confirming SPF/DKIM/DMARC setup. Missing configuration fails closed.

- [ ] **Step 4: Test backend contract with mocked n8n webhook**

No live Gmail in automated tests.

- [ ] **Step 5: Commit**

```bash
git add n8n/workflows/send-approved.json backend/src/scout_email/messaging backend/tests/integration/test_n8n_send_contract.py
git commit -m "feat: connect approved messages to Gmail through n8n"
```

**M5 gate:** In mock mode, attempt every forbidden send path and confirm all are blocked. After the M4 quality gate and explicit Gmail setup, send only a controlled test message to an address you own before any outreach campaign.

---

# M6 — Replies, Bounces, DNC

### Task 21: Implement reply sync ingestion, thread matching, classification, and atomic stop behavior

**Files:**
- Create: `backend/src/scout_email/replies/schemas.py`
- Create: `backend/src/scout_email/replies/classifier.py`
- Create: `backend/src/scout_email/replies/service.py`
- Create: `backend/src/scout_email/replies/routes.py`
- Create: `n8n/workflows/reply-sync.json`
- Create: `backend/tests/integration/test_reply_sync.py`

**Interfaces:**
- n8n sends new Gmail message metadata/body to `POST /replies/sync` using Gmail thread/message IDs.
- Reply classes are exactly: POSITIVE, INTERESTED_BUT_LATER, QUESTION, REFERRAL, NOT_INTERESTED, UNSUBSCRIBE, AUTO_REPLY, BOUNCE, UNKNOWN.

- [ ] **Step 1: Test idempotent reply ingestion**

Same Gmail message ID twice -> one reply record and one set of state changes.

- [ ] **Step 2: Implement deterministic preclassification for obvious bounces/auto-replies/opt-outs**

Use clear headers/content signals before spending an LLM call; ambiguous business replies go through the structured reply classifier.

- [ ] **Step 3: Make stop behavior atomic**

When a human reply/opt-out/bounce is persisted, cancel eligible pending follow-up jobs in the same transaction.

- [ ] **Step 4: Produce reviewer-facing reply intelligence**

Persist classification, summary, intent score, extracted questions, and recommended action. Do not auto-send sales replies.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/integration/test_reply_sync.py -q
git add backend/src/scout_email/replies n8n/workflows/reply-sync.json backend/tests/integration/test_reply_sync.py
git commit -m "feat: track and classify Gmail replies"
```

---

### Task 22: Implement global do-not-contact and bounce invalidation

**Files:**
- Create: `backend/tests/unit/test_dnc.py`
- Create: `backend/tests/integration/test_bounce_handling.py`
- Modify: `backend/src/scout_email/replies/service.py`
- Modify: `backend/src/scout_email/messaging/eligibility.py`

**Interfaces:**
- DNC matching supports normalized email, canonical domain, and normalized business identity.
- Hard bounce invalidates the contact and blocks future sends.

- [ ] **Step 1: Test DNC precedence over campaign rules**

A campaign cannot override a global DNC hit even if the draft was approved earlier.

- [ ] **Step 2: Test unsubscribe ingestion creates DNC record**

The reply and DNC write occur atomically; pending follow-up jobs are cancelled.

- [ ] **Step 3: Test hard bounce invalidates contact**

Set contact status INVALID and lead to CONTACT_NEEDED/NO_CONTACT as appropriate. Future eligibility must block it.

- [ ] **Step 4: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_dnc.py tests/integration/test_bounce_handling.py -q
git add backend/src/scout_email backend/tests
git commit -m "feat: enforce global DNC and bounce invalidation"
```

**M6 gate:** Feed simulated positive reply, unsubscribe, auto-reply, and hard bounce events. Confirm correct thread association, no duplicate ingestion, and cancellation of incompatible pending work.

---

# M7 — Follow-up, n8n Orchestration, Analytics, Deployment, E2E

### Task 23: Implement one intelligent approval-gated follow-up

**Files:**
- Create: `backend/src/scout_email/replies/followup.py`
- Create: `n8n/workflows/follow-up.json`
- Create: `backend/tests/unit/test_followup_eligibility.py`
- Create: `backend/tests/integration/test_followup_flow.py`

**Interfaces:**
- Follow-up strategies: `SHORT_BUMP|ADD_NEW_OBSERVATION|ADD_CONCRETE_IDEA|DO_NOT_FOLLOW_UP`.
- V1 maximum follow-up stage: 1.

- [ ] **Step 1: Test eligibility**

No reply + elapsed configured delay + valid thread/contact + campaign active -> candidate allowed. Any reply/bounce/DNC/manual stop -> not allowed.

- [ ] **Step 2: Generate follow-up through Writer/Critic-style evidence controls**

The follow-up receives original research/angle/email and explicitly gathered new evidence if any; it cannot invent a new observation.

- [ ] **Step 3: Require independent critique and human approval**

Same content-hash approval semantics as first touch.

- [ ] **Step 4: Ensure same-thread send contract**

Gmail handoff includes existing thread ID and records stage `1`.

- [ ] **Step 5: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_followup_eligibility.py tests/integration/test_followup_flow.py -q
git add backend/src/scout_email/replies n8n/workflows/follow-up.json backend/tests
git commit -m "feat: add one approval-gated intelligent follow-up"
```

---

### Task 24: Add coarse-grained n8n campaign/research workflows

**Files:**
- Create: `n8n/workflows/campaign-scout.json`
- Create: `n8n/workflows/lead-research.json`
- Create: `backend/tests/integration/test_orchestration_contracts.py`

**Interfaces:**
- Campaign workflow: trigger -> create Scout jobs -> poll job completion -> enqueue qualified leads.
- Research workflow: enrich -> crawl/evidence -> research -> strategy -> write -> critique -> human review queue.

- [ ] **Step 1: Define backend API contract tests before workflow JSON**

Assert 202 job responses include stable `job_id`, `status_url`, and correlation ID.

- [ ] **Step 2: Create n8n workflows with backend-only domain decisions**

n8n routes statuses and waits; it does not duplicate dedupe/scoring/prompts/evidence logic in Function nodes.

- [ ] **Step 3: Add failure branches**

FAILED/RETRY/SKIPPED job states must route to bounded retry/manual visibility instead of silently disappearing.

- [ ] **Step 4: Run contract tests and commit**

```bash
cd backend
uv run pytest tests/integration/test_orchestration_contracts.py -q
git add n8n/workflows backend/tests/integration/test_orchestration_contracts.py
git commit -m "feat: orchestrate scouting and research with n8n"
```

---

### Task 25: Add campaign metrics and structured operational events

**Files:**
- Create: `backend/src/scout_email/metrics/service.py`
- Create: `backend/src/scout_email/metrics/routes.py`
- Modify: `backend/src/scout_email/logging.py`
- Create: `backend/tests/integration/test_metrics.py`

**Interfaces:**
- API: `GET /campaigns/{id}/metrics` returns counts and ratios from spec §41.
- Structured events contain event type, correlation ID, campaign/lead/job IDs when applicable, outcome, duration; no secrets/tokens.

- [ ] **Step 1: Test funnel counts from seeded records**

Verify discovered, qualified, researched, contactable, drafted, critic-approved, human-approved, sent, bounced, replied, positive, skipped.

- [ ] **Step 2: Calculate ratios defensively**

Zero denominators return `0.0`, never errors/NaN.

- [ ] **Step 3: Add structured event logging to milestone transitions**

Ensure API keys/OAuth tokens and raw credential headers are filtered.

- [ ] **Step 4: Run and commit**

```bash
cd backend
uv run pytest tests/integration/test_metrics.py -q
git add backend/src/scout_email/metrics backend/src/scout_email/logging.py backend/tests/integration/test_metrics.py
git commit -m "feat: add outreach funnel metrics and observability"
```

---

### Task 26: Dockerize local stack and document first-run setup

**Files:**
- Create: `backend/Dockerfile`
- Create: `browser-worker/Dockerfile`
- Create: `docker-compose.yml`
- Create: `README.md`
- Modify: `.env.example`
- Modify: `.gitignore`
- Create: `backend/tests/integration/test_config_fail_closed.py`

**Interfaces:**
- `docker compose up -d` starts `n8n`, `outreach-api`, and `browser-worker` with persistent `data`/`n8n_data` volumes.

- [ ] **Step 1: Add config fail-closed tests**

`SEND_MODE=gmail` with missing n8n/Gmail handoff configuration must refuse startup or mark sender disabled; it must never silently fall back to a send path.

- [ ] **Step 2: Build backend image using uv lockfile**

Run application as non-root where practical. Mount only runtime data/config required.

- [ ] **Step 3: Build browser image with Playwright Chromium dependencies**

Do not install unrelated desktop packages.

- [ ] **Step 4: Compose services**

Persist:

```text
./data
./n8n_data
```

Expose only the local ports needed by the operator. Use service DNS names internally.

- [ ] **Step 5: Write exact README runbook**

Document:

```text
1. copy .env.example -> .env
2. configure optional LLM provider
3. docker compose up -d
4. run Alembic upgrade
5. import n8n workflows
6. configure n8n Gmail OAuth only when M4 quality gate is complete
7. create campaign
8. run Scout
9. review approval queue
10. enable mock/test send first
11. configure real Gmail and send a self-addressed smoke test
12. begin low-volume campaign
```

Include troubleshooting for browser-worker unavailable, Maps selector smoke failure, model rate limit, crawl timeout, invalid model JSON, n8n callback failure, and DNC block.

- [ ] **Step 6: Validate compose**

```bash
docker compose config
docker compose build
docker compose up -d
docker compose ps
curl -fsS http://localhost:8000/health
```

- [ ] **Step 7: Commit**

```bash
git add backend/Dockerfile browser-worker/Dockerfile docker-compose.yml README.md .env.example .gitignore backend/tests/integration/test_config_fail_closed.py
git commit -m "chore: package Scout Email for local deployment"
```

---

### Task 27: Add complete fixture E2E acceptance test and release verification script

**Files:**
- Create: `backend/tests/e2e/test_full_v1_flow.py`
- Create: `backend/tests/fixtures/e2e/maps_leads.json`
- Create: `backend/tests/fixtures/e2e/site/`
- Create: `scripts/verify_v1.sh`
- Modify: `Makefile`

**Interfaces:**
- E2E runs without Google, Gmail, or a paid/provider dependency by substituting fixture browser, fake LLM provider, and mock sender behind the same production interfaces.

- [ ] **Step 1: Write the end-to-end test first**

Test this exact flow:

```text
campaign
-> Maps fixture returns leads
-> normalization/deduplication
-> qualification
-> website/contact enrichment
-> crawl + desktop/mobile evidence records
-> Researcher dossier
-> CONTACT strategy with evidence IDs
-> Writer draft with claim mappings
-> Critic APPROVE
-> human approval
-> mock send + thread
-> simulated positive reply
-> reply classification
-> pending follow-up cancelled
-> metrics updated
```

- [ ] **Step 2: Add negative E2E case**

A business with insufficient evidence/excellent existing presence must reach SKIP and never produce an outbound message.

- [ ] **Step 3: Add duplicate/idempotency E2E case**

Repeat scout, send callback, and reply ingestion. Counts must remain stable.

- [ ] **Step 4: Create verification script**

`scripts/verify_v1.sh` must run:

```bash
set -euo pipefail
cd backend
uv run alembic upgrade head
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/e2e -q
cd ../browser-worker
uv run pytest -q
cd ..
docker compose config >/dev/null
```

- [ ] **Step 5: Run full verification**

```bash
bash scripts/verify_v1.sh
```

Expected: all tests pass; no live Maps or Gmail request occurs during default verification.

- [ ] **Step 6: Run authorized live smoke sequence manually**

Only after default verification passes:

```text
1. enable live Maps smoke and fetch <=3 businesses
2. research one non-sensitive public business without sending
3. inspect evidence and generated draft manually
4. send a Gmail test only to an address you own
5. inject/reply from that address and verify thread classification
6. disable test artifacts or mark the test campaign as internal
```

- [ ] **Step 7: Commit**

```bash
git add backend/tests/e2e backend/tests/fixtures scripts/verify_v1.sh Makefile
git commit -m "test: verify complete Scout Email V1 workflow"
```

**M7 gate / V1 release gate:** `bash scripts/verify_v1.sh` passes from a clean checkout; the opt-in Maps smoke works; one owned-address Gmail smoke works after explicit configuration; no sending path bypasses approval/DNC/idempotency; replies cancel follow-ups correctly; README reproduces setup from scratch.

---

## Execution Order and Dependency Graph

```text
M0
Task 1 bootstrap
  -> Task 2 schema
  -> Task 3 repositories/states
  -> Task 4 campaigns

M1
Task 5 normalization/dedupe/scoring
  -> Task 6 jobs
  -> Task 7 browser worker
  -> Task 8 Scout integration

M2
Task 9 enrichment
  -> Task 10 crawl/audit
  -> Task 11 evidence/screenshots

M3
Task 12 LLM gateway/context
  -> Task 13 Researcher
  -> Task 14 Strategy

M4
Task 15 playbook
  -> Task 16 Writer
  -> Task 17 Critic + manual quality gate

M5
Task 18 approval
  -> Task 19 eligibility/mock sender
  -> Task 20 n8n/Gmail contract

M6
Task 21 replies
  -> Task 22 DNC/bounces

M7
Task 23 follow-up
  -> Task 24 n8n orchestration
  -> Task 25 metrics
  -> Task 26 Docker/runbook
  -> Task 27 E2E/release verification
```

Tasks within a milestone should be merged only after their local tests pass. Milestone gates are mandatory checkpoints; they are specifically intended to prevent downstream complexity from hiding failures in upstream lead quality, evidence provenance, writing integrity, or send safety.

---

## Cross-Cutting Test Matrix

| Risk | Required proof |
|---|---|
| Maps DOM changes | fixture extractor tests + opt-in <=3-result live smoke |
| Duplicate businesses | exact-domain/phone precedence + repeated-scout integration test |
| Wrong contact | public-source provenance required; no guessed-email function exists |
| Website unavailable | per-lead typed failure; campaign continues |
| Browser crash | bounded timeout/retry and job lease recovery |
| LLM malformed output | Pydantic rejection + one repair attempt + typed failure |
| Hallucinated personalization | claim/evidence IDs + Critic deterministic hard fail |
| Generic email | banned phrase scan + recent similarity + Critic genericness test |
| Human edits after approval | approval content hash invalidated |
| Duplicate sends | transactional eligibility + unique idempotency key |
| Opt-out race | DNC check immediately before send + atomic cancellation on reply |
| Reply duplicates | Gmail message ID uniqueness/idempotent ingestion |
| Follow-up after reply | same-transaction reply persist + follow-up cancellation |
| Secret leakage | env/n8n credential storage + log filtering tests |
| Accidental live sending | `SEND_MODE=mock` default + explicit Gmail config gate |

---

## Operational Defaults for First Real Campaign

These are safe initial operating defaults, not permanent product limits:

```yaml
scout:
  maps_browser_concurrency: 1
  target_leads: 50

research:
  http_concurrency: 5
  browser_concurrency: 1
  max_pages_per_site: 12

writing:
  critic_rewrite_limit: 2
  human_approval: true

sending:
  max_per_day: 5
  send_mode: gmail
  business_hours_only: true

follow_up:
  enabled: true
  max_followups: 1
```

Increase throughput only after observing stable browser behavior, low bounce rate, correct DNC behavior, and consistently good human approval outcomes. Technical provider limits are never treated as outreach targets.

---

## Final Definition of Done

Implementation is complete only when all of the following are true at the same commit:

- A fresh local checkout can be configured from `.env.example` and started through Docker Compose.
- Alembic creates the full schema from an empty SQLite database.
- A campaign with multiple search terms and locations can be created, paused, and resumed.
- Google Maps browser Scout can return normalized leads and repeated scouting does not duplicate them.
- Website verification distinguishes LIVE/BROKEN/NO_WEBSITE/SOCIAL_ONLY/PARKED/UNCERTAIN.
- Every public business email has source provenance; the system never silently guesses one.
- Relevant website pages are crawled with bounded context and browser fallback.
- Desktop/mobile screenshots and technical/textual evidence are persisted with stable IDs.
- Researcher and Strategist outputs validate against schemas and may correctly choose SKIP.
- Every CONTACT strategy references evidence IDs.
- Writer drafts map material claims back to evidence and obey the versioned WEBERAISE playbook.
- Critic rejects unsupported, wrong-company, generic, fake-familiarity, duplicate, or DNC-invalid drafts.
- Human approval is bound to the exact message content hash; editing invalidates prior approval.
- Sender rechecks approval/contact/DNC/thread/quota/sender health immediately before dispatch.
- Mock sending is the default and is fully testable without Gmail.
- Real Gmail uses n8n OAuth and cannot alter approved subject/body.
- Gmail message/thread IDs are persisted and reply ingestion is idempotent.
- Replies, bounces, opt-outs, and manual stops prevent incompatible follow-ups.
- V1 produces at most one follow-up candidate and still requires human approval.
- Campaign funnel metrics and outcome metadata are queryable.
- All unit, integration, E2E, and browser fixture tests pass through `scripts/verify_v1.sh`.
- Opt-in live Maps and owned-address Gmail smoke tests pass before the first external campaign.
- No V1 non-goal has been added merely for architectural elegance.

When these conditions hold, the system satisfies the approved specification and is ready for controlled low-volume WEBERAISE outreach.