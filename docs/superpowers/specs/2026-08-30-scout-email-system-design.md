# Scout Email System — Technical Design Specification

**Status:** Approved design, implementation not started  
**Date:** 2026-08-30  
**Repository:** `manbtd0-cloud/scout-email`  
**Primary use case:** WEBERAISE cold outreach  
**Deployment target:** Local-first, self-hosted, zero-cost-first  
**V1 operating mode:** Human approval required before every outbound email

---

## 1. Purpose

Scout Email is a local-first, evidence-backed cold-outreach system for WEBERAISE.

Given a campaign such as:

```yaml
name: Lahore Dentists
searches:
  - dentist
  - dental clinic
  - cosmetic dentist
locations:
  - Lahore
target_leads: 100
```

the system should:

1. discover relevant businesses through an automated Chromium-driven Google Maps scouting flow;
2. normalize, deduplicate, and qualify those businesses;
3. verify and crawl each business's public website and relevant public online presence;
4. discover public business contact information without guessing addresses;
5. collect technical, textual, and visual evidence about the business and its website;
6. build a structured business dossier;
7. determine whether WEBERAISE has a credible sales opportunity;
8. choose one strong, evidence-backed persuasion angle rather than listing every weakness;
9. write a short, highly personalized cold email using WEBERAISE-specific writing rules;
10. independently critique the draft for genericness, hallucinations, tone, evidence integrity, and CTA quality;
11. require human approval, editing, regeneration, or rejection;
12. send approved mail through Gmail;
13. track threads, replies, bounces, opt-outs, and follow-ups;
14. store outcomes so later versions can learn which leads, angles, prompts, and writing patterns perform well.

The system is intentionally optimized for **small volumes of highly researched outreach**, not mass-mail blasting.

---

## 2. Product goals

### 2.1 Primary goals

- Produce outreach that feels individually researched rather than mail-merged.
- Keep the infrastructure effectively free for V1.
- Avoid dependence on paid lead databases such as Apollo or Clay.
- Reuse the previously proven browser-driven Google Maps scouting pattern.
- Keep every personalized claim traceable to collected evidence.
- Let the system decide **not to contact** a business when no compelling WEBERAISE opportunity exists.
- Preserve strict separation between research, strategy, writing, review, and sending permissions.
- Make model providers replaceable rather than tying the application to one vendor.
- Capture human edits and campaign outcomes for future optimization.

### 2.2 Success condition

A successful V1 should support this flow without manual business research:

```text
Industry: Dental clinics
Location: Lahore
Target: 50

50 discovered
32 qualified
25 successfully researched
21 valid public business emails
18 strong opportunities
18 personalized drafts
14 manually approved
14 sent
replies automatically attached to their leads
```

The exact counts are illustrative; the requirement is the complete end-to-end workflow.

---

## 3. Non-goals for V1

V1 explicitly does **not** require:

- automatic first-touch sending;
- multi-account sender rotation;
- high-volume bulk outreach;
- long automated follow-up sequences;
- autonomous handling of real sales conversations;
- a full CRM;
- a vector database;
- model fine-tuning;
- Kubernetes;
- Redis;
- PostgreSQL;
- LangChain or another mandatory agent framework;
- paid lead APIs;
- paid email-automation products;
- complex social-media scraping;
- multi-user support;
- cloud deployment;
- a sophisticated predictive lead-scoring model;
- a full SEO auditing suite.

These may be added only when real V1 usage demonstrates a need.

---

## 4. Core design principles

### 4.1 Evidence before persuasion

The Writer never receives permission to invent personalization. Every material claim in an email must be derived from a stored observation, public fact, or explicitly marked inference.

### 4.2 One strong angle beats a long audit

The Strategist chooses one primary credible reason the business should care about WEBERAISE. The email should not dump a list of technical issues.

### 4.3 Business impact beats design criticism

The system translates technical/design findings into plausible business consequences without pretending to know private analytics.

Example:

```text
Finding: booking CTA is buried on mobile.
Allowed implication: this may add friction for visitors trying to book.
Forbidden claim: this is costing you 40% of customers.
```

### 4.4 Strengths are useful evidence too

Research must record strengths as well as weaknesses. Strong outreach may begin from a positive mismatch, for example: polished Instagram presence combined with a weak website conversion path.

### 4.5 No forced outreach

A valid terminal result is:

```text
SKIP
```

If the business already has excellent web presence, has no meaningful fit, lacks reliable contact information, or has insufficient evidence, the system should not invent a reason to email it.

### 4.6 Human approval first, selective automation later

Phase 1 requires approval for every first-touch email and every follow-up. Selective auto-send may only be introduced after enough reviewed examples and real campaign outcomes exist to calibrate confidence thresholds.

### 4.7 Separate capabilities and permissions

Research, writing, reviewing, and sending are independent. The Writer cannot send. The Sender cannot rewrite. The Researcher cannot fabricate contact information.

### 4.8 Local-first and provider-neutral

n8n, Python workers, SQLite, Chromium, and crawling run locally. LLM access is abstracted behind a gateway so hosted or local models can be switched without changing business logic.

---

## 5. High-level architecture

```text
                         +----------------+
                         |      n8n       |
                         | Orchestration  |
                         +--------+-------+
                                  |
             +--------------------+--------------------+
             |                    |                    |
             v                    v                    v
      +-------------+      +-------------+      +-------------+
      |   Browser   |      |  Research   |      | LLM Gateway |
      |   Worker    |      |   Worker    |      |   Python    |
      | Playwright  |      |   Python    |      +------+------+ 
      | + Chromium  |      +------+------+             |
      +------+------+             |                    |
             |                    |                    v
             |              Crawl4AI/HTTP        Hosted/local
             |              parsing/audits          models
             |                    |                    |
             +--------------------+--------------------+
                                  |
                                  v
                              +--------+
                              | SQLite |
                              +---+----+
                                  |
                           +------+------+
                           | Approval UI |
                           +------+------+
                                  |
                                  v
                              Gmail API
```

### 5.1 Responsibility split

**n8n** is the control plane:

