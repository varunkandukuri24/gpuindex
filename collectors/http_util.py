"""Shared HTTP client helpers for collectors."""

from __future__ import annotations

import httpx

from config import settings

DEFAULT_TIMEOUT = 30.0


def user_agent() -> str:
    return f"gpu-index/0.1 (+mailto:{settings.contact_email})"


def get_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers={"User-Agent": user_agent()},
        follow_redirects=True,
    )
