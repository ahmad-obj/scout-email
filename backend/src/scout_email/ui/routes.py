from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import ApprovalState
from scout_email.db.models import (
    AuditFinding,
    EmailDraft,
    Evidence,
    Lead,
    Screenshot,
    Strategy,
)
from scout_email.db.session import get_session

router = APIRouter(tags=["review-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


def _opportunity_score(strategy: Strategy | None) -> int | None:
    if strategy is None:
        return None
    try:
        components = json.loads(strategy.score_components_json or "{}")
        severity = float(components["severity"])
        evidence = float(components["evidence_confidence"])
        impact = float(components["business_impact"])
        fit = float(components["weberaise_fit"])
        explainability = float(components["explainability"])
        risk = float(
            components.get(
                "generic_speculation_risk", components.get("generic_risk", 0.5)
            )
        )
        score = (
            0.20 * severity
            + 0.20 * evidence
            + 0.25 * impact
            + 0.20 * fit
            + 0.10 * explainability
            + 0.05 * (1.0 - risk)
        )
        return round(score * 100)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return round(strategy.confidence * 100)


@router.get("/review")
async def review_queue(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(EmailDraft, Lead, Strategy)
            .join(Lead, Lead.id == EmailDraft.lead_id)
            .outerjoin(Strategy, Strategy.id == EmailDraft.strategy_id)
            .where(EmailDraft.approval_state == ApprovalState.PENDING.value)
            .order_by(EmailDraft.id)
        )
    ).all()
    items = [
        {
            "draft": draft,
            "lead": lead,
            "strategy": strategy,
            "score": _opportunity_score(strategy),
        }
        for draft, lead, strategy in rows
    ]
    return templates.TemplateResponse(
        request=request,
        name="queue.html",
        context={"items": items},
    )


@router.get("/review/{draft_id}")
async def review_draft(
    request: Request,
    draft_id: int,
    session: AsyncSession = Depends(get_session),
):
    draft = await session.get(EmailDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
    lead = await session.get(Lead, draft.lead_id)
    strategy = await session.get(Strategy, draft.strategy_id) if draft.strategy_id else None
    evidence = list(
        (
            await session.scalars(
                select(Evidence).where(Evidence.lead_id == draft.lead_id).order_by(Evidence.id)
            )
        ).all()
    )
    screenshots = list(
        (
            await session.scalars(
                select(Screenshot)
                .where(Screenshot.lead_id == draft.lead_id)
                .order_by(Screenshot.id)
            )
        ).all()
    )
    findings = list(
        (
            await session.scalars(
                select(AuditFinding)
                .where(AuditFinding.lead_id == draft.lead_id)
                .order_by(AuditFinding.id)
            )
        ).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="lead.html",
        context={
            "draft": draft,
            "lead": lead,
            "strategy": strategy,
            "score": _opportunity_score(strategy),
            "evidence": evidence,
            "screenshots": screenshots,
            "findings": findings,
        },
    )