- campaign scheduling;
- workflow routing;
- queue triggers;
- retries/timeouts at workflow level;
- approval notifications/interactions;
- Gmail integration;
- follow-up scheduling;
- reply polling/triggering.

**Python services** perform domain work:

- browser scouting;
- crawling;
- extraction;
- technical checks;
- evidence creation;
- LLM context construction;
- structured agent calls;
- scoring;
- persistence helpers.

n8n must not contain giant scraper scripts or giant prompts.

---

## 6. End-to-end workflow

```text
Campaign
   |
   v
Google Maps Chromium Scout
   |
   v
Normalize / Deduplicate / Filter
   |
   v
Enricher
   |
   v
Researcher
   |
   v
Auditor + Strategist
   |
   v
Persuasion Brief
   |
   v
Writer
   |
   v
Critic
   |
   +--> REWRITE ----+
   |                |
   +--> REJECT       |
   |                 |
   v                 |
Human Approval <-----+
   |
   v
Sender
   |
   v
Follow-up Scheduler
   |
   v
Reply Tracker / Classifier
   |
   v
Outcome Store / Learning Data
```

---

## 7. Campaign model

A campaign defines a search scope and outreach policy.

Example:

```yaml
name: Lahore Dentists
searches:
  - dentist
  - dental clinic
  - cosmetic dentist
locations:
  - Lahore
target_leads: 100

qualification:
  minimum_rating: 3.5
  exclude_chains: true

sending:
  max_per_day: 10
  human_approval: required

follow_up:
  enabled: true
  max_followups: 1
```

### 7.1 Required campaign capabilities

- multiple search terms per campaign;
- one or more locations;
- target lead count;
- configurable qualification rules;
- configurable sending limit;
- human approval mode;
- configurable follow-up timing;
- campaign pause/resume;
- global do-not-contact enforcement regardless of campaign.

---

## 8. Scout

### 8.1 Primary source: browser-driven Google Maps

V1 reuses the proven browser-driven scouting concept rather than depending on a Maps API.

```text
Campaign search
    |
    v
Playwright launches Chromium
    |
    v
Open Google Maps
    |
    v
Enter query, e.g. "dentists in Lahore"
    |
    v
Iterate visible result list
    |
    v
Open business listings
    |
    v
Extract visible structured fields
    |
    v
Normalize + persist
```

### 8.2 V1 captured fields

When available:

- business name;
- category;
- address/location;
- phone;
- website;
- rating;
- review count;
- Maps listing URL;
- originating search query;
- source timestamp.

The Scout must tolerate missing fields.

### 8.3 Supplemental sources

The architecture permits later source adapters:

- OpenStreetMap;
- public business/industry directories;
- manual CSV import;
- permitted web search or other public sources.

All sources must normalize into the same lead interface. Google Maps is the primary V1 discovery source; others are supplements/fallbacks, not separate pipelines.

### 8.4 Scout output

```json
{
  "name": "ABC Dental Clinic",
  "category": "Dentist",
  "city": "Lahore",
  "address": "...",
  "phone": "+92...",
  "website": "https://abcdental.pk",
  "rating": 4.6,
  "review_count": 183,
  "maps_url": "...",
  "source": "google_maps_browser",
  "source_query": "dentist Lahore"
}
```

### 8.5 Browser worker isolation

The Google Maps worker must be isolated from the rest of the application because browser/DOM behavior is likely to change independently. A broken Maps selector must not break website research, writing, approval, or email tracking.

---

## 9. Lead normalization, deduplication, and qualification

### 9.1 Deterministic filtering first

Do not spend LLM calls on obviously bad candidates.

Initial filters include:

- duplicate business;
- outside requested geography;
- wrong category;
- permanently closed where detectable;
- excluded chains;
- previously contacted;
- global do-not-contact match;
- too little identifying information.

### 9.2 Deduplication signals

Use a weighted combination of:

- normalized business name;
- normalized phone number;
- canonical website/domain;
- normalized address;
- Maps URL/place identity where available.

Exact phone or exact canonical domain matches should dominate fuzzy name similarity.

### 9.3 Initial score

The first scoring model should be transparent and deterministic. Example signals:

```text
+ established-looking business
+ website exists
+ active public presence signals
+ high-value service category
+ proper domain/business email later found
+ multiple corroborating sources
- giant corporation outside target profile
- already excellent digital presence
- barely identifiable business
- previously contacted
```

The score is prioritization, not truth. V1 must log the component values that produced it.

### 9.4 Lead states

At minimum:

```text
DISCOVERED
QUALIFIED
LOW_PRIORITY
REJECTED
RESEARCH_PENDING
RESEARCHING
RESEARCHED
CONTACTABLE
NO_CONTACT
SKIPPED
```

---

## 10. Enricher

The Enricher finds and verifies evidence. It does not decide the sales angle.

### 10.1 Website verification states

```text
LIVE
BROKEN
NO_WEBSITE
SOCIAL_ONLY
PARKED
UNCERTAIN
```

Checks include:

- domain resolution;
- HTTP/HTTPS response;
- redirects;
- whether the destination is actually the business;
- parked/placeholder domain detection;
- social profile substituted for a website;
- obvious broken-site state.

`NO_WEBSITE` and `UNCERTAIN` must remain distinct.

### 10.2 Public contact discovery

Search the business's own public presence first:

```text
/
/contact
/contact-us
/about
/about-us
/team
/footer
/privacy
/terms
```

Extract explicitly published business emails such as:

```text
info@
hello@
contact@
sales@
support@
business@
```

Do not fabricate or silently guess individual addresses in V1.

Contact evidence must include provenance:

```json
{
  "email": "hello@example.com",
  "source_url": "https://example.com/contact",
  "type": "business",
  "confidence": 1.0
}
```

### 10.3 Social/profile discovery

Capture relevant public profiles linked from Maps, the website, or clearly verified public search results:

- Instagram;
- Facebook;
- LinkedIn company page;
- YouTube;
- other prominent business-owned public profiles.

V1 should not become a broad OSINT crawler.

---

## 11. Website crawling

### 11.1 Crawl strategy

Use cheap retrieval first and browser rendering only when necessary:

```text
website
   |
   v
HTTP / Crawl4AI
   |
   +-- success --> parse
   |
   +-- failure --> Chromium fallback
```

