"""LLM provider adapters (BYOK).

A thin, synchronous provider abstraction so the rest of ClauseGuard depends on
one interface (:class:`~clauseguard.providers.base.LLMProvider`) regardless of
whether tokens come from a local Ollama server or a hosted OpenAI-compatible
API. Synchronous to match the rest of the codebase (ports and services are
plain ``def``, not ``async def``).
"""
