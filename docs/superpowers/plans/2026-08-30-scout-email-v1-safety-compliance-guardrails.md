# Scout Email V1 Safety & Compliance Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the cross-cutting safety, compliance, and network-boundary requirements that the master V1 plan depends on before any external outreach is enabled.

**Architecture:** These guardrails are implemented inside the existing backend/browser boundaries rather than as a new subsystem. URL/network policy is enforced centrally before HTTP or browser navigation. Outreach compliance is resolved into a deterministic per-message policy before send eligibility, and the generated compliance footer/opt-out text becomes part of the exact content hash that receives human approval.

**Tech Stack:** Existing Scout Email V1 stack; Python ipaddress/socket/url parsing, FastAPI/Pydantic, SQLite, pytest/respx, Playwright request interception.

**Spec:** `docs/superpowers/specs/2026-08-30-scout-email-system-design.md`

**Master Plan:** `docs/superpowers/plans/2026-08-30-scout-email-v1-implementation-plan.md`

## Global Constraints

- This plan is mandatory before the M5 real-Gmail release gate in the master plan.
- Public website research must not permit arbitrary access to loopback, link-local, private-network, metadata-service, file, or non-HTTP(S) destinations.
- Redirects are revalidated at every hop.
- Browser automation must use a dedicated persistent profile owned by Scout Email or isolated ephemeral contexts; it must not silently inherit unrelated personal Chrome sessions/cookies.
- Sender identity and opt-out behavior must be explicit and truthful.
- Jurisdiction-specific rules are configuration/policy data, not model decisions.
- Compliance content is generated deterministically, not improvised by the Writer.
- Human approval must cover the exact final subject/body/footer that will be sent.
- A compliance-policy failure blocks sending rather than silently choosing a permissive default.

---

### Guardrail Task A: Central URL and network-access policy

**Files:**
- Create: `backend/src/scout_email/common/url_policy.py`
- Create: `backend/tests/unit/test_url_policy.py`
- Modify: `backend/src/scout_email/crawling/crawler.py`
- Modify: `backend/src/scout_email/enrichment/website.py`
- Modify: `backend/src/scout_email/browser/client.py`

**Interfaces:**
- Produces `validate_public_http_url(url: str) -> SafeURL`.
- Produces `resolve_and_validate_host(hostname: str) -> list[ipaddress._BaseAddress]`.
- Every HTTP/browser navigation path must call this policy before first request and after each redirect.

- [ ] **Step 1: Write rejection tests**

Reject at minimum:

```text
file:///etc/passwd
ftp://example.com
http://localhost/
http://127.0.0.1/
http://[::1]/
http://169.254.169.254/
http://10.0.0.10/
http://172.16.0.10/
http://192.168.1.10/
```

- [ ] **Step 2: Write redirect-revalidation test**

Mock `https://public.example/` returning a redirect to `http://127.0.0.1/admin`; assert the crawler blocks the redirect before requesting the private destination.

- [ ] **Step 3: Implement DNS/IP validation**

Resolve all A/AAAA answers and reject the host if any resolved address is loopback, private, link-local, multicast, reserved, unspecified, or otherwise non-public. Accept only `http` and `https` schemes.

- [ ] **Step 4: Wire into HTTP and browser clients**

The browser client must also intercept subresource/navigation requests that attempt prohibited network destinations where practical; top-level redirect/navigation validation is mandatory.

- [ ] **Step 5: Run tests**

```bash
cd backend
uv run pytest tests/unit/test_url_policy.py -q
```

Expected: all dangerous URL cases are blocked and normal public domains pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/scout_email/common/url_policy.py backend/src/scout_email/crawling/crawler.py backend/src/scout_email/enrichment/website.py backend/src/scout_email/browser/client.py backend/tests/unit/test_url_policy.py
git commit -m "security: enforce public-web navigation boundaries"
```

---

### Guardrail Task B: Isolate browser identity and persistent state

**Files:**
- Modify: `browser-worker/src/browser_worker/settings.py`
- Modify: `browser-worker/src/browser_worker/app.py`
- Modify: `browser-worker/src/browser_worker/maps.py`
- Modify: `browser-worker/src/browser_worker/render.py`
- Create: `browser-worker/tests/test_context_isolation.py`

**Interfaces:**
- Produces dedicated `BROWSER_PROFILE_DIR` under Scout Email runtime data when persistence is explicitly enabled.
- Default rendered-site research uses isolated contexts with no unrelated cookies/local storage.

- [ ] **Step 1: Test default context starts without personal cookies**

Create two independent contexts and assert cookies/local storage from one are unavailable to the other unless an explicit Scout Email-owned persistent profile is selected.

- [ ] **Step 2: Reject arbitrary host profile paths**

Configuration must not accept paths pointing to common personal Chrome/Chromium profile locations outside the Scout Email data directory.

- [ ] **Step 3: Implement controlled Maps profile behavior**

If Google Maps requires persistence for stability, use exactly one dedicated Scout Email Maps profile under the configured data directory. Do not import browser cookies from the user’s normal browser.

- [ ] **Step 4: Run and commit**

```bash
cd browser-worker
uv run pytest tests/test_context_isolation.py -q
git add src/browser_worker tests/test_context_isolation.py
git commit -m "security: isolate browser automation state"
```

---

### Guardrail Task C: Add sender profiles and deterministic compliance policy

**Files:**
- Create: `backend/src/scout_email/messaging/compliance.py`
- Create: `backend/src/scout_email/messaging/sender_profiles.py`
- Create: `backend/tests/unit/test_compliance_policy.py`
- Modify: `backend/src/scout_email/db/models.py`
- Create: `backend/migrations/versions/0002_sender_compliance.py`
- Modify: `backend/src/scout_email/campaigns/schemas.py`

**Interfaces:**
- Sender profile fields: display name, sender email, organization name, physical postal address, enabled flag, and policy region/home jurisdiction.
- Campaign may provide recipient jurisdiction when known; unknown jurisdiction resolves through an explicit configured default policy or blocks external sending if no policy is configured.
- Produces `resolve_compliance_policy(sender, campaign, lead) -> CompliancePolicy`.

- [ ] **Step 1: Write fail-closed policy tests**

Assert a real-send candidate with no enabled sender profile or no resolvable compliance policy is ineligible.

- [ ] **Step 2: Add migration and model**

Persist sender identity separately from API/OAuth credentials. Credentials remain in n8n/environment storage.

- [ ] **Step 3: Implement deterministic policy fields**

At minimum policy specifies:

```python
class CompliancePolicy(BaseModel):
    policy_id: str
    require_postal_address: bool
    require_opt_out_instruction: bool
    opt_out_text: str
    sender_identity_required: bool = True