### 11.2 Page discovery

Prefer:

- `sitemap.xml`;
- top navigation;
- internal links from key pages.

Prioritize:

- homepage;
- about;
- services;
- products;
- pricing;
- contact;
- portfolio/work;
- testimonials;
- FAQ;
- location pages relevant to the campaign.

Avoid wasting context on:

- privacy/legal boilerplate unless needed for contacts;
- duplicate archives;
- hundreds of blog posts;
- tag/category archives;
- tracking URL variants.

V1 should normally cap research to approximately 5–20 useful pages per lead.

### 11.3 Page extraction schema

Each useful page should be reduced to structured content before LLM use:

```json
{
  "url": "https://example.com/services",
  "title": "Services",
  "headings": [],
  "important_text": "...",
  "calls_to_action": [],
  "forms": [],
  "links": [],
  "images": [],
  "technical_signals": {}
}
```

Boilerplate and duplicate content should be removed before model context is assembled.

---

## 12. Technical website audit

Where possible, website findings should be deterministic rather than subjective.

V1 checks may include:

- HTTP status;
- HTTPS;
- mobile viewport configuration;
- responsive-layout indicators;
- page title;
- meta description;
- canonical URL;
- `robots.txt`;
- sitemap presence;
- OpenGraph metadata;
- obvious broken internal links;
- image dimensions/file sizes;
- approximate page weight;
- favicon;
- structured data presence;
- CTA/link detection;
- social-link detection.

V1 does not need a comprehensive SEO platform.

Example:

```json
{
  "missing_meta_description": true,
  "homepage_size_mb": 8.2,
  "broken_internal_links": 4,
  "mobile_viewport_present": true
}
```

---

## 13. Visual inspection

Because WEBERAISE sells design/development, HTML-only analysis is insufficient.

### 13.1 V1 screenshots

Capture at minimum:

- desktop homepage;
- mobile homepage.

Optionally capture one additional high-value page when research/strategy needs it.

Screenshots are stored as files, not SQLite blobs.

Suggested layout:

```text
data/
  campaigns/
    <campaign-slug>/
      <lead-slug>/
        desktop-home.webp
        mobile-home.webp
        services.webp
```

### 13.2 Visual observations

A vision-capable model may assess:

- visual hierarchy;
- dated presentation;
- spacing/layout problems;
- CTA prominence;
- brand consistency;
- mobile presentation;
- overcrowding;
- trust presentation.

Subjective findings must be stored as observations with evidence, not objective facts.

---

## 14. Evidence model and provenance

Evidence is the backbone of the system.

Every useful finding gets a stable evidence record.

Example:

```json
{
  "id": 192,
  "lead_id": 281,
  "kind": "visual_observation",
  "claim": "The primary booking CTA is not visible in the first mobile viewport.",
  "source_type": "screenshot",
  "source_url": "https://example.com/",
  "artifact_path": "data/.../mobile-home.webp",
  "confidence": 0.94,
  "observed_at": "2026-08-30T00:00:00Z"
}
```

### 14.1 Provenance chain

The system should be able to trace:

```text
SOURCE
  |
  v
EVIDENCE
  |
  v
FINDING
  |
  v
STRATEGY
  |
  v
EMAIL CLAIM
```

The Strategist references evidence IDs. The Writer's claims reference strategy/evidence IDs. The Critic verifies those references before approval.

### 14.2 Claim classes

All significant claims should be classified as:

```text
OBSERVED_FACT
REASONABLE_INFERENCE
UNVERIFIED
```

`UNVERIFIED` claims cannot be used in outgoing copy.

---

## 15. Researcher

The Researcher turns cleaned evidence into a structured business dossier.

It answers questions such as:

- What does this company sell?
- Who appears to be its customer?
- What is its main value proposition?
- What actions does the site want visitors to take?
- Which services appear highest value?
- What differentiators does the company claim?
- How mature/established does the business appear?
- Which public digital channels does it actively maintain?
- What website strengths are evident?
- What website/digital mismatches are evident?

### 15.1 Dossier schema

Representative output:

```yaml
business:
  name: ABC Dental
  type: Cosmetic dental clinic
  location: Lahore

business_model:
  customers:
    - consumers
  primary_services:
    - implants
    - whitening
    - orthodontics
  primary_conversion: book appointment

presence:
  website: live
  instagram: active
  facebook: active

strengths:
  - strong patient reviews
  - professional social content
  - clear service specialization

website_findings:
  - booking CTA is weak on mobile
  - homepage hierarchy is crowded
  - treatment discovery requires several interactions
  - social branding appears stronger than website branding

technical_findings:
  - oversized homepage images
  - missing OpenGraph metadata

contact:
  email: info@abcdental.pk
  source: https://abcdental.pk/contact

confidence: 0.92
```

### 15.2 Research budget

Do not spend equal effort on every lead.

A representative policy:

```text
low score       -> stop or minimal enrichment
medium score    -> basic enrichment
strong score    -> website crawl + analysis
highest score   -> deeper screenshots/public-presence research
```

Exact thresholds remain configuration rather than hard-coded product logic.

### 15.3 Valid research outcomes

```text
COMPLETE
INSUFFICIENT_EVIDENCE
NO_CLEAR_OPPORTUNITY
RESEARCH_MORE
```

---

## 16. Auditor + Strategist

Architecturally Auditor and Strategist are separate concepts. V1 may implement them as one model call while preserving separate output sections so they can later split without changing downstream interfaces.

### 16.1 Auditor responsibilities

Evaluate WEBERAISE-relevant opportunity categories such as:

- no website;
- outdated visual design;
- poor mobile experience;
- weak conversion path;
- slow/technically weak site;
- weak trust presentation;
- poor service presentation;
- social-to-website quality mismatch;
- brand inconsistency;
- poor local discoverability;
- missing/weak CTA;
- broken/incomplete website.

Each candidate finding gets fields such as:

```json
{
  "problem": "Weak appointment conversion path",
  "severity": 8,
  "business_impact": 9,
  "confidence": 0.94,
  "evidence_ids": [192, 194],
  "safe_to_reference": true
}
```

