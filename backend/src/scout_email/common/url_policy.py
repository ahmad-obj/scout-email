from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeURLError(ValueError):
    """Raised when a URL is not safe for public-web fetching."""


@dataclass(frozen=True, slots=True)
class SafeURL:
    url: str
    scheme: str
    hostname: str
    port: int
    addresses: tuple[IPAddress, ...]


def _assert_public_ip(address: IPAddress) -> None:
    if not address.is_global:
        raise UnsafeURLError(f"Host resolved to non-public address: {address}")


def _parse_ip_literal(hostname: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def resolve_and_validate_host(hostname: str, *, port: int) -> tuple[IPAddress, ...]:
    hostname = hostname.rstrip(".").casefold()
    if not hostname:
        raise UnsafeURLError("URL hostname is required")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeURLError("localhost destinations are forbidden")

    literal = _parse_ip_literal(hostname)
    if literal is not None:
        _assert_public_ip(literal)
        return (literal,)

    try:
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as error:
        raise UnsafeURLError(f"Hostname could not be safely resolved: {hostname}") from error

    resolved: list[IPAddress] = []
    seen: set[IPAddress] = set()
    for answer in answers:
        sockaddr = answer[4]
        if not sockaddr:
            continue
        raw_address = sockaddr[0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as error:
            raise UnsafeURLError(f"Resolver returned invalid IP address: {raw_address}") from error
        _assert_public_ip(address)
        if address not in seen:
            seen.add(address)
            resolved.append(address)

    if not resolved:
        raise UnsafeURLError(f"Hostname produced no usable public addresses: {hostname}")
    return tuple(resolved)


def _parse_url(url: str) -> SplitResult:
    try:
        parsed = urlsplit(url.strip())
    except ValueError as error:
        raise UnsafeURLError("Malformed URL") from error

    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError("Only http and https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("Embedded URL credentials are forbidden")
    if not parsed.hostname:
        raise UnsafeURLError("URL hostname is required")
    try:
        _ = parsed.port
    except ValueError as error:
        raise UnsafeURLError("Invalid URL port") from error
    return parsed


def validate_public_http_url(url: str) -> SafeURL:
    """Validate one outbound public-web URL before a request is attempted.

    Every DNS answer must be globally routable. Call this function again for every
    redirect target; validating the initial URL never authorizes later locations.
    """
    parsed = _parse_url(url)
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname.rstrip(".").casefold()  # type: ignore[union-attr]
    port = parsed.port or (443 if scheme == "https" else 80)
    addresses = resolve_and_validate_host(hostname, port=port)
    return SafeURL(
        url=url.strip(),
        scheme=scheme,
        hostname=hostname,
        port=port,
        addresses=addresses,
    )
