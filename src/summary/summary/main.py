"""Application."""

from pathlib import Path

import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from summary.api import health
from summary.api.main import api_router_v2
from summary.core.config import get_settings

settings = get_settings()


if settings.sentry_dsn and settings.sentry_is_enabled:
    sentry_sdk.init(dsn=settings.sentry_dsn, enable_tracing=True)

app = FastAPI(
    title=settings.app_name,
)

app.include_router(api_router_v2, prefix=settings.app_api_v2_str)
app.include_router(health.router)


@app.get("/memory-admin", include_in_schema=False, response_class=HTMLResponse)
def memory_admin():
    """Serve a data-free admin shell; all data operations require tenant auth."""
    if not get_settings().personal_memory_enabled:
        raise HTTPException(404)
    page = Path(__file__).with_name("memory_admin.html").read_text()
    return HTMLResponse(
        page.replace("__API_PREFIX__", settings.app_api_v2_str),
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
    )
