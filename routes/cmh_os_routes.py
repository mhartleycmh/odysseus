"""Public configuration for the Agentic OS page (/cmh/os).

Only non-secret values read from the environment: the page must never receive
credentials. Any signed-in user may read it; the CMH data APIs stay admin-only.
"""

import os
import posixpath
import re

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import get_current_user

_TRUE = {"1", "true", "yes", "on"}
_REPEATED_SLASH = re.compile(r"/{2,}")

#: Route prefix of the Agentic OS assets. They live under ``/static`` for the
#: no-build ES-module loader, but they are the page itself, not a shared asset,
#: so they follow the page's gate rather than the ``/static`` auth exemption.
OS_ASSET_ROUTE = "/static/cmh-os"


def ui_enabled() -> bool:
    """CMH_OS_UI_ENABLED (default true) turns the /cmh/os page on or off."""
    return os.environ.get("CMH_OS_UI_ENABLED", "true").strip().lower() in _TRUE


def is_os_asset_path(path: str) -> bool:
    """True when a request route resolves to ``OS_ASSET_ROUTE`` or below it.

    Three normalizations, each one measured rather than assumed:

    * **case** — NTFS serves ``/static/CMH-OS/index.html`` out of the same
      folder as the lowercase spelling;
    * **separator** — Starlette's ``StaticFiles`` normalizes its relative path
      with ``os.path.normpath``, which backslashes it on Windows;
    * **dot segments** — ``StaticFiles`` collapses ``.`` and ``..`` before it
      opens the file, so ``/static/./cmh-os/index.html`` and
      ``/static/foo/../cmh-os/index.html`` reach the same bytes. Browsers and
      httpx collapse them client-side, but a raw HTTP client does not: both
      spellings served the page with no session until this was normalized.

    ``..`` that climbs back OUT of the folder (``/static/cmh-os/../x.css``)
    correctly stops being an OS asset: it resolves to ordinary shared static.
    """
    route = _REPEATED_SLASH.sub("/", str(path or "").replace("\\", "/").strip().lower())
    if not route.startswith("/"):
        route = "/" + route
    # normpath collapses interior slashes but keeps a LEADING "//" by POSIX
    # rule, so the sub above is what makes "//static//cmh-os//x" resolve. No
    # caller can currently produce that spelling — the mount would not match
    # it — so this is the predicate being correct on its own terms, not a
    # live path.
    route = posixpath.normpath(route).rstrip("/") or "/"
    return route == OS_ASSET_ROUTE or route.startswith(OS_ASSET_ROUTE + "/")


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
