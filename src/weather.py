"""ISO/RTO zone temperature from Open-Meteo (free, no API key).

Meteologica's feed has no temperature, so the temperature map is sourced here.
Supports multiple US markets and temperature *differences* vs a lookback period
(yesterday … one year ago). Recent history (<=90 d) comes from the forecast API's
`past_days`; one-year lookback uses the ERA5 archive API. All times are UTC so the
"same moment N days ago" comparison is clean across markets.
"""
from __future__ import annotations

import time
import warnings

import numpy as np
import pandas as pd
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
# Archived *past forecasts* (what each model predicted on past dates; distinct from ERA5).
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Default forecast model (documentable/reproducible, not auto best_match).
# gfs_seamless = NOAA GFS Seamless: HRRR (~3 km, 0-48 h) + GFS (~13 km global) — US-appropriate.
# Historical (ARCHIVE_URL) is ECMWF ERA5 reanalysis (the archive API default).
FORECAST_MODEL = "gfs_seamless"

# All US-covering Open-Meteo forecast methods (id -> friendly name), selectable in the UI.
FORECAST_MODELS: dict[str, str] = {
    "gfs_seamless": "NOAA GFS Seamless (HRRR+GFS)",
    "gfs_hrrr": "NOAA HRRR (~3 km, ≤48 h)",
    "gfs_global": "NOAA GFS Global (~13 km)",
    "ncep_nbm_conus": "NOAA NBM (National Blend)",
    "ecmwf_ifs025": "ECMWF IFS (0.25°)",
    "icon_seamless": "DWD ICON",
    "gem_seamless": "Environment Canada GEM",
    "jma_seamless": "JMA (Japan)",
    "meteofrance_seamless": "Météo-France ARPEGE/AROME",
}

ENSEMBLE_MODEL = "gfs025"  # NOAA GFS ensemble (31 members) for forecast-spread (±)

# market -> {label, map center (lat,lon), projection scale, zones {zone:(lat,lon,city)}}
MARKETS: dict[str, dict] = {
    "ERCOT": {"label": "ERCOT — Texas", "center": (31.2, -99.4), "scale": 3.6, "zones": {
        "Coast": (29.76, -95.37, "Houston"), "East": (32.35, -95.30, "Tyler"),
        "Far West": (31.997, -102.078, "Midland"), "North": (33.91, -98.49, "Wichita Falls"),
        "North Central": (32.78, -96.80, "Dallas–Fort Worth"), "South Central": (30.27, -97.74, "Austin"),
        "Southern": (27.80, -97.40, "Corpus Christi"), "West": (32.45, -99.73, "Abilene")}},
    "PJM": {"label": "PJM — Mid-Atlantic/Midwest", "center": (39.6, -80.0), "scale": 3.1, "zones": {
        "ComEd": (41.85, -87.65, "Chicago"), "AEP": (39.96, -83.00, "Columbus"),
        "DEOK": (39.10, -84.51, "Cincinnati"), "Duquesne": (40.44, -79.99, "Pittsburgh"),
        "BGE": (39.29, -76.61, "Baltimore"), "PECO": (39.95, -75.16, "Philadelphia"),
        "Dominion": (37.54, -77.43, "Richmond"), "PSEG": (40.73, -74.17, "Newark")}},
    "CAISO": {"label": "CAISO — California", "center": (36.8, -119.6), "scale": 3.3, "zones": {
        "NP15 (Bay Area)": (37.77, -122.42, "San Francisco"), "Sacramento": (38.58, -121.49, "Sacramento"),
        "ZP26 (Central)": (36.74, -119.77, "Fresno"), "SP15 (LA)": (34.05, -118.24, "Los Angeles"),
        "San Diego": (32.72, -117.16, "San Diego"), "Bakersfield": (35.37, -119.02, "Bakersfield")}},
    "SPP": {"label": "SPP — Central Plains", "center": (39.5, -97.5), "scale": 2.5, "zones": {
        "Oklahoma City": (35.47, -97.52, "Oklahoma City"), "Tulsa": (36.15, -95.99, "Tulsa"),
        "Wichita": (37.69, -97.34, "Wichita"), "Kansas City": (39.10, -94.58, "Kansas City"),
        "Omaha": (41.26, -95.93, "Omaha"), "Amarillo": (35.22, -101.83, "Amarillo"),
        "Sioux Falls": (43.55, -96.70, "Sioux Falls"), "Fargo": (46.88, -96.79, "Fargo")}},
    "MISO": {"label": "MISO — Midwest/South", "center": (40.0, -89.5), "scale": 2.3, "zones": {
        "Minnesota": (44.98, -93.27, "Minneapolis"), "Iowa": (41.59, -93.62, "Des Moines"),
        "Indiana": (39.77, -86.16, "Indianapolis"), "Missouri": (38.63, -90.20, "St. Louis"),
        "Michigan": (42.33, -83.05, "Detroit"), "Wisconsin": (43.04, -87.91, "Milwaukee"),
        "Arkansas": (34.75, -92.29, "Little Rock"), "Louisiana": (29.95, -90.07, "New Orleans")}},
    "USA": {"label": "USA — national overview", "center": (39.5, -98.0), "scale": 1.0, "zones": {
        "West": (37.5, -120.5, "California"), "Mountain": (39.7, -105.0, "Denver"),
        "South Central": (31.5, -97.5, "Texas"), "Midwest": (42.0, -89.0, "Chicago"),
        "Southeast": (33.7, -84.4, "Atlanta"), "Northeast": (41.5, -74.5, "New York")}},
}

