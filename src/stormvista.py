"""StormVista (SVWX) weather-model API client — weighted degree days for ERCOT.

StormVista (https://www.stormvistawxmodels.com) is a paid weather/energy vendor. Its data
host serves CSV files under a `model-data/` tree, authenticated with `?apikey=`:

    https://api.stormvistawxmodels.com/model-data/[model]/[YYYYMMDD]/[cycle]z/wdd/[file].csv?apikey=KEY

(The `model-data/` prefix is the base path; the subscriber docs only show the relative tail.)

We use it for **weighted degree days (WDD)** — temperature collapsed into a demand-relevant
index, population-weighted (`pw`, the standard electricity-load proxy) for the ISO regions,
which include `ercot` (and `ercotnorth/south/west`). This is the NG-demand "language" that
complements the raw Open-Meteo temperature map. See docs/data-sources.md §8.

Setup (.env, gitignored):
    STORMVISTA_API_KEY=...                 # data API (this client)
    STORMVISTA_USER=... STORMVISTA_PASSWORD=...   # only for the gated web docs

File anatomy (one CSV each, Date in the first column):
  - ISO/region forecast: wdd/[weight]_[kind]_regiso.csv      -> columns are regions (ercot, pjm, ...)
  - ensemble members:    wdd/[weight]_[kind]_regiso_members.csv (adds a 'Member' column)
  - 7-day actuals:       history/wdd/[weight]_[kind]_regiso.csv
  - climatology normal:  history/wdd/climo/[weight]_[kind]_regiso_climo[10|30]yr.csv (MM-DD index)
  - national daily:      wdd/[type]-daily.csv with columns Date,Value,Flag(0=obs 1=fcst 2=norm)
"""
from __future__ import annotations

import datetime as _dt
import io
import os
import re
from dataclasses import dataclass

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import PROJECT_ROOT

BASE_URL = "https://api.stormvistawxmodels.com/model-data"
CACHE_DIR = PROJECT_ROOT / "data" / "stormvista"

# Deterministic models carry a single forecast; ensemble models add per-member files.
DETERMINISTIC = ("gfs", "ecmwf", "cmc", "icon-global")
ENSEMBLE = ("gfs-ens", "ecmwf-eps", "cmc-ens", "gfs-ens-bc")
# Medium-range cycles, newest-first, used to discover the latest available run.
CYCLES = ("18", "12", "06", "00")


def credentials() -> str:
    """Return the StormVista API key from .env, or raise a clear message if missing."""
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("STORMVISTA_API_KEY", "")
    if not key:
        raise RuntimeError(
            "STORMVISTA_API_KEY not set. Add it to .env (subscriber key from the /api page)."
        )
    return key


def is_configured() -> bool:
    try:
        credentials()
        return True
    except RuntimeError:
        return False


# --- low-level fetch -----------------------------------------------------------------------
def _fetch(relpath: str, *, cache: bool = True) -> str:
    """GET one CSV under model-data/. Run-specific files are immutable, so we cache them
    on disk; pass cache=False for the rolling history feed. Raises on HTTP/auth errors."""
    cache_file = CACHE_DIR / relpath
    if cache and cache_file.exists():
        return cache_file.read_text()
    resp = requests.get(f"{BASE_URL}/{relpath}", params={"apikey": credentials()}, timeout=60)
    resp.raise_for_status()
    text = resp.text
    # Validate BEFORE writing to disk so an HTTP-200 error page can't poison the cache. SVWX error
    # bodies are HTML ("<!DOCTYPE…"); real data is CSV (header has a comma, e.g. "Date,…" or
    # "station,…"). Reject anything that looks like HTML or isn't comma-delimited.
    first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    if first_line.startswith("<") or "," not in first_line:
        raise RuntimeError(f"Unexpected (non-CSV) response for {relpath}: {text[:120]!r}")
    if cache:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text)
    return text


def _read_regiso(text: str, *, date_col: str = "Date") -> pd.DataFrame:
    """Parse a region CSV into a frame indexed by date with one float column per region."""
    df = pd.read_csv(io.StringIO(text))
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df.set_index(date_col).apply(pd.to_numeric, errors="coerce").sort_index()