### 16.2 Business-goal inference

The Strategist should reason about what the business likely wants, for example:

```text
dentist           -> appointments / higher-value treatments
real estate       -> buyer/seller leads
restaurant        -> reservations / foot traffic
law firm          -> qualified consultations
manufacturer      -> B2B inquiries
school            -> admissions inquiries
```

These are working hypotheses, not private facts.

### 16.3 Angle selection

The Strategist may generate several candidate angles but selects one primary angle.

Examples:

**No website**  
People can discover the company through Maps/social channels but there is no owned destination where the company fully controls presentation and conversion.

**Strong social, weak website**  
The business already earns attention, but the website does not carry the same level of polish or conversion clarity.

**Outdated website**  
The business appears more established/premium than its website communicates.

**Poor conversion path**  
Interested visitors face unnecessary friction in taking the next action.

**Excellent existing presence**  
`SKIP`.

### 16.4 Strategy decision states

```text
CONTACT
RESEARCH_MORE
LOW_PRIORITY
SKIP
```

### 16.5 Opportunity score dimensions

Suggested dimensions:

- problem severity;
- evidence confidence;
- likely business impact;
- WEBERAISE fit;
- ease of explaining the issue naturally;
- risk of sounding generic or speculative.

The score must be decomposable into component values rather than a mysterious number returned by the model.

### 16.6 Persuasion brief

The Strategist produces a compact brief for the Writer:

```yaml
lead: ABC Dental Clinic
decision: CONTACT
recipient_goal: increase appointment inquiries
primary_angle: social-to-website quality mismatch
observation: >
  Instagram presentation is polished and active while the mobile
  website's booking path is substantially less obvious.
business_implication: >
  Visitors arriving from social may face unnecessary friction before booking.
offer_connection: >
  WEBERAISE can bring the website closer to the same premium positioning
  while making the booking path clearer.
supporting_evidence_ids:
  - 192
  - 194
do_not_use:
  - minor favicon issue
  - speculative revenue claims
tone:
  - respectful
  - concise
  - specific
  - non-corporate
cta_strategy: low-friction conversation
```

---

## 17. WEBERAISE knowledge and writing playbook

The Writer must not improvise what WEBERAISE is or offers.

### 17.1 Knowledge files

Suggested repository-managed content:

```text
config/
  weberaise/
    company_context.md
    writing_rules.md
    banned_phrases.md
    cta_rules.md
    approved_examples.json
    rejected_patterns.json
```

### 17.2 `company_context.md`

Must define:

- what WEBERAISE does;
- what WEBERAISE does not do;
- positioning;
- service categories;
- portfolio/case-study facts that may be referenced;
- offer constraints;
- pricing policy if relevant;
- claims the model must never make;
- approved ways to describe the company.

### 17.3 Writing rules

Initial principles include:

- keep emails short;
- do not sound like an agency template;
- no fake compliments;
- no fake familiarity;
- avoid generic openings such as "I hope this email finds you well";
- avoid generic "I came across..." phrasing when stronger context exists;
- no exaggerated claims;
- mention one specific observation rather than many problems;
- connect the observation to a business outcome;
- explain WEBERAISE naturally and briefly;
- use a low-pressure CTA;
- avoid excessive corporate language;
- avoid common AI-marketing phrases;
- avoid repetitive structural patterns across recent emails.

### 17.4 Banned/generic phrase examples

Examples to flag, not necessarily a forever-fixed list:

```text
I hope this message finds you well
I recently came across
in today's digital landscape
elevate your online presence
take your business to the next level
seamless user experience
unlock your potential
transform your digital presence
```

---

## 18. Writer

### 18.1 Writer context

The Writer receives only curated context:

```text
BUSINESS SUMMARY
PRIMARY SALES ANGLE
VERIFIED EVIDENCE
RECIPIENT GOAL
WEBERAISE OFFER/CONTEXT
ALLOWED CLAIMS
FORBIDDEN CLAIMS
WRITING RULES
RELEVANT APPROVED EXAMPLES
RELEVANT RECENT CORRECTIONS
```

It must not receive the raw 50,000-token crawl unless a specific exceptional task requires it.

### 18.2 Drafting strategy

The Writer may produce two internal candidate drafts, score them, and emit only the stronger one. It should vary structure according to situation rather than using one fixed template.

Possible strategy labels:

```text
DIRECT_OBSERVATION
SOCIAL_MISMATCH
NO_WEBSITE
OUTDATED_SITE
CONVERSION_PROBLEM
LOCAL_BUSINESS
PREMIUM_BUSINESS
```

### 18.3 Preferred conceptual structure

Not a rigid template:

```text
specific observation
        |
        v
why it may matter
        |
        v
brief WEBERAISE relevance
        |
        v
simple low-friction CTA
```

### 18.4 Subject generation

Subject generation is a separate mini-step. Subjects should generally be:

- short;
- specific;
- not clickbait;
- not obviously promotional;
- consistent with the email body.

---

## 19. Critic

The Writer cannot approve itself.

The Critic receives the draft plus the evidence/strategy required to verify it.

### 19.1 Critic checks

- Does it sound mass-produced?
- Does the first line demonstrate real relevance?
- Is any factual claim unsupported?
- Could the email mostly work unchanged for 1,000 businesses?
- Is it insulting or unnecessarily negative?
- Is it too long?
- Does it use generic AI/agency language?
- Does it oversell?
- Is the CTA too demanding?
- Is WEBERAISE explained enough for the recipient to understand relevance?
- Is there a clear reason for the recipient to care?
- Is the structure too similar to recent sent emails?

### 19.2 Genericness test

The Critic should effectively ask:

> If the company name were replaced with another business, would most of this email still work?

If yes, the draft should normally be rewritten.

### 19.3 Evidence verification

Every meaningful claim maps to evidence or an allowed inference. Unsupported performance/revenue claims are rejected.

### 19.4 Critic output

```json
{
  "decision": "APPROVE",
  "scores": {
    "specificity": 94,
    "naturalness": 91,
    "persuasiveness": 86,
    "evidence_integrity": 100,
    "genericness": 9,
    "spamminess": 11
  },
  "issues": []
}
```

Or:

```json
{
  "decision": "REWRITE",
  "issues": [
    "Opening is generic",
    "CTA is too sales-heavy",
    "Claim about lost customers is unsupported"
  ]
}
```

Rewrites receive specific critique, not a vague "try again" instruction.

### 19.5 Hard rejection conditions

- hallucinated claim;
- wrong company;
- wrong recipient;
- uncertain/unverified email address;
- unsupported revenue/performance claim;
- insulting copy;
- fake familiarity;
- broken personalization;
- duplicate outreach;
- global do-not-contact match.

---

## 20. Human approval

V1 requires human review before first-touch sends and follow-ups.

### 20.1 Approval actions

```text
APPROVE & QUEUE
EDIT
REGENERATE
REJECT
```

### 20.2 Approval view

The UI should expose, at minimum:

- business name;
- location/category;
- lead/opportunity score;
- selected strategy;
- confidence;
- concise explanation of why the lead is worth contacting;
- supporting evidence links/screenshots;
- subject;
- editable body;
- approval actions.

The reviewer should not need to inspect the full crawl unless desired.

### 20.3 Human edits as data

When a reviewer edits a draft, store the exact before/after content and classify the change when possible:

```json
{
  "original": "Would you be interested in discussing how we could improve this?",
  "edited": "Would you like me to send over what I'd change?",
  "context": "cta",
  "industry": "dentist"
}
```

This data informs future few-shot examples and writing-rule updates. V1 does not require model fine-tuning.

---

## 21. Sender

The Sender receives only approved content. It cannot rewrite the message.

### 21.1 Pre-send checks

Before every send:

- approved state exists;
- recipient contact is verified;
- recipient is not globally do-not-contact;
- lead has not already received equivalent outreach;
- no active reply/conversation makes the scheduled message obsolete;
- sender account is enabled/healthy;
- campaign daily limit is not exceeded.

### 21.2 Gmail

Use Gmail OAuth/API integration, preferably through n8n for V1. Avoid storing a raw Gmail password.

Outbound mail should come from a normal WEBERAISE/person-associated mailbox rather than a conspicuous bot identity.

### 21.3 Sending cadence

V1 should start conservatively, e.g. approximately 5–10/day and later 10–20/day if bounce/reply/reputation signals remain healthy. Technical provider limits are not campaign targets.

Messages should be queued across configured business-hour windows rather than emitted as one burst.

### 21.4 Deliverability configuration

Operational setup should verify:

- SPF;
- DKIM;
- DMARC;
- TLS availability;
- sending account enabled state.

If sender authentication or account health is known to be broken, outbound sending must pause.

---

## 22. Conversation and thread tracking

Every sent email creates an outreach/conversation record.

Representative schema:

```json
{
  "lead_id": 281,
  "campaign_id": 10,
  "gmail_thread_id": "...",
  "message_id": "...",
  "sent_at": "...",
  "status": "sent",
  "followup_stage": 0,
  "reply_status": null,
  "bounce": false,
  "unsubscribed": false
}
```

Follow-ups should remain in the same Gmail thread whenever supported.

---

## 23. Follow-up engine

### 23.1 V1 sequence

```text
Initial email
   |
   +-- reply --> STOP
   |
   +-- no reply after configured period
            |
            v
       AI Follow-up #1
            |
            v
       Human approval
            |
            v
           send
            |
            v
           STOP
```

V1 supports at most one follow-up by default.

### 23.2 Follow-up intelligence

The Follow-up Writer receives:

- original research;
- original email;
- original angle;
- elapsed time;
- any relevant new public evidence gathered intentionally;
- campaign writing rules.

It may choose to:

```text
SHORT_BUMP
ADD_NEW_OBSERVATION
ADD_CONCRETE_IDEA
DO_NOT_FOLLOW_UP
```

A follow-up must add value when possible; "just following up" should not be the default behavior.

### 23.3 Stop conditions

Immediately stop automated follow-ups when:

- recipient replies;
- recipient opts out;
- message bounces;
- recipient asks not to be contacted;
- address is invalid;
- lead becomes irrelevant;
- user manually stops the sequence.

---

## 24. Reply tracker and classifier

n8n monitors Gmail threads/messages and associates new replies with existing outreach records.

### 24.1 Reply classes

```text
POSITIVE
INTERESTED_BUT_LATER
QUESTION
REFERRAL
NOT_INTERESTED
UNSUBSCRIBE
AUTO_REPLY
BOUNCE
UNKNOWN
```

### 24.2 Reply handling

For V1:

```text
reply
  |
  v
classifier
  |
  v
update lead/thread
  |
  v
stop follow-up if human reply/opt-out
  |
  v
notify reviewer
  |
  v
optional AI suggested response
  |
  v
HUMAN sends/edits response
```

Autonomous sales-conversation replies are explicitly deferred.

### 24.3 Reply intelligence

Representative output:

```json
{
  "classification": "POSITIVE",
  "summary": "Owner is interested but asks for approximate pricing.",
  "intent_score": 88,
  "questions": ["pricing"],
  "recommended_action": "respond_today"
}
```

---

## 25. Bounce and do-not-contact handling

### 25.1 Bounces

Hard bounce example:

```text
550 mailbox does not exist
```

must cause:

```text
contact -> INVALID
lead -> CONTACT_NEEDED or NO_CONTACT
future sends to that address -> BLOCKED
```

Campaign-level bounce metrics should be visible and repeated failures should be able to pause the campaign.

### 25.2 Global do-not-contact

The do-not-contact table is global, not campaign-local.

Suggested fields:

```text
email
domain
business_name
reason
source
created_at
```

Every send checks this table immediately before dispatch.

### 25.3 Compliance

The system targets public business outreach and must preserve truthful sender identity, non-deceptive subject/body content, opt-out handling, and applicable jurisdiction-specific requirements. Compliance rules should be configurable rather than assuming one country’s rules apply everywhere.

---

## 26. Learning and optimization data

V1 stores the data needed for future optimization but does not autonomously mutate production prompts based on sparse outcomes.

### 26.1 Store per message

