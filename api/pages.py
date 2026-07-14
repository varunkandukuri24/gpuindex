"""HTML page routes for the public index site."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from analysis.rollups import latest_snapshot_at
from analysis.trends import availability_level, build_index_trends, sparkline_svg
from api.deps import get_db
from api.routes.v1 import DATA_LICENSE
from config import settings
from db.models import GpuIndexSnapshot, GpuType
from jobs.status_data import collect_status

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

router = APIRouter(tags=["pages"])

PROBE_METHODS = [
    {"provider": "SkyPilot catalog (AWS/GCP/Azure/…)", "method": "none yet", "notes": "List prices only"},
    {"provider": "Vast.ai", "method": "marketplace_listing", "notes": "Rentable listings"},
    {"provider": "RunPod", "method": "none yet", "notes": "Prices only (secure + community)"},
    {"provider": "Lambda Cloud", "method": "capacity_api", "notes": "regions_with_capacity_available"},
]


@router.get("/", response_class=HTMLResponse)
def index_page(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    snapshot_at = latest_snapshot_at(session)
    rows = []
    if snapshot_at:
        trends = build_index_trends(session, snapshot_at)
        raw_rows = (
            session.query(GpuIndexSnapshot, GpuType)
            .join(GpuType, GpuIndexSnapshot.gpu_type_id == GpuType.id)
            .filter(GpuIndexSnapshot.snapshot_at == snapshot_at)
            .order_by(GpuIndexSnapshot.median_on_demand_per_gpu_hour_usd.asc().nulls_last())
            .all()
        )
        for snap, gpu in raw_rows:
            trend = trends.get(gpu.id, {})
            spark = trend.get("sparkline") or []
            avail_label, avail_segments = availability_level(
                snap.availability_indicator, snap.availability_rate_24h
            )
            rows.append(
                {
                    "snap": snap,
                    "gpu": gpu,
                    "sparkline_svg": sparkline_svg(spark),
                    "change_24h_pct": trend.get("change_24h_pct"),
                    "change_7d_pct": trend.get("change_7d_pct"),
                    "insufficient_data": trend.get("insufficient_data", False),
                    "avail_label": avail_label,
                    "avail_segments": avail_segments,
                }
            )

    freshness = (
        f"Data as of {snapshot_at.strftime('%Y-%m-%d %H:%M UTC')}"
        if snapshot_at
        else "No snapshot yet"
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": settings.site_title,
            "snapshot_at": snapshot_at,
            "rows": rows,
            "og_description": f"{settings.site_title} — GPU cloud prices. {freshness}.",
        },
    )


@router.get("/gpu/{gpu_name}", response_class=HTMLResponse)
def gpu_detail_page(
    request: Request,
    gpu_name: str,
    session: Session = Depends(get_db),
) -> HTMLResponse:
    gpu_type = session.query(GpuType).filter_by(name=gpu_name).one_or_none()
    if gpu_type is None:
        raise HTTPException(status_code=404, detail="GPU not found")

    snapshot_at = latest_snapshot_at(session)
    freshness = (
        f"Data as of {snapshot_at.strftime('%Y-%m-%d %H:%M UTC')}"
        if snapshot_at
        else "No snapshot yet"
    )
    return templates.TemplateResponse(
        request,
        "gpu.html",
        {
            "title": f"{gpu_name} — {settings.site_title}",
            "gpu_name": gpu_name,
            "gpu_type": gpu_type,
            "snapshot_at": snapshot_at,
            "og_description": f"{gpu_name} cloud prices on {settings.site_title}. {freshness}.",
        },
    )


@router.get("/methodology", response_class=HTMLResponse)
def methodology_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "methodology.html",
        {
            "title": f"Methodology — {settings.site_title}",
            "probe_methods": PROBE_METHODS,
            "data_license": DATA_LICENSE,
            "og_description": f"How {settings.site_title} collects and publishes GPU prices.",
        },
    )


@router.get("/status", response_class=HTMLResponse)
def status_page(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    data = collect_status(session)
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "title": f"Status — {settings.site_title}",
            "status": data,
            "og_description": f"{settings.site_title} collector status.",
        },
    )


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    return "User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap(session: Session = Depends(get_db)) -> Response:
    snapshot_at = latest_snapshot_at(session)
    gpus = []
    if snapshot_at:
        gpus = [
            g.name
            for g in session.query(GpuType)
            .join(GpuIndexSnapshot, GpuIndexSnapshot.gpu_type_id == GpuType.id)
            .filter(GpuIndexSnapshot.snapshot_at == snapshot_at)
            .order_by(GpuType.name)
            .all()
        ]
    urls = ["/", "/methodology", "/status", "/api/v1/index"]
    urls.extend(f"/gpu/{name}" for name in gpus)
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path in urls:
        body.append(f"  <url><loc>{path}</loc></url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")
