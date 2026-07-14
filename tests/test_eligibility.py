"""Tests for marketplace eligibility rules."""

from analysis.eligibility import is_index_eligible


def test_catalog_providers_always_eligible():
    assert is_index_eligible(provider_slug="lambda-api", attrs={})
    assert is_index_eligible(provider_slug="runpod-api", attrs={})
    assert is_index_eligible(provider_slug="aws", attrs={})


def test_vast_requires_reliability_and_verified():
    assert is_index_eligible(
        provider_slug="vast",
        attrs={"reliability2": 0.99, "verified": True},
    )
    assert not is_index_eligible(
        provider_slug="vast",
        attrs={"reliability2": 0.90, "verified": True},
    )
    assert not is_index_eligible(
        provider_slug="vast",
        attrs={"reliability2": 0.99, "verified": False},
    )
    assert not is_index_eligible(provider_slug="vast", attrs={})