- campaign;
- lead industry/location;
- selected strategy/angle;
- evidence IDs;
- writer prompt version;
- critic prompt version;
- strategist prompt version;
- model/provider identifiers;
- original draft;
- human edits;
- approved/rejected status;
- subject style;
- sent timestamp;
- bounce;
- reply class;
- positive/negative outcome;
- eventual client conversion when manually recorded.

### 26.2 Future performance comparisons

The data should support queries such as:

```text
positive reply rate by industry
positive reply rate by primary angle
approval rate by writer prompt version
bounce rate by lead source
reply rate by CTA style
```

Open-tracking pixels are not required for V1; delivered/bounced/replied/positive/client outcomes are more important.

---

## 27. LLM gateway

No business module should call a specific model SDK directly.

Suggested structure:

```text
backend/
  llm/
    gateway.py
    providers/
      gemini.py
      ollama.py
      openrouter.py   # optional later
    prompts/
      researcher/
      strategist/
      writer/
      critic/
      reply_classifier/
```

Conceptual interface:

```python
result = await llm.generate(
    task="strategy",
    context=context,
    response_model=StrategyOutput,
)
```

### 27.1 Model-routing principle

Use deterministic/local processing whenever it is sufficient.

```text
HTML cleaning / regex / dedupe / extraction
    -> no LLM

simple classification / basic summarization
    -> local model when quality is sufficient

strategy / writing / critique / complex understanding
    -> strongest available zero-cost hosted model by default
```

The initial hosted provider/model is configuration, not a permanent architectural dependency.

### 27.2 Zero-cost-first policy

The system should prefer:

1. deterministic code;
2. local models;
3. capable hosted free-tier models;
4. paid providers only if the user explicitly enables them later.

---

## 28. Context builder

Each agent receives a deliberately bounded context generated by a Context Builder.

```text
raw crawl + evidence + stored knowledge
                |
                v
          Context Builder
                |
                v
      task-specific compact context
                |
                v
               LLM
```

Examples:

**Researcher:** cleaned key-page content + important technical/visual evidence.  
**Strategist:** dossier + candidate evidence, not raw HTML.  
**Writer:** persuasion brief + allowed evidence + writing playbook + relevant examples.  
**Critic:** draft + claims/evidence + rules + recent similarity examples.

This reduces cost, context pollution, and hallucination risk.

---

## 29. Structured model outputs

Every production agent call must return a schema-validated structured result.

Do not route workflow control based on arbitrary prose.

Example:

```json
{
  "decision": "CONTACT",
  "confidence": 0.93,
  "primary_angle": "social_to_website_mismatch",
  "evidence_ids": [192, 194],
  "reason": "..."
}
```

Flow:

```text
LLM response
   |
   v
Pydantic/JSON schema validation
   |
   +-- valid --> persist + continue
   |
   +-- invalid --> bounded repair/retry
   |
   +-- still invalid --> FAILED/REVIEW state
```

---

## 30. Agent permissions

Logical roles and capabilities:

| Agent | Public web/browser | DB read | DB write | Email send |
|---|---:|---:|---:|---:|
| Scout | Yes | Limited | Leads/source records | No |
| Enricher | Yes | Yes | Contacts/evidence | No |
| Researcher | Evidence-focused | Yes | Research report | No |
| Auditor/Strategist | No arbitrary browsing | Yes | Findings/strategy | No |
| Writer | No | Limited curated context | Draft only | No |
| Critic | No | Evidence + draft | Review only | No |
| Sender | No | Approved message + safety state | Message status | Yes |
| Reply Classifier | No arbitrary browsing | Thread/context | Reply classification | No |

The application must preserve these boundaries even when multiple roles use the same underlying model provider.

---

## 31. Backend service structure

Suggested initial structure:

```text
backend/
  api/
  campaigns/
  scout/
  browser/
  leads/
  enrichment/
  crawling/
  evidence/
  research/
  strategy/
  writing/
  critique/
  contacts/
  messaging/
  replies/
  llm/
  db/
  common/
```

Each module owns one domain responsibility and exposes clear interfaces rather than sharing large mutable scripts.

---

## 32. Internal API

n8n should invoke stable application endpoints rather than internal Python implementation details.

Representative API:

```http
POST /campaigns
POST /campaigns/{campaign_id}/scout
POST /leads/{lead_id}/enrich
POST /leads/{lead_id}/research
POST /leads/{lead_id}/strategize
POST /leads/{lead_id}/write
POST /drafts/{draft_id}/critique
POST /drafts/{draft_id}/approve
POST /drafts/{draft_id}/reject
POST /messages/{message_id}/queue
POST /replies/sync
```

Long-running work should use jobs rather than keeping HTTP requests open indefinitely.

---

## 33. Job model and queue

Use a lightweight SQLite-backed job queue for V1.

### 33.1 Job states

```text
PENDING
RUNNING
COMPLETE
FAILED
RETRY
SKIPPED
```

### 33.2 Long-running pattern

```text
n8n
  |
  v
POST /jobs/research
  |
  v
202 Accepted + job_id

worker processes job
  |
  v
updates SQLite

n8n resumes/continues when job completes
```

### 33.3 Parallelism defaults

Keep concurrency configurable. Reasonable initial limits:

```text
HTTP crawling:      5–10 concurrent
Chromium work:      1–3 concurrent
LLM requests:       provider/rate-limit aware
email sending:      deliberately serialized/paced
```

---

## 34. Failure handling and retries

A single broken site must never stop an entire campaign.

Example crawl fallback:

```text
HTTP/Crawl4AI attempt
      |
      +-- fail --> retry
                       |
                       +-- fail --> Chromium fallback
                                          |
                                          +-- fail --> RESEARCH_MORE / FAILED
```

Required categories include:

- transient network failure;
- browser crash;
- changed/unknown DOM selector;
- crawl timeout;
- invalid HTML/content;
- model rate limit;
- invalid model JSON;
- missing evidence;
- Gmail/API failure;
- bounce;
- duplicate send attempt.

Retries must be bounded and idempotent where writes/sends are involved.

---

## 35. Database

Use SQLite for V1.

### 35.1 Core tables

