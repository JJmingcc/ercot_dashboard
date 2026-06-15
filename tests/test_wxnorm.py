"""Tests for the weather-normalization analysis helpers (no I/O)."""
from __future__ import annotations

import pandas as pd

from src.wxnorm import diurnal, response_by_temp


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2025-07-01", periods=n, freq="h", tz="UTC")


def test_response_by_temp_bins_means() -> None:
    df = pd.DataFrame({"temp": [90] * 10 + [100] * 10, "net_load": [50000] * 10 + [60000] * 10},
                      index=_idx(20))
    r = response_by_temp(df, "net_load", width=2.0, min_count=5)
    assert r.loc[90.0, "mean"] == 50000.0
    assert r.loc[100.0, "mean"] == 60000.0


def test_response_by_temp_drops_sparse_bins() -> None:
    df = pd.DataFrame({"temp": [90, 90, 90, 90, 90, 100], "net_load": list(range(6))}, index=_idx(6))
    r = response_by_temp(df, "net_load", width=2.0, min_count=5)
    assert 90.0 in r.index and 100.0 not in r.index  # 100°F bin has only 1 sample


def test_diurnal_means_by_hour_in_bin() -> None:
    df = pd.DataFrame({"temp": [95] * 48, "net_load": list(range(48)),
                       "hour": [i % 24 for i in range(48)]}, index=_idx(48))
    d = diurnal(df, "net_load", 90, 100)
    assert d.loc[0] == 12.0       # hour 0 has values 0 and 24 -> mean 12
    assert d.loc[5] == 17.0       # hour 5 has 5 and 29 -> mean 17


def test_diurnal_respects_temp_filter() -> None:
    df = pd.DataFrame({"temp": [80] * 12 + [95] * 12, "net_load": [1.0] * 12 + [9.0] * 12,
                       "hour": list(range(12)) + list(range(12))}, index=_idx(24))
    d = diurnal(df, "net_load", 90, 100)  # only the 95°F half
    assert (d == 9.0).all()
