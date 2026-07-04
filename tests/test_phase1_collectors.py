"""Tests for Phase 1 collectors with HTTP fixtures."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from collectors.lambda_labs import LambdaLabsCollector
from collectors.runpod import RunPodCollector
from collectors.skypilot_catalog import SkyPilotCatalogCollector
from collectors.vast import VastCollector
from config import settings

FIXTURES = Path(__file__).parent / "fixtures"


@respx.mock
def test_skypilot_catalog_collector_parses_gpu_rows():
    providers_json = [{"name": "lambda", "type": "dir"}]
    csv_text = (FIXTURES / "skypilot_lambda_vms.csv").read_text()

    respx.get(
        "https://api.github.com/repos/skypilot-org/skypilot-catalog/contents/catalogs/v7"
    ).mock(return_value=httpx.Response(200, json=providers_json))
    respx.get(
        "https://raw.githubusercontent.com/skypilot-org/skypilot-catalog/master/catalogs/v7/lambda/vms.csv"
    ).mock(return_value=httpx.Response(200, text=csv_text))

    result = SkyPilotCatalogCollector().fetch()

    assert len(result.price_observations) >= 2
    gpu_names = {obs.gpu_type_name for obs in result.price_observations}
    assert "H100-PCIE-80GB" in gpu_names
    assert "A100-SXM-80GB" in gpu_names
    assert all(obs.provider_slug == "lambda" for obs in result.price_observations)


@respx.mock
def test_vast_collector_prices_and_availability():
    payload = json.loads((FIXTURES / "vast_bundles.json").read_text())
    respx.post("https://console.vast.ai/api/v0/bundles/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = VastCollector().fetch()

    assert len(result.price_observations) == 2
    assert len(result.availability_observations) == 2
    assert all(obs.status == "available" for obs in result.availability_observations)
    gpu_names = {obs.gpu_type_name for obs in result.price_observations}
    assert "RTX-4090" in gpu_names
    assert "H100-SXM-80GB" in gpu_names


@respx.mock
def test_runpod_collector_graphql():
    payload = json.loads((FIXTURES / "runpod_gpu_types.json").read_text())
    respx.post("https://api.runpod.io/graphql").mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = RunPodCollector().fetch()

    assert len(result.price_observations) >= 2
    assert any(obs.gpu_type_name == "H100-SXM-80GB" for obs in result.price_observations)
    assert all(obs.provider_slug == "runpod-api" for obs in result.price_observations)


def test_lambda_collector_degraded_without_key():
    with patch.object(settings, "lambda_api_key", None):
        result = LambdaLabsCollector().fetch()
    assert result.price_observations == []
    assert result.availability_observations == []


@respx.mock
def test_lambda_collector_with_key():
    payload = json.loads((FIXTURES / "lambda_instance_types.json").read_text())
    respx.get("https://cloud.lambda.ai/api/v1/instance-types").mock(
        return_value=httpx.Response(200, json=payload)
    )

    with patch.object(settings, "lambda_api_key", "test-key"):
        result = LambdaLabsCollector().fetch()

    assert len(result.price_observations) == 2
    assert any(obs.gpu_type_name == "H100-SXM-80GB" for obs in result.price_observations)
    assert len(result.availability_observations) == 2
    assert {obs.status for obs in result.availability_observations} == {"available", "unavailable"}
