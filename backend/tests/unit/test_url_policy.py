import socket

import pytest

from scout_email.common.url_policy import UnsafeURLError, validate_public_http_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.10/",
        "http://172.16.0.10/",
        "http://192.168.1.10/",
    ],
)
def test_rejects_non_public_or_non_http_targets(url):
    with pytest.raises(UnsafeURLError):
        validate_public_http_url(url)


def test_accepts_public_https_host_when_all_dns_answers_are_public(monkeypatch):
    def fake_getaddrinfo(host, port, *, type):
        assert host == "example.com"
        assert type == socket.SOCK_STREAM
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    safe = validate_public_http_url("https://example.com/contact")
    assert safe.hostname == "example.com"
    assert str(safe.addresses[0]) == "93.184.216.34"


def test_rejects_hostname_if_any_dns_answer_is_private(monkeypatch):
    def fake_getaddrinfo(host, port, *, type):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("https://example.com/")


def test_rejects_embedded_credentials():
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("https://user:pass@example.com/")
