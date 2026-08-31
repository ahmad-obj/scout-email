import json
import logging
from typing import Any

_EVENT_LOGGER = logging.getLogger("scout_email.events")
_SENSITIVE_KEYS = {
    "authorization",
    "proxy-authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "oauth_token",
    "token",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "cookie",
    "set-cookie",
    "credentials",
}


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized in {item.replace("-", "_") for item in _SENSITIVE_KEYS}:
        return True
    return normalized.endswith("_token") or normalized.endswith("_secret") or normalized.endswith("_password")


def _redact(value: Any, *, key: object | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, key=item_key) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_redact(item) for item in value]
    return value


def configure_logging(level: int = logging.INFO) -> None:
    """Configure concise application logging without secret-bearing payloads."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def log_operational_event(
    event_type: str,
    *,
    correlation_id: str | None = None,
    campaign_id: int | None = None,
    lead_id: int | None = None,
    job_id: int | None = None,
    outcome: str | None = None,
    duration_ms: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    event: dict[str, Any] = {"event_type": event_type}
    optional = {
        "correlation_id": correlation_id,
        "campaign_id": campaign_id,
        "lead_id": lead_id,
        "job_id": job_id,
        "outcome": outcome,
        "duration_ms": duration_ms,
    }
    event.update({key: value for key, value in optional.items() if value is not None})
    if details:
        event["details"] = _redact(details)
    _EVENT_LOGGER.info(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str))
