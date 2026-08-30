import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure concise application logging without secret-bearing payloads."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