```text
campaigns
campaign_searches

leads
lead_sources
lead_scores
websites
contacts
social_profiles

crawl_pages
screenshots
evidence

research_reports
audit_findings
strategies

email_drafts
email_draft_claims
email_reviews
email_edits

outbound_messages
email_threads
replies
followups

jobs

senders
do_not_contact
bounces

writing_rules
approved_examples
rejected_patterns
prompt_versions

campaign_metrics
```

### 35.2 Important relationships

```text
campaign
   |
   +--> many leads
             |
             +--> many sources
             +--> contacts
             +--> crawl pages/screenshots/evidence
             +--> research report
             +--> many audit findings
             +--> one or more strategies
             +--> drafts
                     |
                     +--> reviews/edits
                     +--> outbound message
                               |
                               +--> thread
                                       |
                                       +--> replies/followups
```

### 35.3 Database requirements

- foreign keys enabled;
- migrations from day one;
- created/updated timestamps on mutable business entities;
- uniqueness constraints for idempotent message dispatch;
- indexes on campaign/lead/status/thread/contact fields used by queues;
- raw secrets must not be stored in ordinary application tables.

---

## 36. Prompt versioning

Prompts are versioned application artifacts.

Examples:

```text
researcher:v1
strategist:v1
writer:v1
critic:v1
reply_classifier:v1
```

Every model-generated production artifact stores:

- prompt version;
- model/provider;
- generation timestamp;
- relevant configuration version.

This enables outcome comparisons between prompt/model versions.

---

## 37. Approval UI

V1 may use either:

1. n8n forms/interface where sufficient; or
2. a minimal local FastAPI-backed web UI.

Do not build a large React SaaS application before the workflow is proven.

Representative screen:

```text
+-----------------------------------------+
| ABC Dental                              |
| Lead score: 91                          |
| Strategy: Conversion                    |
| Confidence: 94%                         |
|                                         |
| Why contact them                        |
| Instagram -> website quality mismatch   |
|                                         |
| Evidence                                |
| [Mobile Screenshot] [Website] [Maps]    |
|                                         |
| Subject                                 |
| [editable]                              |
|                                         |
| Email                                   |
| [editable textarea]                     |
|                                         |
| [Approve] [Regenerate] [Reject]         |
+-----------------------------------------+
```

---

## 38. n8n workflows

V1 should keep workflows coarse-grained and delegate domain logic to the backend.

Suggested workflows:

### 38.1 Campaign scouting

```text
Manual/Scheduled Trigger
 -> load campaign
 -> create Scout job
 -> wait/poll completion
 -> enqueue qualification/enrichment
```

### 38.2 Lead research

```text
Qualified lead
 -> enrich
 -> crawl/audit
 -> research
 -> strategy
 -> write
 -> critique
 -> if approved-by-critic: human approval queue
```

### 38.3 Sending

```text
Human-approved draft
 -> final safety checks
 -> queue against daily limit
 -> Gmail send
 -> persist message/thread IDs
```

### 38.4 Reply synchronization

```text
Gmail trigger/poll
 -> match thread
 -> classify reply
 -> stop follow-up when required
 -> update metrics
 -> notify user
```

### 38.5 Follow-up

```text
Scheduled check
 -> eligible no-reply threads
 -> generate follow-up
 -> critique
 -> human approval
 -> send in same thread
```

---

## 39. Security and secrets

- Gmail uses OAuth/API credentials rather than raw passwords.
- LLM API keys live in environment/secrets configuration, not committed files.
- n8n credentials remain in n8n's credential store/secured environment.
- `.env` is ignored by Git.
- Logs should avoid dumping full secrets or OAuth tokens.
- Public business data can be stored for campaign operation, but collection should remain scoped to legitimate outreach needs.
- The browser worker must not silently reuse unrelated authenticated personal sessions.

---

## 40. Observability

At minimum record structured events for:

- campaign start/stop;
- Scout query started/completed;
- lead discovered/deduplicated/rejected;
- website/contact verification outcome;
- crawl success/failure;
- evidence generated;
- model call task/provider/version/status;
- strategy decision;
- critic decision;
- human approval/edit/rejection;
- send attempt/result;
- reply/bounce/opt-out;
- follow-up generated/sent/cancelled.

Avoid logging raw secrets. LLM request/response logging should be configurable because it may contain public business content and draft correspondence.

---

## 41. V1 analytics

Dashboard/reporting only needs:

```text
Leads discovered
Qualified
Researched
Contactable
Drafted
Critic-approved
Human-approved
Sent
Bounced
Replied
Positive replies
Rejected/skipped leads
```

Core ratios:

```text
qualification rate
contact discovery rate
human approval rate
bounce rate
reply rate
positive reply rate
```

Later versions may segment by industry, location, strategy, subject style, model, and prompt version.

---

## 42. Testing strategy

### 42.1 Unit tests

Required around deterministic logic:

- normalization;
- deduplication;
- scoring;
- email extraction;
- URL/domain canonicalization;
- evidence validation;
- state transitions;
- send eligibility;
- do-not-contact enforcement;
- follow-up eligibility;
- reply classification schema handling;
- prompt/context assembly boundaries.

### 42.2 Contract/schema tests

- every agent output validates against its Pydantic schema;
- invalid model output is rejected/repaired in a bounded way;
- n8n-facing API responses remain stable;
- provider adapters satisfy the common LLM interface.

### 42.3 Browser tests

Use fixtures/mocked pages for most selector/extraction tests. Maintain a small explicit live smoke test for the Google Maps/browser path that is not required for every unit-test run.

### 42.4 Integration tests

Test pipeline slices:

```text
raw lead -> normalized lead
lead -> website/contact evidence
fixtures -> research dossier
research dossier -> strategy
strategy -> draft -> critique
approved draft -> mocked sender
reply fixture -> classification + follow-up cancellation
```

### 42.5 End-to-end acceptance test

Using a small safe test campaign or controlled fixtures, prove:

```text
campaign
 -> leads
 -> one researched lead
 -> evidence-backed strategy
 -> draft
 -> critic pass
 -> manual approval
 -> mocked/test send
 -> stored thread
 -> simulated reply
 -> reply classification
```

Real Gmail sends should not be part of ordinary automated CI.

---

## 43. Docker/deployment

