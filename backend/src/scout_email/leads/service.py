from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import LeadState
from scout_email.common.errors import DuplicateOperationError
from scout_email.db.models import Lead, LeadScore as LeadScoreModel, LeadSource
from scout_email.leads.dedupe import match_existing_lead
from scout_email.leads.normalize import normalize_lead
from scout_email.leads.scoring import score_lead
from scout_email.leads.schemas import ExistingLead, LeadIngestResult, LeadSourceInput, RawLead


class LeadIngestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest(self, campaign_id: int, raw: RawLead, source: LeadSourceInput) -> LeadIngestResult:
        normalized = normalize_lead(raw)
        score = score_lead(normalized)

        if source.source_external_id:
            existing_source = (
                await self.session.execute(
                    select(LeadSource).where(
                        LeadSource.source == source.source,
                        LeadSource.source_external_id == source.source_external_id,
                    )
                )
            ).scalar_one_or_none()
            if existing_source is not None:
                existing_lead = await self.session.get(Lead, existing_source.lead_id)
                if existing_lead is None:
                    raise RuntimeError("Lead source points to a missing lead")
                if existing_lead.campaign_id != campaign_id:
                    raise DuplicateOperationError(
                        "source identity already belongs to another campaign"
                    )
                self._refresh_source(existing_source, source)
                await self._upsert_score(existing_source.lead_id, score)
                return LeadIngestResult(
                    lead_id=existing_source.lead_id,
                    created=False,
                    match_reason="exact_source_identity",
                    score=score,
                )

        rows = (
            await self.session.execute(select(Lead).where(Lead.campaign_id == campaign_id))
        ).scalars().all()
        candidates = [
            ExistingLead(
                id=row.id,
                name=row.name,
                normalized_name=row.normalized_name,
                category=row.category,
                city=row.city,
                address=row.address,
                phone=row.phone,
                canonical_domain=row.canonical_domain,
                maps_url=row.maps_url,
                rating=row.rating,
                review_count=row.review_count,
            )
            for row in rows
        ]
        match = match_existing_lead(normalized, candidates)
        if match is not None:
            lead_id = match.lead_id
            created = False
            reason = match.reason
        else:
            lead = Lead(
                campaign_id=campaign_id,
                state=LeadState.DISCOVERED.value,
                **normalized.model_dump(),
            )
            self.session.add(lead)
            await self.session.flush()
            lead_id = lead.id
            created = True
            reason = "new_lead"

        existing_source = None
        if source.source_external_id:
            existing_source = (
                await self.session.execute(
                    select(LeadSource).where(
                        LeadSource.source == source.source,
                        LeadSource.source_external_id == source.source_external_id,
                    )
                )
            ).scalar_one_or_none()
        if existing_source is None:
            self.session.add(
                LeadSource(
                    lead_id=lead_id,
                    source=source.source,
                    source_external_id=source.source_external_id,
                    source_query=source.source_query,
                    source_url=source.source_url,
                    raw_json=json.dumps(source.raw, ensure_ascii=False, sort_keys=True) if source.raw is not None else None,
                )
            )
        else:
            self._refresh_source(existing_source, source)
        await self._upsert_score(lead_id, score)
        await self.session.flush()
        return LeadIngestResult(lead_id=lead_id, created=created, match_reason=reason, score=score)

    async def _upsert_score(self, lead_id: int, score: object) -> None:
        record = (
            await self.session.execute(
                select(LeadScoreModel).where(
                    LeadScoreModel.lead_id == lead_id,
                    LeadScoreModel.score_type == "qualification",
                ).order_by(LeadScoreModel.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        payload = json.dumps(score.components, sort_keys=True)
        if record is None:
            self.session.add(LeadScoreModel(
                lead_id=lead_id, score_type="qualification", total=score.total, components_json=payload
            ))
        else:
            record.total = score.total
            record.components_json = payload

    @staticmethod
    def _refresh_source(record: LeadSource, source: LeadSourceInput) -> None:
        if source.source_query is not None:
            record.source_query = source.source_query
        if source.source_url is not None:
            record.source_url = source.source_url
        if source.raw is not None:
            record.raw_json = json.dumps(source.raw, ensure_ascii=False, sort_keys=True)
