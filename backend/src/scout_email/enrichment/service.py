from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.db.models import Contact, SocialProfile, Website
from scout_email.enrichment.contacts import extract_public_contacts
from scout_email.enrichment.social import discover_social_profiles
from scout_email.enrichment.website import WebsiteVerification


class PublicPage(BaseModel):
    url: str
    html: str
    verified: bool = False


class EnrichmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def persist(
        self,
        lead_id: int,
        verification: WebsiteVerification,
        pages: list[PublicPage],
    ) -> None:
        website = await self.session.scalar(
            select(Website).where(Website.lead_id == lead_id)
        )
        if website is None:
            website = Website(
                lead_id=lead_id,
                state=verification.state.value,
            )
            self.session.add(website)

        website.url = verification.requested_url
        website.canonical_domain = verification.canonical_domain
        website.state = verification.state.value
        website.final_url = verification.final_url
        website.http_status = verification.http_status
        website.verified_at = datetime.now(timezone.utc)

        for page in pages:
            if not page.verified:
                continue

            for candidate in extract_public_contacts(page.html, page.url):
                contact = await self.session.scalar(
                    select(Contact).where(
                        Contact.lead_id == lead_id,
                        Contact.normalized_email == candidate.email,
                    )
                )
                if contact is None:
                    contact = Contact(
                        lead_id=lead_id,
                        email=candidate.email,
                        normalized_email=candidate.email,
                        contact_type=candidate.contact_type,
                        state="VERIFIED",
                        source_url=candidate.source_url,
                        confidence=candidate.confidence,
                    )
                    self.session.add(contact)
                else:
                    contact.email = candidate.email
                    contact.contact_type = candidate.contact_type
                    contact.state = "VERIFIED"
                    contact.source_url = candidate.source_url
                    contact.confidence = candidate.confidence

            for candidate in discover_social_profiles(page.html, page.url):
                social = await self.session.scalar(
                    select(SocialProfile).where(
                        SocialProfile.lead_id == lead_id,
                        SocialProfile.network == candidate.network,
                        SocialProfile.url == candidate.url,
                    )
                )
                if social is None:
                    social = SocialProfile(
                        lead_id=lead_id,
                        network=candidate.network,
                        url=candidate.url,
                        source_url=candidate.source_url,
                        verified=candidate.verified,
                    )
                    self.session.add(social)
                else:
                    social.source_url = candidate.source_url
                    social.verified = candidate.verified

        await self.session.commit()
