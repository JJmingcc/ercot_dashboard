"""Backfill ERCOT historical summer panels for the weather-normalization analysis.

Caches demand/wind/PV observations + ERA5 temperature to Parquet (data/history/) for the
battery-era comparison. Meteologica history reaches ~2022; battery obs only ~2025.

    source dash_env/bin/activate
    python -m src.backfill_history                 # 2022 & 2025, Jun-Aug
    python -m src.backfill_history 2023 2024       # extra years
    python -m src.backfill_history --force         # rebuild cached months (e.g. after a schema change)
"""
from __future__ import annotations

import sys

from .historical import build_panel, panel_path
from .meteologica_client import MeteologicaClient


def run(years: tuple[int, ...] = (2022, 2025), months: tuple[int, ...] = (6, 7, 8),
        force: bool = False) -> None:
    """Build/cache the ERCOT history panels. `force=True` rebuilds months already on disk — needed
    after a schema change (e.g. adding per-zone demand/temperature columns)."""
    client = MeteologicaClient()
    for year in years:
        for month in months:
            if panel_path(year, month).exists() and not force:
                print(f"  {year}-{month:02d}: cached")
                continue
            try:
                panel = build_panel(client, year, month)
                print(f"  {year}-{month:02d}: built {len(panel)} hrs, {panel.shape[1]} cols")
            except Exception as exc:
                print(f"  {year}-{month:02d}: ERROR {str(exc)[:70]}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    yrs = tuple(int(a) for a in sys.argv[1:] if not a.startswith("-")) or (2022, 2025)
    run(yrs, force=force)
