from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from scout_email.llm.context import sanitize_context


_TASK_INSTRUCTIONS = {
    "researcher": (
        "Build a bounded business research dossier using only the supplied persisted evidence and verified contacts. "
        "Every strength, website finding, and technical finding must cite supporting evidence IDs from the context. "
        "Do not invent facts, metrics, business consequences, contacts, or evidence IDs. "
        "Synthesize business model and presence only when the evidence supports them; absence of evidence is not a fact. "
        "A COMPLETE outcome requires at least one meaningful evidence-linked finding. "
        "If the supplied evidence cannot safely support a meaningful dossier, use RESEARCH_MORE, "
        "INSUFFICIENT_EVIDENCE, or NO_CLEAR_OPPORTUNITY as appropriate. "
        "Do not treat an HTTP 200 response by itself as a sales problem."
    ),
    "strategist": (
        "Make an outreach decision from the supplied research dossier, persisted evidence, and verified contacts. "
        "Do not enrich, rewrite, or complete the research dossier; strategy chooses whether and how to contact. "
        "Choose CONTACT only when a verified contact exists and at least one specific, evidence-backed, "
        "WEBERAISE-relevant opportunity is safe to reference. "
        "For CONTACT, choose exactly one primary persuasion angle and use only existing evidence IDs from "
        "safe-to-reference candidates as supporting evidence. "
        "Use RESEARCH_MORE only when specific missing information blocks a safe outreach decision, not merely "
        "because additional research is possible. "
        "A verified business contact is sufficient for safe outreach; exact decision-maker identity is not required. "
        "Knowledge of an incumbent vendor or active web-development contract is not required. "
        "Do not require proof that the prospect is actively buying or currently in-market. "
        "Those missing sales-qualification details must not by themselves justify RESEARCH_MORE. "
        "Use RESEARCH_MORE for missing information needed to substantiate a safe, evidence-backed outreach claim "
        "or when no verified contact exists; do not use it merely to eliminate normal cold-outreach uncertainty. "
        "LOW_PRIORITY and SKIP are valid outcomes when the opportunity itself is weak, irrelevant, or unsuitable. "
        "Do not invent facts, metrics, private analytics, or unsupported business consequences."
    ),
    "writer": (
        "Write a concise first-touch email from only the supplied safe evidence, research dossier, persuasion brief, "
        "WEBERAISE context, and writing rules. Every material prospect-specific factual or inferential statement in "
        "the subject or body must be represented in the claims array and cite supporting allowed evidence IDs. "
        "Do not hide extra factual assertions in prose outside the claims ledger. Reasonable inferences must stay "
        "cautious and probabilistic. Do not use fake compliments or gratuitous praise. Do not invent customer behavior, "
        "technical architecture, databases, ordering flows, private analytics, metrics, business consequences, "
        "comparable-client experience, or WEBERAISE capabilities not supported by the supplied context. "
        "Prefer one specific evidence-backed observation, explain WEBERAISE briefly, and use a proportionate low-pressure CTA."
    ),
    "critic": (
        "Audit the complete subject and body independently against the supplied claim ledger, evidence, and review rules. "
        "Do not assume the claim ledger is exhaustive: identify any material prospect-specific factual or inferential "
        "statement in the prose that is uncatalogued, unsupported, overstated, or inconsistent with its evidence. "
        "REWRITE or REJECT copy containing fake compliments, unsupported customer behavior, unsupported technical "
        "architecture or ordering-flow assumptions, invented metrics or consequences, misleading certainty, unsupported "
        "WEBERAISE capabilities or comparable-client experience, generic agency language, or other violations of the "
        "supplied writing and company rules. APPROVE only when the complete email is specific, natural, concise, and "
        "evidence-disciplined, not merely when the declared claims themselves are valid."
    ),
}


def build_system_prompt(*, task: str, prompt_version: str, repair: bool = False) -> str:
    if not task.strip():
        raise ValueError("task is required")
    if not prompt_version.strip():
        raise ValueError("prompt_version is required")

    base = (
        f"Task: {task}. Prompt version: {prompt_version}. "
        "Return only JSON that validates against the supplied schema. "
        "Do not add markdown fences, commentary, or fields outside the schema."
    )
    instructions = _TASK_INSTRUCTIONS.get(task.strip().casefold())
    if instructions:
        base = base + " " + instructions
    if repair:
        return (
            "Schema repair attempt. "
            + base
            + " Correct the previous invalid output using the validation feedback; do not change task intent."
        )
    return base


def build_user_prompt(context: Mapping[str, Any]) -> str:
    cleaned = sanitize_context(context)
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_repair_user_prompt(
    *,
    context: Mapping[str, Any],
    invalid_output: str,
    validation_error: str,
) -> str:
    payload = {
        "context": sanitize_context(context),
        "previous_invalid_output": invalid_output[:12_000],
        "validation_feedback": validation_error[:4_000],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
