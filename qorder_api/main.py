"""FastAPI application entrypoint.

Creates the app instance and exposes a ``GET /health`` endpoint. Routers, the
WebSocket gateway and the scheduler are mounted here as later tasks land.
"""

from __future__ import annotations

from fastapi import FastAPI

from qorder_api.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe used by orchestrators and load balancers."""

    return {"status": "ok"}
