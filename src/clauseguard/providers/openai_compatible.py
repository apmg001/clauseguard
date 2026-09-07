"""Adapter: OpenAI-compatible chat-completions provider.

One adapter serves both ends of the BYOK spectrum because they share the
``POST {base_url}/chat/completions`` contract:

* **Ollama (local, offline)** — ``http://localhost:11434/v1``, no API key. The
  privacy-first default: no data leaves the machine.
* **Hosted (Groq, OpenAI, OpenRouter, DeepSeek)** — their ``/v1`` base URL plus
  a bearer key, for speed/throughput.

Only ``base_url``, ``model`` and ``api_key`` differ — switching is configuration.
``httpx`` is imported lazily so the package (and the tests, which use a fake
provider) do not require it unless this concrete provider is actually used.
"""

from __future__ import annotations

from clauseguard.exceptions import PermanentLLMError, TransientLLMError
from clauseguard.logging_config import get_logger
from clauseguard.providers.base import CompletionRequest, LLMProvider

logger = get_logger(__name__)

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class OpenAICompatibleProvider(LLMProvider):
    """Synchronous chat-completions provider speaking the OpenAI wire format.

    Args:
        model: Model name sent to the backend (e.g. ``qwen2.5:3b`` for Ollama).
        base_url: API base URL, e.g. ``http://localhost:11434/v1``.
        api_key: Bearer token. Empty is valid for a keyless local server.
        timeout_seconds: Per-request timeout.
        max_retries: Retry attempts for transient failures.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        super().__init__(
            model=model, timeout_seconds=timeout_seconds, max_retries=max_retries
        )
        try:
            import httpx  # noqa: PLC0415 - lazy: only needed for the real provider
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise PermanentLLMError(
                "OpenAICompatibleProvider needs 'httpx'; install the 'llm' extra"
            ) from exc
        self._httpx = httpx
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
        )

    def _raw_complete(self, request: CompletionRequest) -> str:
        """Issue one chat-completion call and return the assistant text.

        Raises:
            TransientLLMError: On timeouts, connection errors, retryable status.
            PermanentLLMError: On non-retryable status or a malformed body.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        try:
            response = self._client.post("/chat/completions", json=payload)
        except self._httpx.TimeoutException as exc:
            raise TransientLLMError(
                f"LLM request timed out after {self.timeout_seconds}s"
            ) from exc
        except self._httpx.HTTPError as exc:
            raise TransientLLMError(f"Network error contacting LLM: {exc}") from exc

        self._raise_for_status(response)
        return self._extract_text(response)

    def _raise_for_status(self, response) -> None:
        """Map an HTTP status onto the transient/permanent taxonomy."""
        if response.is_success:
            return
        status = response.status_code
        snippet = response.text[:300]
        if status in _RETRYABLE_STATUS:
            raise TransientLLMError(f"Retryable LLM status {status}: {snippet}")
        raise PermanentLLMError(f"Non-retryable LLM status {status}: {snippet}")

    @staticmethod
    def _extract_text(response) -> str:
        """Pull the assistant message content out of the JSON envelope."""
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise PermanentLLMError(
                f"Malformed LLM response: {response.text[:300]}"
            ) from exc
        if not isinstance(content, str):
            raise PermanentLLMError("LLM returned non-string content")
        return content

    def close(self) -> None:
        """Close the underlying HTTP client and its connection pool."""
        self._client.close()
