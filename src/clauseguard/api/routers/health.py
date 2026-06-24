"""Health-check router."""

from __future__ import annotations

from fastapi import APIRouter

from clauseguard import __version__
from clauseguard.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return basic liveness information.

    Returns:
        Service name, version, and environment.
    """
    return {
        "status": "ok",
        "version": __version__,
        "environment": get_settings().environment,
    }
