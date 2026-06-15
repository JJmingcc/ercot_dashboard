"""Feb 2021 Winter Storm Uri — counterfactual demand reconstruction.

During Uri (mid-Feb 2021) ERCOT shed ~20 GW of load (rolling blackouts), so the **observed**
demand on Feb 15–18 is *curtailed served-load*, not true demand. This module estimates two
counterfactuals from a weather→demand model fit on **un-curtailed** winter hours:

  1. **Latent demand** — what demand would have been at the storm's *actual* extreme cold, had
     load not been cut (the gap to observed = **unserved load**);
  2. **No-storm demand** — what demand would have been at *normal* February weather.

Source: **EIA-930** ERCOT demand (`region-data`, type D) + **ERA5** temperature (Open-Meteo
archive). Meteologica has no pre-Dec-2021 data, so this is a dedicated EIA path. The model is
`demand ~ a_year + b·HDD + c·HDD² + weekend + hour-of-day`, fit on Dec–Feb of several winters
(growth handled by per-year intercepts; HDD² captures the steepening at extreme cold). The
coldest training hour (~15 °F) sits just above the storm's 12.7 °F, so the latent estimate is a
*near-interpolation*, not a wild extrapolation — but still carry the ±band.

Full write-up: docs/winter-storm-uri-2021.md (summary in docs/concepts.md §8).
"""
from __future__ import annotations

import calendar
import os

import numpy as np
import pandas as pd
import requests

from .config import PROJECT_ROOT
from .weather import MARKETS, fetch_archive

CACHE_DIR = PROJECT_ROOT / "data" / "uri2021"
# Dec–Feb of four winters (incl. the 2021 event months); per-year intercepts absorb growth.
TRAIN_MONTHS = [(2019, 12), (2020, 1), (2020, 2), (2020, 12), (2021, 1), (2021, 2),
                (2021, 12), (2022, 1), (2022, 2), (2022, 12), (2023, 1), (2023, 2)]
EVENT_START, EVENT_END = "2021-02-08", "2021-02-21"           # display window (naive UTC)
CURTAIL_START = pd.Timestamp("2021-02-15")                    # rolling-blackout window — excluded
CURTAIL_END = pd.Timestamp("2021-02-19")                      # from training (curtailed ≠ demand)
BASE_F = 65.0


def _eia_key() -> str:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    return os.environ.get("EIA_API_KEY", "")


def eia_demand_month(year: int, month: int) -> pd.Series:
    """ERCOT hourly demand (GW, naive-UTC) for one month from EIA-930 region-data (type D)."""
    last = calendar.monthrange(year, month)[1]
    r = requests.get("https://api.eia.gov/v2/electricity/rto/region-data/data/",
                     params={"api_key": _eia_key(), "frequency": "hourly", "data[0]": "value",
                             "facets[respondent][]": "ERCO", "facets[type][]": "D",
                             "start": f"{year}-{month:02d}-01T00",
                             "end": f"{year}-{month:02d}-{last:02d}T23", "length": 5000}, timeout=60)
    r.raise_for_status()
    d = r.json()["response"]["data"]
    s = pd.Series({pd.Timestamp(x["period"]): float(x["value"]) for x in d}).sort_index() / 1000.0
    s.index = pd.DatetimeIndex(s.index).tz_localize(None)
    return s


def era5_temp_month(year: int, month: int) -> pd.Series:
    """ERCOT zone-mean hourly temperature (°F, naive-UTC) for one month from ERA5."""
    last = calendar.monthrange(year, month)[1]
    t = fetch_archive(MARKETS["ERCOT"]["zones"], f"{year}-{month:02d}-01",
                      f"{year}-{month:02d}-{last:02d}", "fahrenheit")
    s = t.groupby("time")["temp"].mean()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None)
    return s