def prune_cache(max_age_days: int = 14) -> int:
    """Delete cached *run* files older than `max_age_days` to bound disk growth — run files are
    keyed by date and never re-read once superseded. Undated files (meta/, history/, climo/) are
    kept. Returns the number of files removed. Safe to call on a schedule / once per day."""
    if not CACHE_DIR.exists():
        return 0
    cutoff = _dt.datetime.now(_dt.timezone.utc).date() - _dt.timedelta(days=max_age_days)
    removed = 0
    for f in CACHE_DIR.rglob("*.csv"):
        m = re.search(r"/(\d{8})/", f.as_posix())  # the YYYYMMDD run-date path segment
        if not m:
            continue
        try:
            run_date = _dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if run_date < cutoff:
            f.unlink()
            removed += 1
    return removed


# --- run discovery -------------------------------------------------------------------------
def latest_run(model: str = "gfs", *, probe: str | None = None, weight: str = "pw",
               kind: str = "cdd", search_days: int = 2) -> tuple[str, str]:
    """Find the newest (YYYYMMDD, cycle) for which `probe` exists for this model. Probes a
    sentinel file backwards from today (UTC) — the host has no listing endpoint. `probe` is the
    run-relative path (default the ISO regional file built from weight/kind)."""
    probe = probe or f"wdd/{weight}_{kind}_regiso.csv"
    today = _dt.datetime.now(_dt.timezone.utc).date()
    for back in range(search_days + 1):
        day = (today - _dt.timedelta(days=back)).strftime("%Y%m%d")
        for cyc in CYCLES:
            resp = requests.get(f"{BASE_URL}/{model}/{day}/{cyc}z/{probe}",
                                params={"apikey": credentials()}, timeout=30)
            if resp.status_code == 200 and not resp.text.lstrip().startswith("<"):
                return day, cyc
    raise RuntimeError(f"No {model} run with {probe} found in the last {search_days} days.")


# --- public products -----------------------------------------------------------------------
def regional_wdd(model: str, date: str, cycle: str, *, kind: str = "cdd", weight: str = "pw",
                 raw: bool = False, bias_corrected: bool = False) -> pd.DataFrame:
    """ISO/region weighted degree days for one run. Returns a date-indexed frame whose columns
    are regions (incl. 'ercot'). kind ∈ {cdd,hdd}; weight ∈ {pw,ew,gw}."""
    suffix = "-raw" if raw else ("-bc" if bias_corrected else "")
    rel = f"{model}/{date}/{cycle}z/wdd/{weight}_{kind}_regiso{suffix}.csv"
    return _read_regiso(_fetch(rel))


def ercot_wdd(*, model: str = "gfs", date: str | None = None, cycle: str | None = None,
              kind: str = "cdd", weight: str = "pw") -> pd.Series:
    """Convenience: the ERCOT column of the regional WDD forecast (auto-resolves latest run)."""
    if date is None or cycle is None:
        date, cycle = latest_run(model, weight=weight, kind=kind)
    frame = regional_wdd(model, date, cycle, kind=kind, weight=weight)
    return frame["ercot"].rename(f"ercot_{weight}_{kind}")


def ercot_members(model: str = "gfs-ens", date: str | None = None, cycle: str | None = None, *,
                  kind: str = "cdd", weight: str = "pw") -> pd.DataFrame:
    """Per-member ERCOT WDD for an ensemble model → date-indexed frame, one column per member
    (basis for p10/p50/p90). Requires an ensemble model (gfs-ens, ecmwf-eps, ...)."""
    if date is None or cycle is None:
        date, cycle = latest_run(model, weight=weight, kind=kind)
    rel = f"{model}/{date}/{cycle}z/wdd/{weight}_{kind}_regiso_members.csv"
    df = pd.read_csv(io.StringIO(_fetch(rel)))
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    wide = df.pivot_table(index="Date", columns="Member", values="ercot")
    wide.columns = [f"m{int(c):02d}" if str(c).isdigit() else str(c) for c in wide.columns]
    return wide.sort_index()


def history(kind: str = "cdd", *, weight: str = "pw") -> pd.DataFrame:
    """Recent (~7 day) *observed* ISO WDD — the actuals to compare a forecast against.
    Not cached (it rolls forward daily)."""
    return _read_regiso(_fetch(f"history/wdd/{weight}_{kind}_regiso.csv", cache=False))


def climatology(kind: str = "cdd", *, weight: str = "pw", period: int = 30) -> pd.DataFrame:
    """The `period`-yr normal ISO WDD, indexed by 'MM-DD' day-of-year — the anomaly reference
    (anomaly = forecast − normal). period ∈ {10, 30}. Cached: the multi-year normal is static."""
    text = _fetch(f"history/wdd/climo/{weight}_{kind}_regiso_climo{period}yr.csv")
    df = pd.read_csv(io.StringIO(text))
    return df.set_index(df.columns[0]).apply(pd.to_numeric, errors="coerce")


