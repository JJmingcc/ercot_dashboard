"""Historical ERCOT panel for weather-normalization analysis (2022 vs 2025/26).

Pulls demand/wind/PV **observations** (Meteologica `historical_data`, a ZIP of JSON)
+ ERA5 temperature (Open-Meteo archive), cleans to an hourly UTC grid, and assembles
net load. Cached to Parquet under data/history/. See docs/concepts.md ("temperature
normalization") for the why; the goal is comparing the early-battery (2022) era to the
scaled-battery (2025/26) era with weather held constant.
"""
from __future__ import annotations

import calendar
import pathlib

import pandas as pd

from .config import PROJECT_ROOT
from .meteologica_client import MeteologicaClient
from .parsing import parse_data
from .weather import MARKETS, fetch_archive

HIST_DIR = PROJECT_ROOT / "data" / "history"

# Whole-ERCOT observation content ids (verified via the catalog probe).
ERCOT_OBS: dict[str, int] = {"demand": 1969, "wind": 1929, "pv": 1865}

# Per-zone observed *demand* content ids — the 8 ERCOT weather zones (Meteologica
# PowerDemand/Observation/<zone>). Keys MUST match weather.MARKETS["ERCOT"]["zones"] so each zone's
# demand pairs with its own ERA5 temperature column. (Wind is published by geo-region and solar is
# system-only, so only DEMAND splits cleanly by zone — net load stays a system quantity.)
ERCOT_ZONE_DEMAND_OBS: dict[str, int] = {
    "Coast": 1970, "East": 1971, "North": 1972, "Far West": 1973,
    "South Central": 1974, "North Central": 1975, "West": 1976, "Southern": 1977,
}

# Battery storage net output observation (MW): **+ = discharging to grid, − = charging from grid**.
# System-wide only; the series exists from ~late 2024 (earlier months 404 → column simply absent).
# Charging is part of `demand` (it's load); `min(battery_net, 0)` is the charging component we can
# remove to get demand *excluding* battery charging. See data-sources.md §9 / concepts.md §6.
ERCOT_BATTERY_OBS: int = 7044


def fetch_clean_month(client: MeteologicaClient, content_id: int, year: int, month: int) -> pd.Series:
    """One month of an observation as an hourly UTC series (deduped + resampled).

    The historical ZIP merges several overlapping vintages, so we drop duplicate
    timestamps (keep last) and resample to hour-start.
    """
    frame = parse_data(client.get_historical_data(content_id, year, month)).frame
    s = frame[frame.columns[0]].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.resample("1h").mean()


def ercot_zone_temperatures(year: int, month: int) -> pd.DataFrame:
    """ERA5 per-zone temperature (°F), hourly UTC — one column per ERCOT weather zone."""
    last = calendar.monthrange(year, month)[1]
    df = fetch_archive(MARKETS["ERCOT"]["zones"], f"{year}-{month:02d}-01",
                       f"{year}-{month:02d}-{last:02d}", "fahrenheit")
    return df.pivot_table(index="time", columns="zone", values="temp")


def ercot_temperature(year: int, month: int) -> pd.Series:
    """ERA5 ERCOT temperature (°F), hourly UTC — mean across the 8 weather-zone cities."""
    return ercot_zone_temperatures(year, month).mean(axis=1).rename("temp")


def panel_path(year: int, month: int) -> pathlib.Path:
    return HIST_DIR / f"ercot_{year}_{month:02d}.parquet"


def build_panel(client: MeteologicaClient, year: int, month: int) -> pd.DataFrame:
    """Hourly panel (UTC index), cached to Parquet. Columns:
    - system: demand, wind, pv, net_load, temp;
    - per zone: demand_<zone> (observed MW) + temp_<zone> (ERA5 °F) for the 8 weather zones.
    Zone columns may carry NaNs (a zone's series can have gaps); only the *system* columns gate the
    row, so the whole-ERCOT panel is unchanged from before this addition."""
    cols = {role: fetch_clean_month(client, cid, year, month) for role, cid in ERCOT_OBS.items()}
    panel = pd.DataFrame(cols)
    panel["net_load"] = panel["demand"] - panel["wind"] - panel["pv"]
    ztemps = ercot_zone_temperatures(year, month)          # one temp column per zone
    panel["temp"] = ztemps.mean(axis=1)                    # system mean (unchanged definition)
    for zone, cid in ERCOT_ZONE_DEMAND_OBS.items():        # per-zone observed demand + temperature
        try:
            panel[f"demand_{zone}"] = fetch_clean_month(client, cid, year, month)
        except Exception:                                  # a zone may be missing for an old month
            pass
        if zone in ztemps.columns:
            panel[f"temp_{zone}"] = ztemps[zone]
    try:                                                   # battery net output (~late-2024 onward)
        panel["battery_net"] = fetch_clean_month(client, ERCOT_BATTERY_OBS, year, month)
    except Exception:                                      # older months 404 → column simply absent
        pass
    panel = panel.dropna(subset=["demand", "wind", "pv", "net_load", "temp"])  # zone/battery may be NaN
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(panel_path(year, month))
    return panel


def load_panel(year: int, month: int) -> pd.DataFrame:
    """Read a cached month panel (empty DataFrame if not yet built)."""
    p = panel_path(year, month)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def available_months() -> dict[int, list[int]]:
    """{year: [months]} for every cached panel on disk (drives the UI selectors)."""
    out: dict[int, list[int]] = {}
    if HIST_DIR.exists():
        for p in HIST_DIR.glob("ercot_*.parquet"):
            parts = p.stem.split("_")
            if len(parts) == 3:
                try:
                    out.setdefault(int(parts[1]), []).append(int(parts[2]))
                except ValueError:
                    continue
    return {y: sorted(ms) for y, ms in sorted(out.items())}
