"""FastAPI application factory.

Builds the ASGI app, configures logging, and registers routers. Use the factory
(rather than a module-level global) so tests can construct isolated app
instances and so configuration is explicit.
"""

from __future__ import annotations

from fastapi import FastAPI

from clauseguard import __version__
from clauseguard.api.routers import health, reconciliation
from clauseguard.logging_config import configure_logging, get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        The configured :class:`FastAPI` instance.
    """
    configure_logging()
    app = FastAPI(
        title="ClauseGuard",
        version=__version__,
        description="Audit-grade contract-to-invoice reconciliation.",
    )
    app.include_router(health.router)
    app.include_router(reconciliation.router)
    logger.info("Application initialised", extra={"version": __version__})
    return app


app = create_app()