# label -> lookback in days (0 == absolute current temperature)
LOOKBACKS: dict[str, int] = {
    "Now (absolute)": 0, "vs Yesterday": 1, "vs 2 days ago": 2, "vs 1 week ago": 7,
    "vs 2 weeks ago": 14, "vs 1 month ago": 30, "vs 1 quarter ago": 91, "vs 1 year ago": 365,
}


def _parse(payload, zones: dict) -> pd.DataFrame:
    """Open-Meteo response -> long [time(UTC), zone, lat, lon, city, temp]."""
    if isinstance(payload, dict):
        payload = [payload]
    frames = []
    for (zone, (lat, lon, city)), loc in zip(zones.items(), payload):
        h = loc["hourly"]
        df = pd.DataFrame({"time": pd.to_datetime(h["time"]), "temp": h["temperature_2m"]})
        df["zone"], df["lat"], df["lon"], df["city"] = zone, lat, lon, city
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["time"] = out["time"].dt.tz_localize("UTC")
    return out


def _coords(zones: dict) -> dict[str, str]:
    return {
        "latitude": ",".join(str(v[0]) for v in zones.values()),
        "longitude": ",".join(str(v[1]) for v in zones.values()),
    }


def fetch_forecast(zones: dict, past_days: int, forecast_days: int = 1,
                   om_unit: str = "fahrenheit") -> pd.DataFrame:
    params = {**_coords(zones), "hourly": "temperature_2m", "temperature_unit": om_unit,
              "timezone": "GMT", "past_days": past_days, "forecast_days": forecast_days}
    r = requests.get(FORECAST_URL, params=params, timeout=40)
    r.raise_for_status()
    return _parse(r.json(), zones)


def fetch_archive(zones: dict, start_date: str, end_date: str,
                  om_unit: str = "fahrenheit") -> pd.DataFrame:
    params = {**_coords(zones), "hourly": "temperature_2m", "temperature_unit": om_unit,
              "timezone": "GMT", "start_date": start_date, "end_date": end_date}
    r = requests.get(ARCHIVE_URL, params=params, timeout=40)
    r.raise_for_status()
    return _parse(r.json(), zones)


def _value_at(series: pd.DataFrame, t: pd.Timestamp) -> dict[str, float]:
    """Temperature nearest to time `t` for each zone."""
    out: dict[str, float] = {}
    for zone, g in series.groupby("zone"):
        g = g.dropna(subset=["temp"]).set_index("time").sort_index()
        if g.empty:
            out[zone] = float("nan")
            continue
        pos = g.index.get_indexer([t], method="nearest")[0]
        out[zone] = float(g["temp"].iloc[pos])
    return out


