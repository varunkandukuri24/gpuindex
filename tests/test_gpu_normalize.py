"""Unit tests for GPU name normalization."""

import pytest

from collectors.gpu_normalize import normalize_gpu


@pytest.mark.parametrize(
    "raw,sku,expected",
    [
        ("H100 SXM5", None, "H100-SXM-80GB"),
        ("NVIDIA H100 80GB HBM3", None, "H100-SXM-80GB"),
        ("h100-sxm", None, "H100-SXM-80GB"),
        ("H100 PCIe", None, "H100-PCIE-80GB"),
        ("NVIDIA A100 80GB PCIe", None, "A100-PCIE-80GB"),
        ("NVIDIA A100-SXM4-80GB", None, "A100-SXM-80GB"),
        ("A100", "gpu_1x_a100", "A100-PCIE-40GB"),
        ("RTX 4090", None, "RTX-4090"),
        ("RTX 5070 Ti", None, None),
        ("B200", None, "B200"),
        ("V100", None, "V100-PCIE-16GB"),
        ("T4", None, "T4-PCIE-16GB"),
        ("L40S", None, "L40S-PCIE-48GB"),
        ("AMD Instinct MI300X OAM", None, "MI300X-OAM-192GB"),
        ("H100", "gpu_1x_h100_pcie", "H100-PCIE-80GB"),
        ("H100", "gpu_8x_h100_sxm", "H100-SXM-80GB"),
    ],
)
def test_normalize_gpu(raw, sku, expected):
    result = normalize_gpu(raw, instance_sku=sku)
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result.canonical_name == expected
