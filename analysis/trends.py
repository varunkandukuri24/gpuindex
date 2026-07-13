"""Index-page trend helpers — sparklines and % change from price history rollups."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from db.models import PriceHistoryPoint

SPARKLINE_POINTS = 56
TREND_DAYS = 7


def build_index_trends(
    session: Session, snapshot_at: datetime
) -> dict[int, dict[str, Any]]:
    """Return per-gpu_type_id trend payload for the latest index snapshot."""
    if snapshot_at.tzinfo is None:
        snapshot_at = snapshot_at.replace(tzinfo=UTC)

    since = snapshot_at - timedelta(days=TREND_DAYS)
    rows = (
        session.query(PriceHistoryPoint)
        .filter(
            PriceHistoryPoint.snapshot_at == snapshot_at,
            PriceHistoryPoint.hour_bucket >= since,
        )
        .order_by(PriceHistoryPoint.hour_bucket)
        .all()
    )

    by_gpu: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for row in rows:
        hour = row.hour_bucket
        if hour.tzinfo is None:
            hour = hour.replace(tzinfo=UTC)
        by_gpu[row.gpu_type_id].append((hour, row.median_per_gpu_hour_usd))

    result: dict[int, dict[str, Any]] = {}
    for gpu_id, series in by_gpu.items():
        medians = [price for _, price in series]
        current = medians[-1]
        change_7d = pct_change_vs_lookback(series, current, hours=24 * TREND_DAYS)
        result[gpu_id] = {
            "sparkline": downsample(medians, SPARKLINE_POINTS),
            "change_24h_pct": pct_change_vs_lookback(series, current, hours=24),
            "change_7d_pct": change_7d,
            "trend_down": change_7d is not None and change_7d < 0,
        }
    return result


def downsample(values: list[float], max_points: int) -> list[float]:
    if len(values) <= max_points:
        return [round(v, 4) for v in values]
    if max_points <= 1:
        return [round(values[-1], 4)]

    step = (len(values) - 1) / (max_points - 1)
    sampled = [values[round(i * step)] for i in range(max_points)]
    return [round(v, 4) for v in sampled]


def pct_change_vs_lookback(
    series: list[tuple[datetime, float]],
    current: float,
    *,
    hours: int,
) -> float | None:
    """Percent change from the value nearest to (latest - hours) to current."""
    if not series or current is None:
        return None

    latest_hour = series[-1][0]
    target = latest_hour - timedelta(hours=hours)

    past: float | None = None
    for hour, price in series:
        if hour <= target:
            past = price
        else:
            break

    # Not enough history yet (series starts after the lookback target)
    if past is None:
        return None
    if past == 0:
        return None
    return round((current - past) / past * 100.0, 1)


def sparkline_svg(
    values: list[float],
    *,
    width: int = 320,
    height: int = 96,
    filled: bool = True,
) -> str:
    """Inline SVG area/line chart for index cards (prices falling = green)."""
    if len(values) < 2:
        return ""

    lo = min(values)
    hi = max(values)
    # Pad the y-range so flat series still have some visual shape
    span = hi - lo
    if span <= 0:
        pad_y = max(abs(hi) * 0.02, 0.01)
        lo -= pad_y
        hi += pad_y
        span = hi - lo
    else:
        pad_y = span * 0.12
        lo -= pad_y
        hi += pad_y
        span = hi - lo

    pad_x = 0.0
    pad_top = 4.0
    pad_bottom = 2.0
    chart_h = height - pad_top - pad_bottom

    coords: list[tuple[float, float]] = []
    for i, value in enumerate(values):
        x = pad_x + (i / (len(values) - 1)) * (width - 2 * pad_x)
        y = pad_top + chart_h - ((value - lo) / span) * chart_h
        coords.append((x, y))

    falling = values[-1] <= values[0]
    stroke = "#0f766e" if falling else "#c2410c"
    fill = "rgba(15,118,110,0.22)" if falling else "rgba(194,65,12,0.20)"
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)

    parts = [
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" '
        f'width="100%" height="{height}" preserveAspectRatio="none" aria-hidden="true">'
    ]
    if filled:
        area = (
            f"M {coords[0][0]:.1f},{height - pad_bottom:.1f} "
            + " ".join(f"L {x:.1f},{y:.1f}" for x, y in coords)
            + f" L {coords[-1][0]:.1f},{height - pad_bottom:.1f} Z"
        )
        parts.append(f'<path class="spark-fill" d="{area}" fill="{fill}"/>')
    parts.append(
        f'<polyline class="spark-line" fill="none" stroke="{stroke}" stroke-width="2.25" '
        f'stroke-linecap="round" stroke-linejoin="round" points="{line_points}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def availability_level(indicator: str, rate: float | None) -> tuple[str, int]:
    """Map availability to (label, filled_segments out of 4)."""
    if indicator == "green" or (rate is not None and rate >= 0.7):
        return "High", 4
    if indicator == "yellow" or (rate is not None and rate >= 0.3):
        return "Med", 2
    if indicator == "red" or (rate is not None and rate >= 0):
        return "Low", 1
    return "—", 0