def _fetch_points(url: str, lats: list[float], lons: list[float], extra: dict,
                  retries: int = 2, timeout: int = 35) -> list[dict]:
    # One quick retry for a transient blip, but a SHORT timeout so a slow/flaky archive fails fast
    # (worst case ≈ 2×35 s + 1 s, not 3×90 s) instead of hanging the page.
    params = {"latitude": ",".join(f"{x:.4f}" for x in lats),
              "longitude": ",".join(f"{x:.4f}" for x in lons),
              "hourly": "temperature_2m", "timezone": "GMT", **extra}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            payload = r.json()
            return payload if isinstance(payload, list) else [payload]
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last = exc  # transient (archive slow / connection dropped) — short back-off and retry once
            time.sleep(1.0)
    raise last  # HTTP errors (429/5xx) are NOT retried here — they propagate to the caller



def _temps_at(locs: list[dict], t: pd.Timestamp) -> list[float]:
    """Temperature nearest time `t` for each location (locations share a time axis)."""
    times = pd.DatetimeIndex(pd.to_datetime(locs[0]["hourly"]["time"])).tz_localize("UTC")
    idx = int(times.get_indexer([t], method="nearest")[0])
    return [loc["hourly"]["temperature_2m"][idx] for loc in locs]


def _to_float(values: list) -> list[float]:
    return [float(x) if x is not None else float("nan") for x in values]


def points_now(lats: list[float], lons: list[float], unit: str = "°F",
               model: str = FORECAST_MODEL) -> tuple[list[float], pd.Timestamp]:
    """Current temperature per point from the chosen forecast model."""
    om = "fahrenheit" if unit == "°F" else "celsius"
    now = pd.Timestamp.now(tz="UTC").floor("h")
    out: list[float] = []
    for i in range(0, len(lats), 250):
        fc = _fetch_points(FORECAST_URL, lats[i:i + 250], lons[i:i + 250],
                           {"temperature_unit": om, "past_days": 2, "forecast_days": 1,
                            "models": model})
        out += _temps_at(fc, now)
    return _to_float(out), now


def points_ensemble_std(lats: list[float], lons: list[float], unit: str = "°F",
                        model: str = ENSEMBLE_MODEL) -> tuple[list[float], pd.Timestamp]:
    """Forecast spread (± = std across ensemble members) for the current hour, per point."""
    om = "fahrenheit" if unit == "°F" else "celsius"
    now = pd.Timestamp.now(tz="UTC").floor("h")
    out: list[float] = []
    for i in range(0, len(lats), 100):  # ensemble payloads are larger; smaller chunks
        r = _fetch_points(ENSEMBLE_URL, lats[i:i + 100], lons[i:i + 100],
                          {"temperature_unit": om, "past_days": 1, "forecast_days": 1, "models": model})
        times = pd.DatetimeIndex(pd.to_datetime(r[0]["hourly"]["time"])).tz_localize("UTC")
        idx = int(times.get_indexer([now], method="nearest")[0])
        for loc in r:
            h = loc["hourly"]
            members = [h[k][idx] for k in h if k.startswith("temperature_2m_member")]
            vals = [float(x) for x in members if x is not None]
            out.append(float(np.std(vals)) if vals else float("nan"))
    return out, now