def build_cache() -> pd.DataFrame:
    """Pull every training month (EIA demand + ERA5 temp) and cache the combined hourly panel."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    parts = []
    for y, m in TRAIN_MONTHS:
        dem = eia_demand_month(y, m)
        tmp = era5_temp_month(y, m)
        parts.append(pd.concat([dem.rename("demand"), tmp.rename("temp")], axis=1).dropna())
    panel = pd.concat(parts).sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    panel.to_parquet(CACHE_DIR / "panel.parquet")
    return panel


def load_panel() -> pd.DataFrame:
    """Read the cached hourly panel (empty if not built)."""
    p = CACHE_DIR / "panel.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def analyze(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fit the weather→demand model on un-curtailed hours and reconstruct the Feb-2021 event.

    Returns (event_frame, stats). event_frame is hourly over the display window with columns
    temp, observed, latent, no_storm, norm_temp, band(±GW). stats has r2, resid_std, slopes,
    coldest_train, and headline peaks.
    """
    df = panel.copy()
    df["hdd"] = (BASE_F - df["temp"]).clip(lower=0)
    years = sorted(int(y) for y in df.index.year.unique())

    def design(idx: pd.DatetimeIndex, hdd: np.ndarray) -> np.ndarray:
        cols = [np.ones(len(idx)), hdd, hdd ** 2, np.asarray(idx.dayofweek >= 5, dtype=float)]
        cols += [np.asarray(idx.year == yr, dtype=float) for yr in years[1:]]      # 1st year = baseline
        cols += [np.asarray(idx.hour == h, dtype=float) for h in range(1, 24)]     # hour 0 = baseline
        return np.column_stack(cols)

    storm = (df.index >= CURTAIL_START) & (df.index < CURTAIL_END)
    train = df[~storm]
    Xtr, ytr = design(train.index, train["hdd"].to_numpy()), train["demand"].to_numpy()
    coef, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
    resid = ytr - Xtr @ coef
    resid_std = float(resid.std())
    r2 = float(1 - (resid ** 2).sum() / ((ytr - ytr.mean()) ** 2).sum())
    XtX_inv = np.linalg.pinv(Xtr.T @ Xtr)                      # for the prediction interval

    ev = df[(df.index >= pd.Timestamp(EVENT_START)) & (df.index < pd.Timestamp(EVENT_END))].copy()
    Xev = design(ev.index, ev["hdd"].to_numpy())
    latent = Xev @ coef
    # 95% prediction interval — leverage term grows for points far from the training cloud (extreme
    # cold), so the band *widens* exactly where we're extrapolating. The honest confidence statement.
    lev = np.einsum("ij,jk,ik->i", Xev, XtX_inv, Xev)
    se_pred = resid_std * np.sqrt(1.0 + lev)
    band = 2.0 * se_pred

    # "normal" February weather = climatological mean temp by month-day-hour across training winters
    tr_feb = train[train.index.month == 2]
    norm = tr_feb.groupby(tr_feb.index.strftime("%m-%d-%H"))["temp"].mean()
    norm_temp = pd.Index(ev.index.strftime("%m-%d-%H")).map(norm).to_numpy(dtype=float)
    norm_temp = np.where(np.isnan(norm_temp), float(tr_feb["temp"].mean()), norm_temp)
    no_storm = design(ev.index, np.clip(BASE_F - norm_temp, 0, None)) @ coef

    res = pd.DataFrame({"temp": ev["temp"].to_numpy(), "observed": ev["demand"].to_numpy(),
                        "latent": latent, "no_storm": no_storm, "norm_temp": norm_temp,
                        "band": band}, index=ev.index)

    cmask = (res.index >= CURTAIL_START) & (res.index < CURTAIL_END)
    stats = {
        "r2": r2, "resid_std": resid_std, "hdd_slope": float(coef[1]), "hdd_sq": float(coef[2]),
        "coldest_train": float(train["temp"].min()), "n_train": int(len(train)),
        "coldest_event": float(res["temp"].min()),
        "peak_observed": float(res.loc[cmask, "observed"].max()),
        "peak_latent": float(res.loc[cmask, "latent"].max()),
        "max_unserved": float((res["latent"] - res["observed"])[cmask].max()),
        "nostorm_peak": float(res["no_storm"].max()),
    }
    return res, stats


def temp_curve(panel: pd.DataFrame, degree: int = 2):
    """Daily-mean **demand vs temperature** for the analog reference: the training cloud + a fitted
    curve extended into the extrapolated extreme cold. Lets a trader read off expected demand at any
    temperature for a *similar* event. Returns (train_daily[temp,demand], curve[temp,demand,extrapolated])."""
    df = panel.copy()
    storm = (df.index >= CURTAIL_START) & (df.index < CURTAIL_END)
    tr = df[~storm].resample("1D").mean().dropna(subset=["temp", "demand"])
    x, y = tr["temp"].to_numpy(dtype=float), tr["demand"].to_numpy(dtype=float)
    coef = np.polyfit(x, y, degree)
    xmin = float(x.min())
    xs = np.linspace(min(xmin, 5.0), float(x.max()), 140)     # extend down to ~5 °F (Uri-class cold)
    curve = pd.DataFrame({"temp": xs, "demand": np.polyval(coef, xs), "extrapolated": xs < xmin})
    return tr[["temp", "demand"]], curve


if __name__ == "__main__":                                    # one-time cache build
    print("building Uri-2021 cache (EIA + ERA5)…")
    p = build_cache()
    r, s = analyze(p)
    print(f"cached {len(p)} hrs | model R²={s['r2']:.3f} resid±{s['resid_std']:.1f}GW "
          f"coldest train {s['coldest_train']:.0f}°F")
    print(f"peak observed {s['peak_observed']:.0f} → latent {s['peak_latent']:.0f} GW "
          f"(unserved up to {s['max_unserved']:.0f} GW); no-storm peak {s['nostorm_peak']:.0f} GW")
