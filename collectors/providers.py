"""Provider metadata registry for collector persistence."""

from db.models import ApiType, ProviderKind

ProviderMeta = tuple[str, str, str]  # display_name, kind, api_type

PROVIDER_REGISTRY: dict[str, ProviderMeta] = {
    # Hyperscalers (SkyPilot catalog)
    "aws": ("AWS", ProviderKind.HYPERSCALER.value, ApiType.CATALOG_SCRAPE.value),
    "azure": ("Azure", ProviderKind.HYPERSCALER.value, ApiType.CATALOG_SCRAPE.value),
    "gcp": ("GCP", ProviderKind.HYPERSCALER.value, ApiType.CATALOG_SCRAPE.value),
    "oci": ("OCI", ProviderKind.HYPERSCALER.value, ApiType.CATALOG_SCRAPE.value),
    "ibm": ("IBM Cloud", ProviderKind.HYPERSCALER.value, ApiType.CATALOG_SCRAPE.value),
    # Neoclouds
    "lambda": ("Lambda Cloud", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "runpod": ("RunPod", ProviderKind.NEOCLOUD.value, ApiType.GRAPHQL.value),
    "paperspace": ("Paperspace", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "nebius": ("Nebius", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "fluidstack": ("Fluidstack", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "hyperstack": ("Hyperstack", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "do": ("DigitalOcean", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "cudo": ("Cudo", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "scaleway": ("Scaleway", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "ovhcloud": ("OVHcloud", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "seeweb": ("Seeweb", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "scp": ("SCP", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "mithril": ("Mithril", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "hyperbolic": ("Hyperbolic", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    "primeintellect": ("Prime Intellect", ProviderKind.NEOCLOUD.value, ApiType.CATALOG_SCRAPE.value),
    # Marketplace
    "vast": ("Vast.ai", ProviderKind.MARKETPLACE.value, ApiType.REST.value),
    # Direct API collectors (not SkyPilot)
    "runpod-api": ("RunPod API", ProviderKind.NEOCLOUD.value, ApiType.GRAPHQL.value),
    "lambda-api": ("Lambda Cloud API", ProviderKind.NEOCLOUD.value, ApiType.REST.value),
}

SKYPILOT_SKIP_PROVIDERS = frozenset({"common", "kubernetes"})
