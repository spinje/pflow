"""Unit tests for `core/duration_format.py`.

Pins the breakpoint rendering + edge-case handling directly. If thresholds
shift, these tests make the contract break explicit.
"""

from __future__ import annotations

import math

import pytest

from pflow.core.duration_format import format_duration


class TestSubSecond:
    def test_zero(self) -> None:
        assert format_duration(0) == "0ms"

    def test_sub_millisecond_rounds_to_zero(self) -> None:
        assert format_duration(0.4) == "0ms"

    def test_typical_milliseconds(self) -> None:
        assert format_duration(450) == "450ms"

    def test_fractional_ms_rounds_to_nearest(self) -> None:
        assert format_duration(450.6) == "451ms"

    def test_just_below_one_second(self) -> None:
        assert format_duration(999) == "999ms"


class TestSeconds:
    def test_exactly_one_second(self) -> None:
        assert format_duration(1000) == "1.0s"

    def test_typical_seconds(self) -> None:
        assert format_duration(2340) == "2.3s"

    def test_just_below_one_minute(self) -> None:
        assert format_duration(59_999) == "60.0s"


class TestMinutes:
    def test_exactly_one_minute(self) -> None:
        assert format_duration(60_000) == "1m0s"

    def test_typical_minutes(self) -> None:
        assert format_duration(192_000) == "3m12s"

    def test_rounds_up_seconds(self) -> None:
        # 3m59.6s → rounds to 4m0s (carry over)
        assert format_duration(239_600) == "4m0s"

    def test_just_below_one_hour(self) -> None:
        # 59m59.9s → rounds to 1h0m (carry over)
        assert format_duration(3_599_900) == "1h0m"


class TestHours:
    def test_exactly_one_hour(self) -> None:
        assert format_duration(3_600_000) == "1h0m"

    def test_typical_hours(self) -> None:
        # 1h5m
        assert format_duration(3_900_000) == "1h5m"

    def test_rounds_up_minutes(self) -> None:
        # 1h59m31s → rounds minutes to 60 → 2h0m
        assert format_duration(7_171_000) == "2h0m"


class TestEdgeCases:
    def test_negative_treated_as_zero(self) -> None:
        assert format_duration(-50) == "0ms"

    def test_nan_treated_as_zero(self) -> None:
        assert format_duration(math.nan) == "0ms"


@pytest.mark.parametrize(
    "ms,expected",
    [
        (0, "0ms"),
        (1, "1ms"),
        (500, "500ms"),
        (1_000, "1.0s"),
        (2_345, "2.3s"),
        (60_000, "1m0s"),
        (125_000, "2m5s"),
        (3_600_000, "1h0m"),
        (3_900_000, "1h5m"),
    ],
)
def test_representative_samples(ms: float, expected: str) -> None:
    assert format_duration(ms) == expected
