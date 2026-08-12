"""FastAPI application entrypoint.

Creates the app instance and exposes a ``GET /health`` endpoint. Routers, the
WebSocket gateway and the scheduler are mounted here as later tasks land.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from qorder_api.api.admin_menu_router import router as admin_menu_router
from qorder_api.api.admin_router import router as admin_router
from qorder_api.api.admin_table_router import router as admin_table_router
from qorder_api.api.auth_router import router as auth_router
from qorder_api.api.customer_router import router as customer_router
from qorder_api.api.kitchen_router import router as kitchen_router
from qorder_api.api.staff_table_router import router as staff_table_router
from qorder_api.config import get_settings
from qorder_api.scheduler import shutdown_scheduler, start_scheduler
from qorder_api.ws import router as ws_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: start/stop scheduler."""
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# --- Routers ---
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_menu_router)
app.include_router(admin_table_router)
app.include_router(customer_router)
app.include_router(kitchen_router)
app.include_router(staff_table_router)
app.include_router(ws_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe used by orchestrators and load balancers."""

    return {"status": "ok"}
