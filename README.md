# Scout Email

> A structured, local-first pipeline for discovering prospects and preparing relevant outreach.

Scout Email turns an otherwise fragmented process—searching for businesses, qualifying them, finding the right contact, understanding their online presence, and drafting a useful first message—into one reviewable workflow.

> [!IMPORTANT]
> This repository is under active development. The current focus is a dependable research and approval pipeline, not unattended bulk sending.

## Intended workflow

```text
search brief
  └─> discover businesses
       └─> collect public signals
            └─> qualify + deduplicate
                 └─> identify contact path
                      └─> draft personalized outreach
                           └─> human review
                                └─> approved delivery
```

## Design goals

- **Relevant leads over large lists** — qualification happens before drafting
- **Evidence-backed personalization** — messages should reference real, useful observations
- **Review before delivery** — the operator remains in control of what gets sent
- **Traceable decisions** — each lead keeps its source, status, reasoning, and history
- **Low-cost operation** — local tools and free-first providers where practical
- **Replaceable components** — search, enrichment, writing, and delivery are separate stages

## System boundaries

| Stage | Output |
| :-- | :-- |
| Discovery | Candidate businesses and source URLs |
| Qualification | Fit score, reasons, and duplicate handling |
| Enrichment | Public business and contact signals |
| Personalization | A prospect-specific outreach draft |
| Approval | Explicit operator decision and any edits |
| Delivery | Send result, timestamps, and follow-up state |

## Current direction

The first use case is website-focused outreach for small businesses. The architecture is intentionally broader: each stage can later support different lead sources, qualification policies, message models, and delivery channels without rewriting the full pipeline.

