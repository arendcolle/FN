"""The local web app: the factory, host and origin checks, security headers, error handler and fn-serve."""
import logging
import sys
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fn import config, net
from fn.config import Settings
from fn.contracts import HttpClient
from fn.llm import StructuredLLM, from_settings
from fn.steps import redact, setup_logging
from fn.store import Store
from fn.web import debug, staff
from fn.web.parts import error_page
from fn.worker import Worker, new_id, now

log = logging.getLogger("fn.web")

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; connect-src 'self' https://tiles.openfreemap.org; "
        "worker-src blob:; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
}


def refusal(request: Request) -> Response | None:
    """A 403 for a state-changing request from another site or origin, else None.

    Origin must be the app's own. A browser sends Origin: null from the app's own forms because of
    Referrer-Policy: no-referrer, so null passes only when Sec-Fetch-Site says same-origin.
    """
    if request.method in SAFE_METHODS:
        return None
    origin, site = request.headers.get("origin"), request.headers.get("sec-fetch-site")
    allowed = {None, f"http://{request.headers.get('host')}"} | ({"null"} if site == "same-origin" else set())
    if origin not in allowed or site not in (None, "same-origin", "none"):
        return HTMLResponse(error_page("Refused", "This request comes from another site."), 403)
    return None


def create_app(settings: Settings, llm: StructuredLLM | None, http: HttpClient | None = None) -> FastAPI:
    """The app for settings, with a store, a worker and the guard middleware; lifespan migrates and sweeps."""
    store = Store(settings.db_path)
    worker = Worker(store, settings, llm, http)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.migrate()
        worker.sweep()
        yield
        worker.shutdown()
        store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.worker = store, worker
    app.include_router(staff.router)
    app.include_router(debug.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
        return HTMLResponse(error_page(str(exc.status_code), str(exc.detail)), exc.status_code)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = refusal(request)
        if response is None:
            try:
                response = await call_next(request)
            except Exception:  # noqa: BLE001 the guard stores every unhandled request error
                error = redact(traceback.format_exc(), settings.secrets())
                route = f"{request.method} {request.url.path}"
                store.add_request_error(new_id(), route, error, now())
                log.error("request %s failed\n%s", route, error)
                response = HTMLResponse(error_page("Server error", error), 500)
        response.headers.update(SECURITY_HEADERS)
        return response

    return app


def serve() -> None:
    """Run the app on settings.host and settings.port; exits when the host is not loopback."""
    settings = config.from_env()
    if settings.host not in ("127.0.0.1", "::1"):
        sys.exit(f"fn-serve binds 127.0.0.1 or ::1 only, not {settings.host!r}")
    setup_logging(settings)
    uvicorn.run(create_app(settings, from_settings(settings), net.Client(settings)), host=settings.host, port=settings.port, log_config=None)
