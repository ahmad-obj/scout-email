from pathlib import Path

import pytest

from scout_email.common.enums import ClaimClass
from scout_email.evidence.provenance import (
    UnverifiedClaimError,
    UnsupportedClaimError,
    assert_claim_supported,
)
from scout_email.evidence.service import UnsafeArtifactPathError, build_screenshot_path


def test_unverified_claim_is_never_sendable():
    with pytest.raises(UnverifiedClaimError):
        assert_claim_supported([], ClaimClass.UNVERIFIED)


def test_sendable_claim_requires_at_least_one_evidence_id():
    with pytest.raises(UnsupportedClaimError):
        assert_claim_supported([], ClaimClass.OBSERVED_FACT)

    with pytest.raises(UnsupportedClaimError):
        assert_claim_supported([], ClaimClass.REASONABLE_INFERENCE)


def test_sendable_claim_accepts_stable_positive_evidence_ids():
    assert_claim_supported([12, 19], ClaimClass.OBSERVED_FACT)
    assert_claim_supported([21], ClaimClass.REASONABLE_INFERENCE)


def test_screenshot_path_is_campaign_and_lead_scoped(tmp_path):
    path = build_screenshot_path(
        tmp_path,
        campaign_id=7,
        lead_id=31,
        viewport="desktop",
    )

    assert path == tmp_path / "campaigns" / "7" / "leads" / "31" / "screenshots" / "homepage-desktop.png"
    assert path.is_relative_to(tmp_path)


def test_screenshot_path_rejects_untrusted_viewport_or_escape(tmp_path):
    with pytest.raises(UnsafeArtifactPathError):
        build_screenshot_path(
            tmp_path,
            campaign_id=7,
            lead_id=31,
            viewport="../../outside",
        )

    with pytest.raises(UnsafeArtifactPathError):
        build_screenshot_path(
            Path("/tmp") / ".." / "tmp",
            campaign_id=-1,
            lead_id=31,
            viewport="mobile",
        )
