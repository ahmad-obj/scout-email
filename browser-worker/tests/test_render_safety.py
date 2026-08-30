import pytest

from browser_worker.render import (
    UnsafeTargetError,
    resolve_screenshot_path,
    validate_public_url,
    viewport_dimensions,
)


def test_private_and_local_targets_are_rejected():
    for url in (
        "http://127.0.0.1/admin",
        "http://localhost:8000",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
    ):
        with pytest.raises(UnsafeTargetError):
            validate_public_url(url, resolve_dns=False)


def test_normal_public_hostname_is_allowed_without_dns_resolution():
    validate_public_url("https://example.com/about", resolve_dns=False)


def test_screenshot_path_cannot_escape_artifact_root(tmp_path):
    root = tmp_path / "artifacts"
    assert resolve_screenshot_path(root, "campaign/a.png") == root / "campaign/a.png"
    with pytest.raises(ValueError):
        resolve_screenshot_path(root, "../../outside.png")


def test_evidence_screenshot_viewports_are_fixed():
    assert viewport_dimensions("desktop") == {"width": 1440, "height": 900}
    assert viewport_dimensions("mobile") == {"width": 390, "height": 844}
