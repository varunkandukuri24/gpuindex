"""Canonical GPU type normalization across providers."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Explicit alias map: lowercase key -> canonical name
ALIASES: dict[str, str] = {
    "h100 sxm5": "H100-SXM-80GB",
    "h100-sxm": "H100-SXM-80GB",
    "h100 sxm": "H100-SXM-80GB",
    "h100-sxm4-80gb": "H100-SXM-80GB",
    "h100 80gb hbm3": "H100-SXM-80GB",
    "a100 80gb pcie": "A100-PCIE-80GB",
    "h100 pcie": "H100-PCIE-80GB",
    "h100-pcie": "H100-PCIE-80GB",
    "h200": "H200-SXM-141GB",
    "b200": "B200",
    "nvidia b200": "B200",
    "a100-sxm4-80gb": "A100-SXM-80GB",
    "a100 sxm": "A100-SXM-80GB",
    "a100-sxm4-40gb": "A100-SXM-40GB",
    "a100 pcie": "A100-PCIE-80GB",
    "a10": "A10-PCIE-24GB",
    "a40": "A40-PCIE-48GB",
    "l40s": "L40S-PCIE-48GB",
    "l40": "L40-PCIE-48GB",
    "rtx 4090": "RTX-4090",
    "rtx4090": "RTX-4090",
    "4090": "RTX-4090",
    "rtx 5090": "RTX-5090",
    "rtx5090": "RTX-5090",
    "rtx 3090": "RTX-3090",
    "rtx3090": "RTX-3090",
    "v100": "V100-PCIE-16GB",
    "t4": "T4-PCIE-16GB",
    "l4": "L4-PCIE-24GB",
    "mi300x": "MI300X-OAM-192GB",
    "amd instinct mi300x oam": "MI300X-OAM-192GB",
}

ARCHITECTURE_BY_CANONICAL: dict[str, str] = {
    "H100-SXM-80GB": "hopper",
    "H100-PCIE-80GB": "hopper",
    "H200-SXM-141GB": "hopper",
    "B200": "blackwell",
    "A100-SXM-80GB": "ampere",
    "A100-SXM-40GB": "ampere",
    "A100-PCIE-80GB": "ampere",
    "A100-PCIE-40GB": "ampere",
    "A10-PCIE-24GB": "ampere",
    "A40-PCIE-48GB": "ampere",
    "L40S-PCIE-48GB": "ada",
    "L40-PCIE-48GB": "ada",
    "RTX-4090": "ada",
    "RTX-5090": "blackwell",
    "RTX-3090": "ampere",
    "V100-PCIE-16GB": "volta",
    "T4-PCIE-16GB": "turing",
    "L4-PCIE-24GB": "ada",
    "MI300X-OAM-192GB": "cdna3",
}

VRAM_BY_CANONICAL: dict[str, int] = {
    "H100-SXM-80GB": 80,
    "H100-PCIE-80GB": 80,
    "H200-SXM-141GB": 141,
    "B200": 192,
    "A100-SXM-80GB": 80,
    "A100-SXM-40GB": 40,
    "A100-PCIE-80GB": 80,
    "A100-PCIE-40GB": 40,
    "A10-PCIE-24GB": 24,
    "A40-PCIE-48GB": 48,
    "L40S-PCIE-48GB": 48,
    "L40-PCIE-48GB": 48,
    "RTX-4090": 24,
    "RTX-5090": 32,
    "RTX-3090": 24,
    "V100-PCIE-16GB": 16,
    "T4-PCIE-16GB": 16,
    "L4-PCIE-24GB": 24,
    "MI300X-OAM-192GB": 192,
}


@dataclass(frozen=True)
class NormalizedGpu:
    canonical_name: str
    vram_gb: int | None
    architecture: str | None


def _clean(raw: str) -> str:
    text = raw.strip().lower()
    text = re.sub(r"^nvidia\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _from_vram(model: str, vram_mb: int | None, sku: str = "") -> str | None:
    combined = f"{model} {sku}".lower()
    vram_gb = None
    if vram_mb:
        vram_gb = round(vram_mb / 1024)

    if "h100" in combined:
        if "sxm" in combined or "hbm3" in combined:
            return "H100-SXM-80GB"
        return "H100-PCIE-80GB"
    if "a100" in combined:
        if "sxm" in combined:
            return "A100-SXM-40GB" if vram_gb == 40 else "A100-SXM-80GB"
        if "80" in combined or (vram_gb and vram_gb >= 80):
            return "A100-PCIE-80GB"
        return "A100-PCIE-40GB"
    if "4090" in combined:
        return "RTX-4090"
    if "5090" in combined:
        return "RTX-5090"
    if "3090" in combined:
        return "RTX-3090"
    if "l40s" in combined or model == "l40 s":
        return "L40S-PCIE-48GB"
    if model == "l40":
        return "L40-PCIE-48GB"
    if "b200" in combined:
        return "B200"
    if "h200" in combined:
        return "H200-SXM-141GB"
    if "mi300" in combined:
        return "MI300X-OAM-192GB"
    return None


def normalize_gpu(
    raw_name: str,
    *,
    vram_mb: int | None = None,
    instance_sku: str | None = None,
) -> NormalizedGpu | None:
    """Map provider-specific GPU names to canonical GpuType names."""
    if not raw_name or not raw_name.strip():
        return None

    cleaned = _clean(raw_name)
    sku = _clean(instance_sku or "")

    if cleaned in ALIASES:
        canonical = ALIASES[cleaned]
    elif sku in ALIASES:
        canonical = ALIASES[sku]
    else:
        canonical = _from_vram(cleaned, vram_mb, sku)
        if canonical is None:
            canonical = _from_vram(sku, vram_mb, sku)

    if canonical is None:
        return None

    vram_gb = VRAM_BY_CANONICAL.get(canonical)
    if vram_gb is None and vram_mb:
        vram_gb = max(1, round(vram_mb / 1024))

    return NormalizedGpu(
        canonical_name=canonical,
        vram_gb=vram_gb,
        architecture=ARCHITECTURE_BY_CANONICAL.get(canonical),
    )
