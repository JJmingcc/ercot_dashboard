"""Tests for src.parsing (no network)."""
from __future__ import annotations

import pandas as pd
import pytest

from src.parsing import _parse_offset, central_column, member_columns, parse_data


def _deterministic_response() -> dict:
    return {
        "content_id": 1943,
        "content_name": "USA ERCOT power demand forecast Meteologica hourly",
        "unit": "MW",
        "timezone": "America/Chicago",
        "issue_date": "2026-06-10 00:19:57 UTC",
        "update_id": "202606091800_livefeed_120H",
        "data": [
            {
                "From yyyy-mm-dd hh:mm": "2026-06-09 20:00",
                "To yyyy-mm-dd hh:mm": "2026-06-09 21:00",
                "UTC offset from (UTC+/-hhmm)": "UTC-0500",
                "UTC offset to (UTC+/-hhmm)": "UTC-0500",
                "forecast": "74368",
            },
            {
                "From yyyy-mm-dd hh:mm": "2026-06-09 21:00",
                "To yyyy-mm-dd hh:mm": "2026-06-09 22:00",
                "UTC offset from (UTC+/-hhmm)": "UTC-0500",
                "UTC offset to (UTC+/-hhmm)": "UTC-0500",
                "forecast": "73900",
            },
        ],
    }


def _ensemble_response() -> dict:
    return {
        "content_id": 1910,
        "content_name": "USA ERCOT wind power generation forecast ECMWF ENS hourly",
        "unit": "MW",
        "timezone": "America/Chicago",
        "issue_date": "2026-06-10 00:19:57 UTC",
        "update_id": "u1",
        "data": [
            {
                "From yyyy-mm-dd hh:mm": "2026-06-09 20:00",
                "To yyyy-mm-dd hh:mm": "2026-06-09 21:00",
                "UTC offset from (UTC+/-hhmm)": "UTC-0500",
                "UTC offset to (UTC+/-hhmm)": "UTC-0500",
                "Average": "5000", "Bottom": "4000", "Top": "6000",
                "ENS00": "4800", "ENS01": "5200",
            },
        ],
    }


def test_parse_offset_negative() -> None:
    assert _parse_offset("UTC-0500") == pd.Timedelta(hours=-5)


def test_parse_offset_positive() -> None:
    assert _parse_offset("UTC+0130") == pd.Timedelta(hours=1, minutes=30)


def test_parse_offset_invalid_raises() -> None:
    with pytest.raises(ValueError):
        _parse_offset("CST")


def test_parse_data_converts_local_to_utc() -> None:
    pd_ = parse_data(_deterministic_response())
    # 2026-06-09 20:00 at UTC-0500 == 2026-06-10 01:00 UTC
    assert pd_.frame.index[0] == pd.Timestamp("2026-06-10 01:00", tz="UTC")
    assert pd_.unit == "MW"
    assert pd_.frame["forecast"].tolist() == [74368, 73900]
    assert pd_.frame["forecast"].dtype.kind in ("i", "f")  # cast from string to numeric


def test_central_column_deterministic_vs_ensemble() -> None:
    det = parse_data(_deterministic_response()).frame
    ens = parse_data(_ensemble_response()).frame
    assert central_column(det) == "forecast"
    assert central_column(ens) == "Average"


def test_member_columns() -> None:
    ens = parse_data(_ensemble_response()).frame
    assert member_columns(ens) == ["ENS00", "ENS01"]
