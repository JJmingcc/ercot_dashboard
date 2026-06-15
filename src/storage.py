"""Local persistence of temperature snapshots.

Open-Meteo only serves a limited recent window (forecast ~16 days ahead, archive lags
~5 days), so to build our own history of *what was forecast when* we append each
per-county "now" pull to Parquet. Files are Hive-partitioned by market and date and
are idempotent per hour, so browsing the app (or a scheduled ingest) accumulates an
archive without duplicates. `data/` is gitignored.
"""
from __future__ import annotations

import pathlib

import pandas as pd

from .config import PROJECT_ROOT

WEATHER_DIR = PROJECT_ROOT / "data" / "weather"


def _unit_tag(unit: str) -> str:
    return "F" if unit == "°F" else "C"


def save_now_snapshot(market: str, model: str, unit: str, fips: list, lats: list,
                      lons: list, temps: list, fetched_at: pd.Timestamp) -> pathlib.Path:
    """Append a per-county 'now' snapshot (idempotent per market/model/unit/hour)."""
    hour = fetched_at.strftime("%Y%m%dT%H00Z")
    out_dir = WEATHER_DIR / f"market={market}" / f"date={fetched_at:%Y-%m-%d}"
    path = out_dir / f"{model}_{_unit_tag(unit)}_{hour}.parquet"
    if path.exists():
        return path  # already captured this hour
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "fetched_at": fetched_at, "market": market, "model": model, "unit": unit,
        "fips": fips, "lat": lats, "lon": lons, "temp_now": temps,
    }).to_parquet(path, index=False)
    return path


def load_history(market: str | None = None) -> pd.DataFrame:
    """Read all saved snapshots (optionally a single market)."""
    root = WEATHER_DIR if market is None else WEATHER_DIR / f"market={market}"
    files = sorted(root.rglob("*.parquet")) if root.exists() else []
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def snapshot_count() -> int:
    return len(list(WEATHER_DIR.rglob("*.parquet"))) if WEATHER_DIR.exists() else 0
