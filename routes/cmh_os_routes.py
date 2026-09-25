"""Public configuration for the Agentic OS page (/cmh/os).

Only non-secret values read from the environment: the page must never receive
credentials. Any signed-in user may read it; the CMH data APIs stay admin-only.
"""

import os

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import get_current_user

_TRUE = {"1", "true", "yes", "on"}


def ui_enabled() -> bool:
    """CMH_OS_UI_ENABLED (default true) turns the /cmh/os page on or off."""
    return os.environ.get("CMH_OS_UI_ENABLED", "true").strip().lower() in _TRUE


def default_mode() -> str:
    """CMH_OS_DEFAULT_MODE: "demo" forces demo data for everyone; anything else is "auto"."""
    return "demo" if os.environ.get("CMH_OS_DEFAULT_MODE", "auto").strip().lower() == "demo" else "auto"


def setup_cmh_os_routes() -> APIRouter:
    router = APIRouter(prefix="/api/cmh/os", tags=["cmh-os"])

    @router.get("/config")
    def config(request: Request):
        if not get_current_user(request):
            raise HTTPException(401, "Not authenticated")
        return {"ui_enabled": ui_enabled(), "default_mode": default_mode()}

    return router
