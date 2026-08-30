from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import ClaimClass
from scout_email.db.models import Contact, CrawlPage, Evidence, Lead, Screenshot, Website
from scout_email.evidence.schemas import EvidenceBundle, EvidenceRecord, ScreenshotRecord


class UnsafeArtifactPathError(ValueError):
    """Raised when an artifact path cannot be proven to stay inside its data root."""


class BrowserRenderer(Protocol):
    async def render(
        self,
        url: str,
        *,
        viewport: str = "desktop",
        screenshot_path: str | None = None,
    ): ...


def build_screenshot_path(
    data_root: Path,
    *,
    campaign_id: int,
    lead_id: int,
    viewport: str,
) -> Path:
    if not isinstance(campaign_id, int) or isinstance(campaign_id, bool) or campaign_id <= 0:
        raise UnsafeArtifactPathError("campaign_id must be a positive integer")
    if not isinstance(lead_id, int) or isinstance(lead_id, bool) or lead_id <= 0:
        raise UnsafeArtifactPathError("lead_id must be a positive integer")
    if viewport not in {"desktop", "mobile"}:
        raise UnsafeArtifactPathError("viewport must be desktop or mobile")

    root = Path(data_root).expanduser().resolve(strict=False)
    candidate = (
        root
        / "campaigns"
        / str(campaign_id)
        / "leads"
        / str(lead_id)
        / "screenshots"
        / f"homepage-{viewport}.png"
    ).resolve(strict=False)

    if not candidate.is_relative_to(root):
        raise UnsafeArtifactPathError("artifact path escapes configured data root")
    return candidate


class EvidenceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        data_root: Path,
        browser_client: BrowserRenderer,
    ) -> None:
        self.session = session
        self.data_root = Path(data_root).expanduser().resolve(strict=False)
        self.browser_client = browser_client

    async def build_bundle(
        self,
        *,
        campaign_id: int,
        lead_id: int,
        homepage_url: str,
    ) -> EvidenceBundle:
        lead = await self.session.scalar(
            select(Lead).where(Lead.id == lead_id, Lead.campaign_id == campaign_id)
        )
        if lead is None:
            raise ValueError("lead does not belong to campaign")

        website = await self.session.scalar(
            select(Website).where(Website.lead_id == lead_id).order_by(Website.id)
        )
        contacts = list(
            (
                await self.session.scalars(
                    select(Contact)
                    .where(Contact.lead_id == lead_id, Contact.state == "VERIFIED")
                    .order_by(Contact.id)
                )
            ).all()
        )
        pages = list(
            (
                await self.session.scalars(
                    select(CrawlPage).where(CrawlPage.lead_id == lead_id).order_by(CrawlPage.id)
                )
            ).all()
        )

        records: list[Evidence] = []
        if website is not None:
            source_url = website.final_url or website.url
            records.append(
                await self._evidence(
                    lead_id=lead_id,
                    kind="website_verification",
                    claim=f"Website state is {website.state}",
                    source_type="website_verification",
                    source_url=source_url,
                    artifact_path=None,
                    confidence=1.0,
                )
            )

        for contact in contacts:
            records.append(
                await self._evidence(
                    lead_id=lead_id,
                    kind="contact",
                    claim=f"Public business email {contact.email} was observed",
                    source_type="public_contact",
                    source_url=contact.source_url,
                    artifact_path=None,
                    confidence=contact.confidence,
                )
            )

        for page in pages:
            status_text = str(page.http_status) if page.http_status is not None else "unknown"
            records.append(
                await self._evidence(
                    lead_id=lead_id,
                    kind="crawl_page",
                    claim=f"Crawled page {page.url} returned HTTP {status_text} and stored deterministic page facts",
                    source_type="crawl_page",
                    source_url=page.url,
                    artifact_path=None,
                    confidence=1.0,
                )
            )

        screenshot_rows: list[Screenshot] = []
        for viewport in ("desktop", "mobile"):
            absolute_path = build_screenshot_path(
                self.data_root,
                campaign_id=campaign_id,
                lead_id=lead_id,
                viewport=viewport,
            )
            relative_path = absolute_path.relative_to(self.data_root)
            absolute_path.parent.mkdir(parents=True, exist_ok=True)

            await self.browser_client.render(
                homepage_url,
                viewport=viewport,
                screenshot_path=relative_path.as_posix(),
            )

            screenshot = await self.session.scalar(
                select(Screenshot).where(
                    Screenshot.lead_id == lead_id,
                    Screenshot.page_url == homepage_url,
                    Screenshot.viewport == viewport,
                )
            )
            if screenshot is None:
                screenshot = Screenshot(
                    lead_id=lead_id,
                    page_url=homepage_url,
                    viewport=viewport,
                    artifact_path=relative_path.as_posix(),
                )
                self.session.add(screenshot)
                await self.session.flush()
            else:
                screenshot.artifact_path = relative_path.as_posix()
            screenshot_rows.append(screenshot)

            records.append(
                await self._evidence(
                    lead_id=lead_id,
                    kind="screenshot",
                    claim=f"{viewport.capitalize()} homepage screenshot captured",
                    source_type="screenshot",
                    source_url=homepage_url,
                    artifact_path=relative_path.as_posix(),
                    confidence=1.0,
                )
            )

        await self.session.commit()

        records = sorted(records, key=lambda item: item.id)
        screenshot_rows = sorted(screenshot_rows, key=lambda item: item.id)
        return EvidenceBundle(
            lead_id=lead_id,
            evidence=[self._record(item) for item in records],
            screenshots=[self._screenshot_record(item) for item in screenshot_rows],
        )

    async def _evidence(
        self,
        *,
        lead_id: int,
        kind: str,
        claim: str,
        source_type: str,
        source_url: str | None,
        artifact_path: str | None,
        confidence: float,
    ) -> Evidence:
        row = await self.session.scalar(
            select(Evidence).where(
                Evidence.lead_id == lead_id,
                Evidence.kind == kind,
                Evidence.claim_class == ClaimClass.OBSERVED_FACT.value,
                Evidence.claim == claim,
                Evidence.source_type == source_type,
                Evidence.source_url == source_url,
                Evidence.artifact_path == artifact_path,
            )
        )
        if row is None:
            row = Evidence(
                lead_id=lead_id,
                kind=kind,
                claim_class=ClaimClass.OBSERVED_FACT.value,
                claim=claim,
                source_type=source_type,
                source_url=source_url,
                artifact_path=artifact_path,
                confidence=confidence,
            )
            self.session.add(row)
            await self.session.flush()
        else:
            row.confidence = confidence
        return row

    @staticmethod
    def _record(row: Evidence) -> EvidenceRecord:
        return EvidenceRecord(
            id=row.id,
            lead_id=row.lead_id,
            kind=row.kind,
            claim_class=ClaimClass(row.claim_class),
            claim=row.claim,
            source_type=row.source_type,
            source_url=row.source_url,
            artifact_path=row.artifact_path,
            confidence=row.confidence,
        )

    @staticmethod
    def _screenshot_record(row: Screenshot) -> ScreenshotRecord:
        return ScreenshotRecord(
            id=row.id,
            lead_id=row.lead_id,
            page_url=row.page_url,
            viewport=row.viewport,
            artifact_path=row.artifact_path,
        )
