"""Index-eligibility rules for marketplace offers (single source of truth).

Ineligible offers are still stored (append-only) and may count toward listing-volume
metrics, but they must not set floor/median headline statistics on the public index.
"""

from __future__ import annotations

from typing import Any

# Marketplace offers must meet both thresholds to influence index floors/medians.
# Tuned for Vast.ai signals: reliability2 (or reliability) in [0,1] and verified hosts.
MARKETPLACE_MIN_RELIABILITY = 0.95
MARKETPLACE_REQUIRE_VERIFIED = True

# Trend / robust-stat sample gates (Task 4)
MIN_ELIGIBLE_OFFERS_FOR_TREND = 5
MIN_ELIGIBLE_PROVIDERS_FOR_TREND = 3

MARKETPLACE_PROVIDER_SLUGS = frozenset({"vast"})


def is_index_eligible(
    *,
    provider_slug: str,
    billing_kind: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> bool:
    """Return True if this observation may set floor/median index stats."""
    _ = billing_kind  # reserved for future kind-specific rules
    if provider_slug not in MARKETPLACE_PROVIDER_SLUGS:
        # Catalog/API providers (SkyPilot, Lambda, RunPod) are always eligible.
        return True

    attrs = attrs or {}
    reliability = _reliability(attrs)
    if reliability is None or reliability < MARKETPLACE_MIN_RELIABILITY:
        return False

    if MARKETPLACE_REQUIRE_VERIFIED and not _is_verified(attrs):
        return False

    return True


def _reliability(attrs: dict[str, Any]) -> float | None:
    for key in ("reliability2", "reliability"):
        raw = attrs.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _is_verified(attrs: dict[str, Any]) -> bool:
    for key in ("verified", "host_verified", "is_verified"):
        if key in attrs:
            return bool(attrs[key])
    # If Vast omit verified, treat as unverified when requirement is on.
    return False