def points_at_lookback(lats: list[float], lons: list[float], lookback_days: int,
                       unit: str = "°F", model: str = FORECAST_MODEL) -> tuple[list[float], pd.Timestamp]:
    """Temperature per point at `now - lookback_days`.

    Cost is independent of how far back: recent (<=2 d) from a tiny forecast window,
    older from a 2-day ERA5 archive window.
    """
    om = "fahrenheit" if unit == "°F" else "celsius"
    past = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(days=lookback_days)
    out: list[float] = []
    for i in range(0, len(lats), 250):
        la, lo = lats[i:i + 250], lons[i:i + 250]
        if lookback_days <= 2:
            fc = _fetch_points(FORECAST_URL, la, lo,
                               {"temperature_unit": om, "past_days": lookback_days + 1,
                                "forecast_days": 1, "models": model})
            out += _temps_at(fc, past)
        else:
            start = (past - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            end = (past + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            arc = _fetch_points(ARCHIVE_URL, la, lo, {"temperature_unit": om, "start_date": start, "end_date": end})
            out += _temps_at(arc, past)
    return _to_float(out), past


MARKET_MEAN = "Market mean"


def _col(loc: dict, key: str, n: int) -> list[float]:
    a = loc["hourly"].get(key)
    return [np.nan if v is None else float(v) for v in a] if a else [np.nan] * n


def forecast_by_zone(zones: dict, unit: str = "°F", forecast_days: int = 7):
    """All-model forecast + GFS ensemble band, per zone (and a 'Market mean').

    Returns (models_by_scope, band_by_scope): dicts keyed by zone name (plus
    'Market mean'); each value is a UTC-indexed DataFrame — models (time x model id)
    or band (time x p10/p50/p90).
    """
    om = "fahrenheit" if unit == "°F" else "celsius"
    lats = [v[0] for v in zones.values()]
    lons = [v[1] for v in zones.values()]
    models = list(FORECAST_MODELS)

    fr = _fetch_points(FORECAST_URL, lats, lons,
                       {"temperature_unit": om, "forecast_days": forecast_days, "models": ",".join(models)})
    ft = pd.DatetimeIndex(pd.to_datetime(fr[0]["hourly"]["time"])).tz_localize("UTC")
    er = _fetch_points(ENSEMBLE_URL, lats, lons,
                       {"temperature_unit": om, "forecast_days": forecast_days, "models": ENSEMBLE_MODEL})
    et = pd.DatetimeIndex(pd.to_datetime(er[0]["hourly"]["time"])).tz_localize("UTC")
    member_keys = [k for k in er[0]["hourly"] if k.startswith("temperature_2m_member")]

    with warnings.catch_warnings():  # HRRR/empty slices -> all-NaN nanmean/nanpercentile
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mbz: dict[str, pd.DataFrame] = {}
        for (zone, _), loc in zip(zones.items(), fr):
            mbz[zone] = pd.DataFrame({m: _col(loc, f"temperature_2m_{m}", len(ft)) for m in models}, index=ft)
        stacked = np.array([df.to_numpy(dtype=float) for df in mbz.values()])  # (zones, time, model)
        mbz[MARKET_MEAN] = pd.DataFrame(np.nanmean(stacked, axis=0), index=ft, columns=models)

        bbz: dict[str, pd.DataFrame] = {}
        member_mats = []
        for (zone, _), loc in zip(zones.items(), er):
            mat = np.array([_col(loc, mk, len(et)) for mk in member_keys], dtype=float)  # (members, time)
            member_mats.append(mat)
            bbz[zone] = pd.DataFrame({"p10": np.nanpercentile(mat, 10, axis=0),
                                      "p50": np.nanpercentile(mat, 50, axis=0),
                                      "p90": np.nanpercentile(mat, 90, axis=0)}, index=et)
        mkt = np.nanmean(np.array(member_mats), axis=0)  # (members, time) averaged over zones
        bbz[MARKET_MEAN] = pd.DataFrame({"p10": np.nanpercentile(mkt, 10, axis=0),
                                         "p50": np.nanpercentile(mkt, 50, axis=0),
                                         "p90": np.nanpercentile(mkt, 90, axis=0)}, index=et)
    return mbz, bbz


def historical_forecast_by_zone(zones: dict, unit: str, start_date: str, end_date: str):
    """All-model *archived past forecast* per zone (+ 'Market mean') for a past window.

    Uses Open-Meteo's Historical Forecast API — i.e. what each model actually predicted on
    those past dates (not ERA5 reanalysis). Returns a {scope: DataFrame(time x model)} dict.
    """
    om = "fahrenheit" if unit == "°F" else "celsius"
    lats = [v[0] for v in zones.values()]
    lons = [v[1] for v in zones.values()]
    models = list(FORECAST_MODELS)
    r = _fetch_points(HISTORICAL_FORECAST_URL, lats, lons,
                      {"temperature_unit": om, "start_date": start_date, "end_date": end_date,
                       "models": ",".join(models)})
    times = pd.DatetimeIndex(pd.to_datetime(r[0]["hourly"]["time"])).tz_localize("UTC")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mbz: dict[str, pd.DataFrame] = {}
        for (zone, _), loc in zip(zones.items(), r):
            mbz[zone] = pd.DataFrame({m: _col(loc, f"temperature_2m_{m}", len(times)) for m in models}, index=times)
        stacked = np.array([df.to_numpy(dtype=float) for df in mbz.values()])
        mbz[MARKET_MEAN] = pd.DataFrame(np.nanmean(stacked, axis=0), index=times, columns=models)
    return mbz


CLIMATOLOGY_YEARS = 10


def points_climatology(lats: list[float], lons: list[float], unit: str = "°F",
                       n_years: int = CLIMATOLOGY_YEARS) -> tuple[list[float], list[float], list[int]]:
    """ERA5 climatology for *this* calendar date & hour across the last `n_years`.

    For each past year it pulls ERA5 (archive API) for the same month/day/hour and
    returns the per-point mean and **inter-annual std** (the climatological ±) plus the
    years actually used. Years that fail (e.g. transient rate limit) are skipped.
    """
    om = "fahrenheit" if unit == "°F" else "celsius"
    now = pd.Timestamp.now(tz="UTC").floor("h")
    per_year: list[list[float]] = []
    used: list[int] = []
    for y in range(now.year - n_years, now.year):
        try:
            target = pd.Timestamp(year=y, month=now.month, day=now.day, hour=now.hour, tz="UTC")
        except ValueError:  # e.g. Feb 29 in a non-leap year
            target = pd.Timestamp(year=y, month=now.month, day=28, hour=now.hour, tz="UTC")
        start = (target - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        end = (target + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            vals: list[float] = []
            for i in range(0, len(lats), 250):
                arc = _fetch_points(ARCHIVE_URL, lats[i:i + 250], lons[i:i + 250],
                                    {"temperature_unit": om, "start_date": start, "end_date": end})
                vals += _temps_at(arc, target)
            per_year.append(_to_float(vals))
            used.append(y)
        except requests.RequestException:
            continue
    if not per_year:
        raise RuntimeError("Could not fetch any ERA5 climatology years (rate limit?).")
    arr = np.array(per_year, dtype=float)  # (years, points)
    return np.nanmean(arr, axis=0).tolist(), np.nanstd(arr, axis=0).tolist(), used


def market_temperature(market: str, lookback_days: int, unit: str = "°F") -> tuple[pd.DataFrame, dict]:
    """Per-zone temperature (absolute if lookback_days==0, else now − past difference).

    Returns (frame, meta). frame columns: zone, lat, lon, city, now, past, diff, value
    where `value` is what the map colours by (temp for absolute, diff otherwise).
    """
    cfg = MARKETS[market]
    zones = cfg["zones"]
    om_unit = "fahrenheit" if unit == "°F" else "celsius"
    now = pd.Timestamp.now(tz="UTC").floor("h")

    if lookback_days == 0:
        cur = _value_at(fetch_forecast(zones, past_days=1, om_unit=om_unit), now)
        rows = [{"zone": z, "lat": la, "lon": lo, "city": c,
                 "now": cur.get(z), "past": None, "diff": None, "value": cur.get(z)}
                for z, (la, lo, c) in zones.items()]
        meta = {"mode": "absolute", "now": now, "past": None}
    else:
        past = now - pd.Timedelta(days=lookback_days)
        if lookback_days <= 90:
            s = fetch_forecast(zones, past_days=min(lookback_days + 2, 92), om_unit=om_unit)
            now_v, past_v = _value_at(s, now), _value_at(s, past)
        else:  # one year -> ERA5 archive for the reference day, forecast for "now"
            now_v = _value_at(fetch_forecast(zones, past_days=2, om_unit=om_unit), now)
            start = (past - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            end = (past + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            past_v = _value_at(fetch_archive(zones, start, end, om_unit=om_unit), past)
        rows = []
        for z, (la, lo, c) in zones.items():
            nv, pv = now_v.get(z), past_v.get(z)
            d = (nv - pv) if (nv == nv and pv == pv) else None  # NaN-safe
            rows.append({"zone": z, "lat": la, "lon": lo, "city": c,
                         "now": nv, "past": pv, "diff": d, "value": d})
        meta = {"mode": "diff", "now": now, "past": past}

    meta.update(unit=unit, label=cfg["label"], center=cfg["center"], scale=cfg["scale"])
    return pd.DataFrame(rows), meta
