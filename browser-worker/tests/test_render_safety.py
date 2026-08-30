import pytest

from browser_worker.render import UnsafeTargetError, resolve_screenshot_path, validate_public_url


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
