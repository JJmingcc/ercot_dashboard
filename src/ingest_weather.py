"""Pull current temperatures for every market and persist a snapshot.

Run on a schedule (e.g. hourly cron) to accumulate a local temperature archive that
outlives Open-Meteo's recent-data window:

    source dash_env/bin/activate
    python -m src.ingest_weather                 # default model, all markets
    python -m src.ingest_weather gfs_seamless ecmwf_ifs025   # specific models
"""
from __future__ import annotations

import sys

from .geo import assign_nearest_index, load_counties, market_counties, subsample
from .storage import save_now_snapshot, snapshot_count
from .weather import FORECAST_MODEL, MARKETS, points_now

UNIT = "°F"


def run(models: tuple[str, ...] = (FORECAST_MODEL,), max_points: int = 200) -> None:
    counties = load_counties()
    for market in MARKETS:
        recs = market_counties(market, counties)
        samples = subsample(recs, max_points)
        idx = assign_nearest_index(recs, samples)
        fips = [r[0] for r in recs]
        lats = [r[1] for r in recs]
        lons = [r[2] for r in recs]
        for model in models:
            try:
                now_s, t = points_now([s[1] for s in samples], [s[2] for s in samples], UNIT, model)
                now_v = [now_s[i] for i in idx]
                path = save_now_snapshot(market, model, UNIT, fips, lats, lons, now_v, t)
                print(f"  {market:6s} {model:16s} -> {path}")
            except Exception as exc:  # rate limit / transient — keep going
                print(f"  {market:6s} {model:16s} -> SKIPPED ({str(exc)[:60]})")
    print(f"archive now holds {snapshot_count()} snapshot files.")


if __name__ == "__main__":
    requested = tuple(sys.argv[1:]) or (FORECAST_MODEL,)
    run(requested)
