"""Unit tests for index sparklines and % change helpers."""

from datetime import UTC, datetime, timedelta

from analysis.trends import downsample, pct_change_vs_lookback, sparkline_svg


def test_downsample_keeps_short_series():
    assert downsample([1.0, 2.0, 3.0], 10) == [1.0, 2.0, 3.0]


def test_downsample_thins_long_series():
    values = [float(i) for i in range(100)]
    sampled = downsample(values, 10)
    assert len(sampled) == 10
    assert sampled[0] == 0.0
    assert sampled[-1] == 99.0


def test_pct_change_vs_lookback():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    series = [
        (now - timedelta(hours=48), 4.0),
        (now - timedelta(hours=24), 2.0),
        (now, 3.0),
    ]
    assert pct_change_vs_lookback(series, 3.0, hours=24) == 50.0
    assert pct_change_vs_lookback(series, 3.0, hours=48) == -25.0


def test_pct_change_insufficient_history():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    series = [(now - timedelta(hours=2), 2.0), (now, 3.0)]
    assert pct_change_vs_lookback(series, 3.0, hours=24) is None


def test_sparkline_svg_renders():
    svg = sparkline_svg([1.0, 1.5, 1.2, 0.9])
    assert "polyline" in svg
    assert "spark-fill" in svg
    assert "sparkline" in svg
    assert sparkline_svg([1.0]) == ""


def test_availability_level():
    from analysis.trends import availability_level

    assert availability_level("green", 0.9) == ("High", 4)
    assert availability_level("yellow", 0.4) == ("Med", 2)
    assert availability_level("red", 0.1) == ("Low", 1)
    assert availability_level("unknown", None) == ("—", 0)
