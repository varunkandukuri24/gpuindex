"""FastAPI public index site and JSON API."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.pages import router as pages_router
from api.rate_limit import RateLimitMiddleware
from api.routes.v1 import router as v1_router
from config import settings

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title=settings.site_title, version="0.3.0")
app.add_middleware(RateLimitMiddleware)
app.include_router(v1_router)
app.include_router(pages_router)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
