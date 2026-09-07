"""Provider factory.

The single place that turns declarative :class:`~clauseguard.config.Settings`
into a live :class:`~clauseguard.providers.base.LLMProvider`. Centralising
construction keeps the rest of the code from importing concrete provider
classes, so adding a backend is a one-line change here (open/closed).
"""

from __future__ import annotations

from clauseguard.config import Settings
from clauseguard.exceptions import ConfigurationError
from clauseguard.logging_config import get_logger
from clauseguard.providers.base import LLMProvider

logger = get_logger(__name__)


def build_provider(settings: Settings) -> LLMProvider:
    """Instantiate the LLM provider described by ``settings``.

    Args:
        settings: Application settings carrying the provider configuration.

    Returns:
        A ready-to-use :class:`LLMProvider`.

    Raises:
        ConfigurationError: If ``settings.llm_provider_kind`` is unknown.
    """
    kind = settings.llm_provider_kind
    if kind == "openai_compatible":
        from clauseguard.providers.openai_compatible import OpenAICompatibleProvider

        logger.info(
            "Building LLM provider",
            extra={"kind": kind, "model": settings.llm_model,
                   "base_url": settings.llm_base_url},
        )
        return OpenAICompatibleProvider(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    raise ConfigurationError(f"Unknown llm_provider_kind: {kind!r}")
