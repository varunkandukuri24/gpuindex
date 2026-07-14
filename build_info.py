"""Runtime build identity — baked at image build time."""

from __future__ import annotations

import os

# Set via Dockerfile ARG / ENV. Falls back for local `uvicorn` / pytest.
GIT_SHA = os.environ.get("GIT_SHA", "dev").strip() or "dev"


def short_sha() -> str:
    return GIT_SHA[:12] if GIT_SHA != "dev" else "dev"