Initial `docker-compose.yml` should target local operation.

Likely services:

```text
n8n
outreach-api
browser-worker
```

Persistent volumes/directories:

```text
./data
./screenshots or ./data/artifacts
./n8n_data
```

A local Ollama installation may run on the host or as a container depending on hardware and networking simplicity.

Target operator experience:

```bash
docker compose up -d
```

plus documented first-run credential/model configuration.

---

## 44. V1 implementation milestones

### M1 — Scout

```text
campaign
 -> Google Maps browser search
 -> normalized businesses
 -> SQLite
```

Acceptance: a campaign can persist approximately 100 discovered businesses with deduplication and source metadata.

### M2 — Enrichment

```text
lead
 -> verify website
 -> discover public business email
 -> crawl selected pages
 -> capture desktop/mobile screenshots
 -> evidence
```

Acceptance: a qualifying lead produces a persisted evidence bundle with provenance.

### M3 — Intelligence

```text
evidence
 -> research dossier
 -> audit/opportunity assessment
 -> persuasion strategy
```

Acceptance: strategy output references evidence IDs and can choose CONTACT, RESEARCH_MORE, LOW_PRIORITY, or SKIP.

### M4 — Writing

```text
strategy
 -> WEBERAISE playbook
 -> draft
 -> independent critic
```

Acceptance: approximately 20–30 generated examples can be manually reviewed before sending integration is enabled.

### M5 — Approval + Gmail

```text
approval UI
 -> approve/edit/reject
 -> queue
 -> Gmail
 -> stored message/thread
```

Acceptance: no message can be sent without approved state in V1.

### M6 — Replies

```text
Gmail thread
 -> reply sync
 -> classification
 -> follow-up cancellation
 -> user notification
```

### M7 — Follow-up

```text
no reply after configured delay
 -> intelligent follow-up
 -> critic
 -> human approval
 -> same-thread send
```

At M7 completion, V1 is feature-complete.

---

## 45. V1 Definition of Done

V1 is complete when the system can:

1. create a campaign for a niche/location;
2. automatically scout Google Maps through Chromium and persist normalized leads;
3. deduplicate and deterministically qualify them;
4. verify websites and discover public business contact addresses;
5. crawl relevant pages and capture desktop/mobile evidence;
6. create a structured business dossier;
7. choose or reject an evidence-backed WEBERAISE opportunity;
8. write a personalized email using versioned WEBERAISE writing rules;
9. independently critique the email and reject unsupported/generic drafts;
10. show the draft and concise evidence in an approval interface;
11. prevent sending until explicitly approved;
12. send approved mail through Gmail while respecting campaign/DNC constraints;
13. attach replies/bounces to the correct thread and lead;
14. stop follow-ups immediately when required;
15. generate at most one approval-gated follow-up in V1;
16. expose basic campaign funnel and reply metrics;
17. retain enough prompt/strategy/edit/outcome metadata for later optimization.

---

## 46. Deferred evolution

After V1 has enough real campaign data, evaluate:

- separating Auditor and Strategist into distinct model calls;
- confidence-calibrated auto-send for narrow high-confidence cases;
- automatic selection of historically better strategies by industry;
- additional lead-source adapters;
- richer public-presence research;
- better dashboard/CRM features;
- multiple sender identities/accounts;
- additional follow-up strategies;
- local-vs-hosted model routing based on measured quality/cost;
- retrieval of relevant approved examples using embeddings only if simple metadata retrieval becomes insufficient;
- prompt experimentation/A-B testing;
- fine-tuning only after a sufficiently large, clean corpus exists;
- migration from SQLite/Postgres only if actual concurrency/scale requires it;
- cloud deployment only when local operation becomes a constraint.

---

## 47. Architectural invariants

The following should remain true even as the system evolves:

1. **No outbound email without an explicit send policy decision.**
2. **A Writer can never directly send.**
3. **A Sender can never silently rewrite approved copy.**
4. **Unverified personalized claims cannot be used.**
5. **Contacts must carry provenance/confidence; V1 does not silently guess addresses.**
6. **Global do-not-contact rules override campaign logic.**
7. **Replies/opt-outs/bounces cancel incompatible scheduled follow-ups.**
8. **Google Maps/browser scouting is an adapter, not the entire system architecture.**
9. **Model providers remain replaceable through the LLM gateway.**
10. **Raw crawls are reduced into task-specific context before most LLM calls.**
11. **Prompt/model versions are recorded with generated production artifacts.**
12. **The system may decide that a lead should not be contacted.**
13. **V1 prioritizes quality and evidence over outreach volume.**
14. **Infrastructure complexity is introduced only when real usage requires it.**

---

## 48. Initial technology choices

| Area | V1 choice |
|---|---|
| Orchestration | self-hosted n8n Community |
| Backend | Python + FastAPI + Pydantic |
| Persistence | SQLite with migrations |
| Browser automation | Playwright + Chromium |
| Website crawling | Crawl4AI + direct HTTP/parser path |
| LLM abstraction | custom provider-neutral gateway |
| Hosted intelligence | configurable strong free-tier model |
| Local model option | Ollama-compatible models |
| Email | Gmail API/OAuth, orchestrated by n8n |
| Approval UI | n8n UI/forms or minimal local FastAPI UI |
| Deployment | Docker Compose/local machine |
| Artifact storage | local filesystem paths referenced from SQLite |

---

## 49. Recommended first repository shape

```text
scout-email/
  README.md
  docker-compose.yml
  .env.example

  backend/
    pyproject.toml
    src/scout_email/
      api/
      campaigns/
      scout/
      browser/
      leads/
      enrichment/
      crawling/
      evidence/
      research/
      strategy/
      writing/
      critique/
      contacts/
      messaging/
      replies/
      llm/
      db/
      common/
    tests/

  config/
    weberaise/
      company_context.md
      writing_rules.md
      banned_phrases.md
      cta_rules.md
      approved_examples.json
      rejected_patterns.json

  n8n/
    workflows/

  data/                 # gitignored runtime data

  docs/
    superpowers/
      specs/
      plans/
```

The implementation plan may refine exact file names, but it must preserve the domain boundaries and architectural invariants defined in this specification.