# --- US-national products (single series; gas-weighted HDD = the Henry-Hub demand driver) ----
def national_wdd(weight: str, kind: str, *, model: str = "gfs", date: str | None = None,
                 cycle: str | None = None) -> pd.DataFrame:
    """US-national weighted degree days. The daily file carries obs + forecast + normal together,
    tagged by a flag — returns a date-indexed frame with columns 'value' (°-days) and
    'flag' (0=obs, 1=fcst, 2=norm). Nationally StormVista publishes the dominant pairing per
    weighting: gw_hdd (gas → winter heating / Henry Hub), pw_cdd & ew_cdd (cooling → power)."""
    if date is None or cycle is None:
        date, cycle = latest_run(model, probe=f"wdd/{weight}_{kind}-daily.csv")
    df = pd.read_csv(io.StringIO(_fetch(f"{model}/{date}/{cycle}z/wdd/{weight}_{kind}-daily.csv")))
    if df.shape[1] != 3:  # guard against a schema change silently mangling the columns
        raise RuntimeError(f"national_wdd expected 3 columns, got {list(df.columns)}")
    df.columns = ["date", "value", "flag"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    out = df.set_index("date")
    out.attrs.update(model=model, date=date, cycle=cycle, weight=weight, kind=kind)
    return out


def national_climo(weight: str, kind: str, *, period: int = 30) -> pd.Series:
    """`period`-yr national normal, indexed by 'MM-DD' — the anomaly reference for national_wdd.
    Cached: the multi-year normal is static."""
    text = _fetch(f"history/wdd/climo/{weight}_{kind}_climo{period}yr.csv")
    df = pd.read_csv(io.StringIO(text))
    return pd.to_numeric(df.set_index(df.columns[0])[df.columns[1]], errors="coerce")


# --- absolute temperature (city-extraction) — the raw °F behind the degree days ----------------
# The ISO degree days come from these station temperatures weighted by load; this exposes the
# underlying absolute weather. ERCOT temp = its load-weighted station temps (meta weights file).
_CITY_REGION = "northamerica"  # the city-extraction continent containing the ERCOT stations


def station_meta(region: str = "northamerica") -> pd.DataFrame:
    """Station metadata for a city-extraction region: columns Station, Region, Latitude, Longitude,
    Name, Elevation, … — the coordinates that let us map stations to counties for a choropleth."""
    return pd.read_csv(io.StringIO(_fetch(f"meta/station-list-{region}.csv")))


def station_normals(region: str = "northamerica") -> pd.DataFrame:
    """30-yr ERA5 daily normal high/low per station: columns Station, Date ('MM-DD'), tmin, tmax.
    The reference for temperature anomalies (forecast − normal)."""
    return pd.read_csv(io.StringIO(_fetch(f"meta/city-extraction-normals-ERA5-30yr-{region}.csv")))


def region_daily_temps(region: str = "northamerica", model: str = "gfs", date: str | None = None,
                       cycle: str | None = None, corrected: bool = True) -> pd.DataFrame:
    """Daily high/low (°F) for **every station** in a region → tidy long frame
    [station, date, tmax, tmin], from the city-extraction max/min file. `corrected` = SV
    grid-corrected (recommended). The grid behind a StormVista-sourced temperature map."""
    fname = "corrected-max-min" if corrected else "max-min"
    probe = f"city-extraction/{fname}_{region}.csv"
    if date is None or cycle is None:
        date, cycle = latest_run(model, probe=probe)
    raw = pd.read_csv(io.StringIO(_fetch(f"{model}/{date}/{cycle}z/{probe}"))).set_index("station")
    parts = []
    for d in sorted({c.split(".")[0] for c in raw.columns}):  # each date appears twice (high, low)
        hi = pd.to_numeric(raw[d], errors="coerce")
        lo = pd.to_numeric(raw[f"{d}.1"], errors="coerce") if f"{d}.1" in raw.columns else hi
        pair = pd.concat([hi, lo], axis=1)
        parts.append(pd.DataFrame({"station": raw.index, "date": d,
                                   "tmax": pair.max(axis=1).values, "tmin": pair.min(axis=1).values}))
    out = pd.concat(parts, ignore_index=True)
    out.attrs.update(model=model, date=date, cycle=cycle)
    return out


def ercot_station_weights() -> pd.Series:
    """The 6 ERCOT stations and their load weights (e.g. KDFW 0.35, KIAH 0.34), normalized to 1."""
    df = pd.read_csv(io.StringIO(_fetch("meta/ercot_wdd_weights.csv")), header=None,
                     names=["station", "weight"])
    w = df.set_index("station")["weight"].astype(float)
    return w / w.sum()


def ercot_temperature(model: str = "gfs", date: str | None = None, cycle: str | None = None, *,
                      corrected: bool = True) -> pd.DataFrame:
    """Load-weighted **absolute** ERCOT daily temperature (°F) — the raw weather behind the degree
    days. Pulls the city-extraction station max/min and weights the ERCOT stations by their load
    weights. Returns a date-indexed frame: 'tmax', 'tmin', 'tavg'. `corrected` = SV grid-corrected
    extraction (recommended over raw)."""
    probe = f"city-extraction/{'corrected-max-min' if corrected else 'max-min'}_{_CITY_REGION}.csv"
    if date is None or cycle is None:
        date, cycle = latest_run(model, probe=probe)
    raw = pd.read_csv(io.StringIO(_fetch(f"{model}/{date}/{cycle}z/{probe}")))
    w = ercot_station_weights()
    df = raw[raw["station"].isin(w.index)].set_index("station")
    w = (w.reindex(df.index)).pipe(lambda s: s / s.sum())  # renormalize over present stations
    # the header repeats each date twice (the daily high & low) → pandas suffixes the 2nd with
    # ".1". Order isn't guaranteed, so take max/min of the two weighted values.
    out: dict = {}
    for d in sorted({c.split(".")[0] for c in df.columns}):
        v1 = (pd.to_numeric(df[d], errors="coerce") * w).sum()
        v2 = (pd.to_numeric(df[f"{d}.1"], errors="coerce") * w).sum() if f"{d}.1" in df.columns \
            else v1
        out[pd.Timestamp(d)] = (max(v1, v2), min(v1, v2))
    res = pd.DataFrame(out, index=["tmax", "tmin"]).T.sort_index()
    res["tavg"] = (res["tmax"] + res["tmin"]) / 2
    res.attrs.update(model=model, date=date, cycle=cycle, corrected=corrected)
    return res


# Friendly names for the ERCOT load-weighting stations.
ERCOT_STATION_CITY = {"KIAH": "Houston", "KDFW": "Dallas", "KSAT": "San Antonio",
                      "KAUS": "Austin", "KBRO": "Brownsville", "KCRP": "Corpus Christi"}


def station_temps_subdaily(stations, model: str = "gfs", date: str | None = None,
                           cycle: str | None = None, *, var: str = "tmp2m") -> pd.DataFrame:
    """Sub-daily (3-hourly) temperature (°F) for **arbitrary** stations — one column per station,
    valid-time-indexed (UTC). var ∈ {tmp2m, heatindex, dpt2m, windchill, …}. The general per-station
    pull behind both the ERCOT load-weighted and the zonal temperature aggregates."""
    if date is None or cycle is None:
        date, cycle = latest_run(model, probe="city-extraction/individual/KIAH_raw.csv")
    init = pd.Timestamp(f"{date[:4]}-{date[4:6]}-{date[6:]} {cycle}:00", tz="UTC")
    cols: dict = {}
    for stn in stations:
        df = pd.read_csv(io.StringIO(_fetch(f"{model}/{date}/{cycle}z/city-extraction/"
                                            f"individual/{stn}_raw.csv")))
        df = df.set_index(df.columns[0])  # first column = forecast hour (0, 3, 6, …)
        if var in df.columns:
            cols[stn] = pd.to_numeric(df[var], errors="coerce")
    mat = pd.DataFrame(cols)
    mat.index = init + pd.to_timedelta(mat.index.astype(int), unit="h")  # forecast hour → valid time
    mat.attrs.update(model=model, date=date, cycle=cycle, var=var)
    return mat


def ercot_station_temps_hourly(model: str = "gfs", date: str | None = None,
                               cycle: str | None = None, *, var: str = "tmp2m") -> pd.DataFrame:
    """Per-station ERCOT **sub-daily** (3-hourly) temperature (°F) — one column per ERCOT
    load-weighting station (KIAH, KDFW, …) plus a 'load-weighted' column. The intraday curve shows
    the diurnal cycle (afternoon peaks / pre-dawn troughs) that daily max/min and degree days hide."""
    if date is None or cycle is None:
        date, cycle = latest_run(model, probe="city-extraction/individual/KIAH_raw.csv")
    w = ercot_station_weights()
    mat = station_temps_subdaily(list(w.index), model, date, cycle, var=var)
    wv = w.reindex(mat.columns).pipe(lambda s: s / s.sum())
    mat["load-weighted"] = (mat[wv.index] * wv).sum(axis=1)
    mat.attrs.update(model=model, date=date, cycle=cycle, var=var)
    return mat


def ercot_temperature_hourly(model: str = "gfs", date: str | None = None,
                             cycle: str | None = None, *, var: str = "tmp2m") -> pd.Series:
    """Load-weighted ERCOT sub-daily (3-hourly) temperature (°F) — the 'load-weighted' column of
    ercot_station_temps_hourly()."""
    col = ercot_station_temps_hourly(model, date, cycle, var=var)["load-weighted"]
    return col.rename(f"ercot_{var}")


@dataclass(frozen=True)
class WddBundle:
    """One coherent ERCOT degree-day picture for a single kind (cdd OR hdd), all date-indexed.
    `kind` distinguishes cooling (summer/AC) from heating (winter); the panel keeps both."""
    model: str
    date: str
    cycle: str
    kind: str                # 'cdd' (cooling) | 'hdd' (heating)
    forecast: pd.Series      # deterministic forecast
    members: pd.DataFrame    # ensemble members (empty if unavailable) → p10/p50/p90
    actual: pd.Series        # recent observed
    normal: pd.Series        # `period`-yr normal aligned to the forecast dates (anomaly reference)
    members_run: tuple[str, str] | None  # (date, cycle) the band came from — may lag the forecast


def ercot_bundle(kind: str = "cdd", *, det_model: str = "gfs", ens_model: str = "gfs-ens",
                 period: int = 30) -> WddBundle:
    """Assemble the full ERCOT picture for one degree-day kind (forecast + ensemble members +
    recent actuals + climatology normal) for the latest available run. kind ∈ {cdd, hdd}."""
    date, cycle = latest_run(det_model, kind=kind)
    forecast = ercot_wdd(model=det_model, date=date, cycle=cycle, kind=kind)
    if forecast.empty:  # a 0-row CSV is a valid HTTP 200; downstream .iloc[0] would crash
        raise RuntimeError(f"Empty {kind} forecast for {det_model} run {date}/{cycle}z")
    # resolve the ensemble's OWN latest run (gfs-ens publishes ~1.5 h after gfs, so its newest
    # complete run may be an earlier cycle); using the deterministic date/cycle risks a 404 right
    # after a run → the band would vanish exactly when traders look. We record the band's run so
    # the UI can flag when it lags the forecast.
    members, members_run = pd.DataFrame(), None
    try:
        ens_date, ens_cycle = latest_run(ens_model, kind=kind)
        members = ercot_members(ens_model, date=ens_date, cycle=ens_cycle, kind=kind)
        members_run = (ens_date, ens_cycle)
    except Exception:
        members, members_run = pd.DataFrame(), None
    try:
        actual = history(kind)["ercot"].rename(f"ercot_actual_{kind}")
    except Exception:
        actual = pd.Series(dtype="float64")
    climo = climatology(kind, period=period)
    if "ercot" not in climo.columns:
        raise RuntimeError(f"'ercot' missing from {period}yr {kind} climo: {list(climo.columns)[:8]}")
    # align the MM-DD normal onto the forecast dates → anomaly = forecast − normal
    normal = pd.Series(
        [climo["ercot"].get(d.strftime("%m-%d"), float("nan")) for d in forecast.index],
        index=forecast.index, name=f"ercot_normal_{kind}",
    )
    return WddBundle(det_model, date, cycle, kind, forecast, members, actual, normal, members_run)


if __name__ == "__main__":  # quick smoke test: `python -m src.stormvista`
    for k in ("cdd", "hdd"):
        b = ercot_bundle(k)
        nxt, anom = b.forecast.index[0], b.forecast.iloc[0] - b.normal.iloc[0]
        print(f"ERCOT {k.upper()} — {b.model} {b.date} {b.cycle}z | next {nxt:%m-%d} "
              f"{b.forecast.iloc[0]:.1f} (anom {anom:+.1f}) | members {b.members.shape[1]} "
              f"actual {len(b.actual)} normal {b.normal.notna().sum()}")
