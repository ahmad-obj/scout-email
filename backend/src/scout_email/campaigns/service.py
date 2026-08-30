from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.campaigns.models import CampaignPolicy
from scout_email.common.errors import NotFoundError
from scout_email.db.models import Campaign, CampaignSearch
from scout_email.campaigns.schemas import CampaignCreate, CampaignResponse, FollowUpPolicy, QualificationPolicy, SendingPolicy


class CampaignService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: CampaignCreate) -> CampaignResponse:
        campaign = Campaign(
            name=payload.name,
            target_leads=payload.target_leads,
            max_per_day=payload.sending.max_per_day,
            human_approval_required=payload.sending.human_approval,
            status="ACTIVE",
        )
        self.session.add(campaign)
        await self.session.flush()
        self.session.add(
            CampaignPolicy(
                campaign_id=campaign.id,
                qualification_json=payload.qualification.model_dump_json(),
                follow_up_json=payload.follow_up.model_dump_json(),
            )
        )

        for search_term in payload.searches:
            for location in payload.locations:
                self.session.add(
                    CampaignSearch(
                        campaign_id=campaign.id,
                        search_term=search_term,
                        location=location,
                    )
                )

        await self.session.commit()
        return await self.get(campaign.id)

    async def get(self, campaign_id: int) -> CampaignResponse:
        campaign = await self.session.get(Campaign, campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign {campaign_id} not found")

        policy = await self.session.get(CampaignPolicy, campaign_id)
        if policy is None:
            raise RuntimeError(f"Campaign {campaign_id} has no persisted policy")

        rows = (
            await self.session.execute(
                select(CampaignSearch)
                .where(CampaignSearch.campaign_id == campaign_id)
                .order_by(CampaignSearch.id)
            )
        ).scalars().all()

        searches = list(dict.fromkeys(row.search_term for row in rows))
        locations = list(dict.fromkeys(row.location for row in rows))
        return CampaignResponse(
            id=campaign.id,
            name=campaign.name,
            searches=searches,
            locations=locations,
            target_leads=campaign.target_leads or 1,
            qualification=QualificationPolicy.model_validate_json(policy.qualification_json),
            sending=SendingPolicy(
                max_per_day=campaign.max_per_day,
                human_approval=campaign.human_approval_required,
            ),
            follow_up=FollowUpPolicy.model_validate_json(policy.follow_up_json),
            status=campaign.status,
        )

    async def set_status(self, campaign_id: int, status: str) -> CampaignResponse:
        campaign = await self.session.get(Campaign, campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign {campaign_id} not found")
        campaign.status = status
        await self.session.commit()
        return await self.get(campaign_id)

    async def pause(self, campaign_id: int) -> CampaignResponse:
        return await self.set_status(campaign_id, "PAUSED")

    async def resume(self, campaign_id: int) -> CampaignResponse:
        return await self.set_status(campaign_id, "ACTIVE")

    async def require_active(self, campaign_id: int) -> Campaign:
        campaign = await self.session.get(Campaign, campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign {campaign_id} not found")
        if campaign.status != "ACTIVE":
            raise RuntimeError(f"Campaign {campaign_id} is not active")
        return campaign
