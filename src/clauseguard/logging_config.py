"""Logging configuration.

Provides a single :func:`configure_logging` entry point and a
:func:`get_logger` helper. The application logs through the standard library
``logging`` module — never ``print`` — so that output is leveled, structured,
and routable to whatever sink the deployment environment provides.

When ``log_json`` is enabled the formatter emits one JSON object per line,
which is what you want in production for log aggregation. Locally it falls back
to a readable console format.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from clauseguard.config import get_settings

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a log record to a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A JSON-encoded representation of the record.
        """
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Attach any structured extras passed via logger.*(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure root logging exactly once for the process.

    Idempotent: repeated calls are no-ops. Reads level and format from
    :class:`~clauseguard.config.Settings`.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    handler = logging.StreamHandler(stream=sys.stdout)

    if settings.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger, ensuring logging is configured first.

    Args:
        name: Logger name, conventionally ``__name__`` of the calling module.

    Returns:
        A configured :class:`logging.Logger`.
    """
    configure_logging()
    return logging.getLogger(name)