```

No LLM chooses or rewrites these fields.

- [ ] **Step 4: Test sender truthfulness constraints**

Final From/display identity is sourced from the enabled sender profile and cannot be overridden by Writer output.

- [ ] **Step 5: Run migration/tests and commit**

```bash
cd backend
uv run alembic upgrade head
uv run pytest tests/unit/test_compliance_policy.py -q
git add src/scout_email/messaging src/scout_email/db/models.py migrations/versions/0002_sender_compliance.py src/scout_email/campaigns/schemas.py tests/unit/test_compliance_policy.py
git commit -m "feat: add deterministic outreach compliance policy"
```

---

### Guardrail Task D: Bind opt-out/footer content into approval and send eligibility

**Files:**
- Modify: `backend/src/scout_email/approval/service.py`
- Modify: `backend/src/scout_email/messaging/eligibility.py`
- Modify: `backend/src/scout_email/messaging/service.py`
- Create: `backend/tests/integration/test_compliance_approval_binding.py`

**Interfaces:**
- Produces `render_final_message(draft, sender_profile, compliance_policy) -> FinalMessage`.
- Approval hash is calculated from exact final subject + body + deterministic compliance footer, not the pre-footer draft.

- [ ] **Step 1: Test footer changes invalidate approval**

Approve a final message, modify sender postal address or compliance policy, render again, and assert send eligibility fails until the new exact content receives approval.

- [ ] **Step 2: Test opt-out instruction cannot be removed after approval**

Any send payload missing a required footer must fail eligibility even if the Writer draft itself was approved previously.

- [ ] **Step 3: Recheck compliance immediately before dispatch**

The same final transactional eligibility check used for DNC/quota must resolve the current sender profile and compliance policy.

- [ ] **Step 4: Run and commit**

```bash
cd backend
uv run pytest tests/integration/test_compliance_approval_binding.py -q
git add src/scout_email/approval/service.py src/scout_email/messaging tests/integration/test_compliance_approval_binding.py
git commit -m "feat: bind compliance footer to human approval"
```

---

### Guardrail Task E: Add retention/redaction and request-signing boundaries

**Files:**
- Create: `backend/src/scout_email/common/redaction.py`
- Create: `backend/src/scout_email/common/signing.py`
- Create: `backend/tests/unit/test_redaction.py`
- Create: `backend/tests/unit/test_signing.py`
- Modify: `backend/src/scout_email/logging.py`
- Modify: `backend/src/scout_email/messaging/routes.py`
- Modify: `backend/src/scout_email/replies/routes.py`

**Interfaces:**
- n8n callbacks/webhooks include timestamp + HMAC signature over raw body; backend rejects invalid/expired signatures.
- Structured logs redact configured secret/token/email-body fields where required.

- [ ] **Step 1: Test HMAC validation**

Valid signature within configured clock skew passes; modified body, wrong secret, or stale timestamp fails.

- [ ] **Step 2: Test secret redaction**

API keys, Authorization headers, OAuth tokens, and configured webhook secrets must never appear in structured logs.

- [ ] **Step 3: Add configurable retention command for runtime artifacts**

Provide a service/CLI operation that removes expired raw crawl bodies/screenshots according to configured retention while preserving lead/message outcome records and required evidence metadata. Default V1 retention may remain disabled until explicitly configured; the deletion behavior itself must be tested.

- [ ] **Step 4: Run and commit**

```bash
cd backend
uv run pytest tests/unit/test_redaction.py tests/unit/test_signing.py -q
git add src/scout_email/common src/scout_email/logging.py src/scout_email/messaging/routes.py src/scout_email/replies/routes.py tests/unit
git commit -m "security: sign callbacks and redact sensitive logs"
```

---

## Guardrail Release Gate

Before M5 real Gmail mode is enabled, verify all of the following:

```text
URL/network policy tests pass
browser contexts are isolated from personal profiles
sender profile is configured truthfully
compliance policy resolves deterministically
required opt-out/footer content is present
approval hash covers the final message including footer
DNC is rechecked immediately before send
n8n callbacks are authenticated
logs contain no credentials/tokens
SEND_MODE remains mock until the owned-address Gmail smoke test
```

Run:

```bash
cd backend
uv run pytest tests/unit/test_url_policy.py \
  tests/unit/test_compliance_policy.py \
  tests/integration/test_compliance_approval_binding.py \
  tests/unit/test_redaction.py \
  tests/unit/test_signing.py -q
cd ../browser-worker
uv run pytest tests/test_context_isolation.py -q
```

These guardrails are part of V1 completion, not optional hardening.