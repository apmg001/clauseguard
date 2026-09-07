"""Port + resilience policy for LLM providers.

Defines the synchronous :class:`LLMProvider` base every concrete adapter
implements, plus the shared fault-tolerance policy (per-request timeout and
bounded retries with exponential backoff for *transient* failures). Concrete
adapters implement only :meth:`LLMProvider._raw_complete`; the public
:meth:`LLMProvider.complete` wraps it so every provider behaves consistently.

The transient/permanent split (see :mod:`clauseguard.exceptions`) tells the
retry loop what is worth re-attempting: timeouts, connection errors and 429/5xx
are transient; auth and malformed-request errors are permanent.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass

from clauseguard.exceptions import LLMProviderError, TransientLLMError
from clauseguard.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CompletionRequest:
    """A provider-neutral chat-completion request.

    Attributes:
        system: System / instruction prompt.
        user: User message content.
        temperature: Sampling temperature. Extraction wants determinism (0.0).
        max_tokens: Upper bound on generated tokens.
    """

    system: str
    user: str
    temperature: float = 0.0
    max_tokens: int = 1024


class LLMProvider(abc.ABC):
    """Abstract base for synchronous chat-completion providers.

    Args:
        model: Model identifier passed verbatim to the backend.
        timeout_seconds: Per-request timeout budget.
        max_retries: Maximum retry attempts for transient failures.
        retry_backoff_base: Base seconds for exponential backoff between retries
            (attempt ``n`` sleeps ``base * 2**n``). Set to 0 in tests.
    """

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        retry_backoff_base: float = 0.5,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._retry_backoff_base = retry_backoff_base

    def complete(self, request: CompletionRequest) -> str:
        """Run a completion with timeout and retry protection.

        Args:
            request: The provider-neutral completion request.

        Returns:
            The model's text response.

        Raises:
            TransientLLMError: If all retries were exhausted on transient errors.
            PermanentLLMError: On non-retryable failures (auth, bad request).
        """
        last_error: LLMProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._raw_complete(request)
            except TransientLLMError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                backoff = self._retry_backoff_base * (2**attempt)
                logger.warning(
                    "LLM transient failure; retrying",
                    extra={"provider": type(self).__name__,
                           "attempt": attempt + 1, "backoff_s": backoff},
                )
                if backoff:
                    time.sleep(backoff)
        assert last_error is not None
        raise last_error

    @abc.abstractmethod
    def _raw_complete(self, request: CompletionRequest) -> str:
        """Perform a single, unguarded completion call.

        Implementations MUST translate backend failures into the shared taxonomy:
        raise :class:`TransientLLMError` for retryable failures and
        :class:`PermanentLLMError` for everything else.

        Args:
            request: The completion request.

        Returns:
            The raw text response.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """Release any underlying network resources (e.g. an HTTP client)."""
        raise NotImplementedError
