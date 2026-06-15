"""Tests for src.storage snapshot persistence (writes to a tmp dir)."""
from __future__ import annotations

import pandas as pd
import pytest

from src import storage


def test_save_load_roundtrip_and_idempotent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "WEATHER_DIR", tmp_path / "weather")
    t = pd.Timestamp("2026-06-10T03:00:00Z")
    p1 = storage.save_now_snapshot("ERCOT", "gfs_seamless", "°F",
                                   ["48201"], [29.7], [-95.4], [80.1], t)
    assert p1.exists()
    # Same hour -> idempotent (no duplicate file/path).
    p2 = storage.save_now_snapshot("ERCOT", "gfs_seamless", "°F",
                                   ["48201"], [29.7], [-95.4], [80.1], t)
    assert p2 == p1
    assert storage.snapshot_count() == 1

    df = storage.load_history("ERCOT")
    assert len(df) == 1
    assert df.iloc[0]["temp_now"] == 80.1
    assert df.iloc[0]["model"] == "gfs_seamless"


def test_load_history_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "WEATHER_DIR", tmp_path / "nope")
    assert storage.load_history().empty
    assert storage.snapshot_count() == 0
