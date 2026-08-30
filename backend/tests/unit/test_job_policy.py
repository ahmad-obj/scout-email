from scout_email.jobs.service import retry_delay_seconds, sanitize_error_message


def test_retry_delay_is_bounded_exponential():
    assert retry_delay_seconds(1) == 30
    assert retry_delay_seconds(2) == 60
    assert retry_delay_seconds(3) == 120
    assert retry_delay_seconds(20) == 3600


def test_error_message_is_single_line_and_bounded():
    value = sanitize_error_message("boom\nsecret detail" + "x" * 2000)
    assert "\n" not in value
    assert len(value) <= 1000
    assert value.startswith("boom secret detail")
