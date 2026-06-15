"""Parse a Meteologica /data response into a tidy, tz-aware DataFrame.

Each row carries its validity interval as local (CPT) wall time plus an explicit
UTC offset (e.g. 'UTC-0500'); values arrive as strings. We normalise both: a
UTC DatetimeIndex and float member columns. See docs/meteologica-api.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

# The four non-value columns present on every /data row.
_TIME_COLS = (
    "From yyyy-mm-dd hh:mm",
    "To yyyy-mm-dd hh:mm",
    "UTC offset from (UTC+/-hhmm)",
    "UTC offset to (UTC+/-hhmm)",
)
_OFFSET_RE = re.compile(r"UTC([+-])(\d{2})(\d{2})")


@dataclass(frozen=True)
class ParsedData:
    """Tidy result: `frame` indexed by UTC valid-time, member columns as floats."""
    frame: pd.DataFrame
    content_id: int
    content_name: str
    unit: str
    timezone: str
    issue_time: pd.Timestamp
    update_id: str


def _parse_offset(text: str) -> pd.Timedelta:
    """'UTC-0500' -> Timedelta(hours=-5)."""
    m = _OFFSET_RE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"Unrecognised UTC offset: {text!r}")
    sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    minutes = (hh * 60 + mm) * (1 if sign == "+" else -1)
    return pd.Timedelta(minutes=minutes)


def parse_data(response: dict[str, Any]) -> ParsedData:
    """Convert a /data response dict into a ParsedData with a UTC DatetimeIndex."""
    rows = response.get("data", [])
    if not rows:
        raise ValueError(f"No data rows in response for content {response.get('content_id')!r}")

    raw = pd.DataFrame(rows)
    # local wall time - offset = UTC instant
    local = pd.to_datetime(raw["From yyyy-mm-dd hh:mm"])
    offset = raw["UTC offset from (UTC+/-hhmm)"].map(_parse_offset)
    valid_utc = (local - offset).dt.tz_localize("UTC")

    value_cols = [c for c in raw.columns if c not in _TIME_COLS]
    values = raw[value_cols].apply(pd.to_numeric, errors="coerce")
    values.index = pd.DatetimeIndex(valid_utc, name="valid_time")

    return ParsedData(
        frame=values,
        content_id=int(response["content_id"]),
        content_name=str(response.get("content_name", "")),
        unit=str(response.get("unit", "")),
        timezone=str(response.get("timezone", "")),
        issue_time=pd.to_datetime(response.get("issue_date"), utc=True, errors="coerce"),
        update_id=str(response.get("update_id", "")),
    )


def member_columns(frame: pd.DataFrame) -> list[str]:
    """Ensemble member columns (ENS00..), in order."""
    return sorted(c for c in frame.columns if c.startswith("ENS"))


def central_column(frame: pd.DataFrame) -> str:
    """The single central value column: 'forecast' (deterministic) or 'Average' (ensemble)."""
    if "forecast" in frame.columns:
        return "forecast"
    if "Average" in frame.columns:
        return "Average"
    raise KeyError(f"No central value column in {list(frame.columns)}")
