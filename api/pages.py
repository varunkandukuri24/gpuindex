"""HTML page routes for the public index site."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from analysis.rollups import latest_snapshot_at
from analysis.trends import availability_level, build_index_trends, sparkline_svg
from api.deps import get_db
from config import settings
from db.models import GpuIndexSnapshot, GpuType

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

router = APIRouter(tags=["pages"])


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
            .order_by(GpuIndexSnapshot.cheapest_listed_per_gpu_hour_usd.asc())
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
                    "avail_label": avail_label,
                    "avail_segments": avail_segments,
                }
            )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": settings.site_title,
            "snapshot_at": snapshot_at,
            "rows": rows,
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
    return templates.TemplateResponse(
        request,
        "gpu.html",
        {
            "title": f"{gpu_name} — {settings.site_title}",
            "gpu_name": gpu_name,
            "gpu_type": gpu_type,
            "snapshot_at": snapshot_at,
        },
    )


@router.get("/methodology", response_class=HTMLResponse)
def methodology_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "methodology.html",
        {"title": f"Methodology — {settings.site_title}"},
    )
