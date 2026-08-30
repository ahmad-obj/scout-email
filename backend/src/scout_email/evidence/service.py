from __future__ import annotations

from pathlib import Path


class UnsafeArtifactPathError(ValueError):
    """Raised when an artifact path cannot be proven to stay inside its data root."""


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
