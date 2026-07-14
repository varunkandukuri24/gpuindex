"""FastAPI public index site and JSON API."""

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from api.pages import router as pages_router
from api.rate_limit import RateLimitMiddleware
from api.routes.v1 import router as v1_router
from build_info import GIT_SHA
from config import settings

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Proxies/CDNs must not pin API JSON or HTML for hours; static assets are versioned.
API_CACHE_CONTROL = "public, max-age=60, must-revalidate"
PAGE_CACHE_CONTROL = "public, max-age=120, must-revalidate"
STATIC_CACHE_CONTROL = "public, max-age=3600"


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path
        if "cache-control" in response.headers:
            return response
        if path.startswith("/api/") or path == "/health":
            response.headers["Cache-Control"] = API_CACHE_CONTROL
        elif path.startswith("/static/"):
            response.headers["Cache-Control"] = STATIC_CACHE_CONTROL
        elif path in ("/robots.txt", "/sitemap.xml"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = PAGE_CACHE_CONTROL
        return response


app = FastAPI(title=settings.site_title, version="0.3.0")
app.add_middleware(CacheControlMiddleware)
app.add_middleware(RateLimitMiddleware)
app.include_router(v1_router)
app.include_router(pages_router)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "code_version": GIT_SHA}
