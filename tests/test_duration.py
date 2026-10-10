"""Tests for duration parsing utilities."""
import pytest
from app.core.duration import format_duration, parse_duration


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("15m") == 900
        assert parse_duration("5m") == 300
        assert parse_duration("60m") == 3600

    def test_seconds(self):
        assert parse_duration("90s") == 90
        assert parse_duration("30s") == 30

    def test_hours(self):
        assert parse_duration("1h") == 3600
        assert parse_duration("2h") == 7200

    def test_compound(self):
        assert parse_duration("1h30m") == 5400
        assert parse_duration("1h5m30s") == 3930

    def test_plain_integer(self):
        assert parse_duration("900") == 900

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_duration("abc")
        with pytest.raises(ValueError):
            parse_duration("")


class TestFormatDuration:
    def test_minutes(self):
        assert "15m" in format_duration(900)

    def test_hours(self):
        assert "1h" in format_duration(3600)

    def test_seconds_only(self):
        assert "45s" in format_duration(45)
