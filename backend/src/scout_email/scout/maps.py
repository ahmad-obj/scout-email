from __future__ import annotations

from hashlib import sha256

from scout_email.browser.schemas import BrowserMapLead
from scout_email.leads.schemas import LeadSourceInput, RawLead


def source_identity(lead: BrowserMapLead) -> str:
    if lead.source_external_id:
        return f"external:{lead.source_external_id}"
    if lead.maps_url:
        return f"maps:{lead.maps_url}"
    stable = "|".join([lead.name.casefold(), lead.phone or "", lead.website or ""])
    return f"fallback:{sha256(stable.encode()).hexdigest()}"


def browser_lead_to_inputs(
    lead: BrowserMapLead,
    *,
    query: str,
    location: str,
) -> tuple[RawLead, LeadSourceInput]:
    raw = RawLead(
        name=lead.name,
        category=lead.category,
        city=location,
        address=lead.address,
        phone=lead.phone,
        website=lead.website,
        maps_url=lead.maps_url,
        rating=lead.rating,
        review_count=lead.review_count,
    )
    source = LeadSourceInput(
        source="google_maps_browser",
        source_external_id=source_identity(lead),
        source_query=query,
        source_url=lead.maps_url,
        raw=lead.model_dump(mode="json"),
    )
    return raw, source
