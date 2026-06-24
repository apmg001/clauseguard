"""Application configuration.

Settings are typed and loaded from environment variables (and an optional
``.env`` file) via ``pydantic-settings``. Nothing in the codebase should read
``os.environ`` directly or hardcode tunables (thresholds, model names, paths) —
everything configurable lives here so it can be changed per environment without
touching code.

Access the singleton via :func:`get_settings`, which is cached so the
environment is parsed once per process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Attributes:
        environment: Deployment environment name.
        log_level: Root logging level.
        log_json: Emit structured JSON logs when True, human-readable otherwise.
        match_accept_threshold: Minimum match score to accept an invoice↔contract
            pairing without human review.
        review_confidence_threshold: Discrepancies scoring below this confidence
            are routed to human review rather than auto-reported.
        arithmetic_tolerance: Absolute currency tolerance when checking that
            quantity × unit_rate equals the stated line total (guards against
            rounding noise, not real errors).
    """

    model_config = SettingsConfigDict(
        env_prefix="CLAUSEGUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "dev", "staging", "prod"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False

    # Tunables — deliberately surfaced as config, not magic numbers in code.
    match_accept_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    review_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    arithmetic_tolerance: float = Field(default=0.01, ge=0.0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, process-wide settings instance.

    Returns:
        The parsed :class:`Settings`.
    """
    return Settings()
