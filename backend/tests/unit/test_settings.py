from scout_email.settings import Settings


def test_defaults_fail_safe(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert settings.send_mode == "mock"
    assert settings.maps_live_smoke_enabled is False
    assert settings.max_browser_concurrency <= 3
