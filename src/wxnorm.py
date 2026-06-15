"""Weather-normalization analysis for the ERCOT battery-era comparison.

Reads the cached hourly panels (src/historical.py) and produces the two core views:
- response-by-temperature (the weather-response curve — hold weather constant, the gap
  between eras is structural), and
- diurnal profile within a temperature bin (the *shape* change — the battery fingerprint,
  esp. the evening peak). See docs/concepts.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .historical import load_panel

DISPLAY_TZ = "America/Chicago"


def era_panel(year: int, months: tuple[int, ...] = (6, 7, 8)) -> pd.DataFrame:
    """Concatenate cached month panels for a year, add local hour-of-day (CPT)."""
    parts = [p for p in (load_panel(year, m) for m in months) if not p.empty]
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df["hour"] = df.index.tz_convert(DISPLAY_TZ).hour
    return df


def response_by_temp(df: pd.DataFrame, value: str, width: float = 2.0, min_count: int = 5) -> pd.DataFrame:
    """Mean of `value` by temperature bin (°F) → the weather-response curve."""
    binc = (df["temp"] / width).round() * width
    g = df.assign(_bin=binc).groupby("_bin")[value].agg(["mean", "count"])
    return g[g["count"] >= min_count]


_RESAMPLE_RULE = {"daily": "D", "weekly": "W", "monthly": "MS", "yearly": "YS"}


def lt_scatter(df: pd.DataFrame, value: str, resolution: str = "daily",
               tz: str = DISPLAY_TZ, temp_col: str = "temp",
               hours: "set[int] | None" = None) -> pd.DataFrame:
    """Aggregate the hourly UTC panel into (temperature, `value`) points at a time resolution for the
    load-vs-temperature scatter. `temp_col` selects the x-axis temperature column (e.g. 'temp' for
    whole-ERCOT, 'temp_Coast' for a zone). resolution ∈ {hourly, daily, weekly, monthly, yearly};
    each point (except hourly) is the **mean** over that local-time bucket. `hours` (optional) keeps only
    those **local-time** hours-of-day (0–23) *before* aggregating — so e.g. {18,19,20,21,22} makes each
    daily point the *evening-peak* block-mean (trader on/off-peak views). Returns a local-time-indexed
    frame with columns [temp_col, value] (empty if either column is absent)."""
    if df.empty or value not in df.columns or temp_col not in df.columns:
        return pd.DataFrame(columns=[temp_col, value])
    local = df[[temp_col, value]].copy()
    local.index = local.index.tz_convert(tz)
    if hours is not None:                                   # keep only the chosen local hours-of-day
        local = local[local.index.hour.isin(list(hours))]
    if resolution == "hourly":
        return local.dropna()
    rule = _RESAMPLE_RULE.get(resolution)
    if rule is None:
        raise ValueError(f"unknown resolution {resolution!r}")
    return local.resample(rule).mean().dropna()


def quantile_bands(x: pd.Series, y: pd.Series, width: float = 2.0,
                   qs: tuple[float, ...] = (0.1, 0.5, 0.9), min_count: int = 5) -> pd.DataFrame:
    """Binned quantiles of `y` across `x` bins (°F) → the conditional spread of load at each
    temperature. Returns a DataFrame indexed by bin centre with one column per quantile
    ('p10','p50','p90', …); empty if too few points. Drives the optional quantile band on the
    load-vs-temperature scatter (e.g. P10–P90 = the load you'd see 80% of the time at that temp)."""
    x = pd.to_numeric(pd.Series(x), errors="coerce")
    y = pd.to_numeric(pd.Series(y), errors="coerce")
    m = x.notna() & y.notna()
    if int(m.sum()) < min_count:
        return pd.DataFrame()
    binc = (x[m] / width).round() * width
    g = pd.DataFrame({"_b": binc.to_numpy(), "_y": y[m].to_numpy()}).groupby("_b")["_y"]
    out = g.quantile(list(qs)).unstack()
    out = out[g.count() >= min_count]
    out.columns = [f"p{int(round(q * 100))}" for q in qs]
    return out.sort_index()


def wn_seasonal_curves(daily_by_year: dict, value: str = "demand", degree: int = 2,
                       method: str = "poly", base: float = 65.0, freq: str = "week"):
    """Weather-normalized seasonal load curve per year — the 'W/N load growth' figure.

    `daily_by_year`: {year: DataFrame[temp, value]} daily, datetime-indexed (local). `freq` sets the
    seasonal x-axis granularity ∈ {'day','week','month'}. Steps:
      1. **normal temperature by `freq`-of-year** = pooled mean across all years (the climatology),
         lightly smoothed (window scales with `freq`);
      2. for each year, fit the load–temperature relationship — `method`:
         - **'poly'**: least-squares polynomial `value ~ temp` (degree `degree`);
         - **'dd'**: the degree-day model `value ~ a + b·CDD + c·HDD` (CDD = max(temp−base,0),
           HDD = max(base−temp,0)) — separates cooling, heating, and the weather-independent baseline;
      3. **evaluate** each year's fit at the normal weekly temperature → the load that year *would*
         have drawn at normal weather. Weather is held constant, so the gap between year-curves is
         **structural growth**, not weather. Years are not extrapolated past their observed temps.

    Returns (curves, normal): curves = DataFrame [week 1..52 × year] in `value` units; normal =
    Series of normal temperature by week."""
    cap, smooth = {"day": (366, 7), "week": (52, 3), "month": (12, 1)}.get(freq, (52, 3))

    def _key(idx: pd.DatetimeIndex) -> "np.ndarray":
        if freq == "day":
            return np.asarray(idx.dayofyear, dtype=int)
        if freq == "month":
            return np.asarray(idx.month, dtype=int)
        return np.asarray(idx.isocalendar().week.astype(int))

    frames = []
    for d in daily_by_year.values():
        if d.empty:
            continue
        k = np.clip(_key(pd.DatetimeIndex(d.index)), None, cap)
        frames.append(pd.DataFrame({"k": k, "temp": d["temp"].to_numpy()}))
    if not frames:
        return pd.DataFrame(), pd.Series(dtype=float)
    normal = pd.concat(frames).groupby("k")["temp"].mean().sort_index()
    if smooth > 1:
        normal = normal.rolling(smooth, center=True, min_periods=1).mean()  # de-jitter the climatology
    nrm = normal.to_numpy(dtype=float)
    ncdd, nhdd = np.clip(nrm - base, 0, None), np.clip(base - nrm, 0, None)   # normal degree days
    min_pts = 3 if method == "dd" else degree
    out = {}
    for y, d in daily_by_year.items():
        x = pd.to_numeric(d["temp"], errors="coerce")
        yv = pd.to_numeric(d[value], errors="coerce")
        msk = x.notna() & yv.notna()
        if int(msk.sum()) <= min_pts or x[msk].nunique() <= min_pts:
            continue
        xv, yvv = x[msk].to_numpy(dtype=float), yv[msk].to_numpy(dtype=float)
        if method == "dd":
            cdd, hdd = np.clip(xv - base, 0, None), np.clip(base - xv, 0, None)
            coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(xv)), cdd, hdd]), yvv, rcond=None)
            pred = coef[0] + coef[1] * ncdd + coef[2] * nhdd
        else:
            pred = np.polyval(np.polyfit(xv, yvv, degree), nrm)
        # don't extrapolate past the year's observed temperature range (a partial year with no summer
        # should NOT get a fabricated summer curve) — blank those weeks instead
        pred = np.where((nrm >= xv.min()) & (nrm <= xv.max()), pred, np.nan)
        out[y] = pd.Series(pred, index=normal.index)
    curves = pd.DataFrame(out)
    curves.index.name = freq
    return curves, normal


def poly_fit(x: pd.Series, y: pd.Series, degree: int = 2, n: int = 120) -> dict:
    """Least-squares polynomial fit `y ~ poly(x, degree)` for the regression curve. Returns a dict
    with the smooth curve (`xs`, `ys`), coefficient of determination `r2`, `coef`, and `n` — or an
    empty dict if there are too few/degenerate points to fit (≤ degree points, or zero x-spread)."""
    x = pd.to_numeric(pd.Series(x), errors="coerce")
    y = pd.to_numeric(pd.Series(y), errors="coerce")
    m = x.notna() & y.notna()
    xv, yv = x[m].to_numpy(dtype=float), y[m].to_numpy(dtype=float)
    if len(xv) <= degree or float(np.ptp(xv)) == 0.0:
        return {}
    coef = np.polyfit(xv, yv, degree)
    yhat = np.polyval(coef, xv)
    ss_res = float(((yv - yhat) ** 2).sum())
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    xs = np.linspace(float(xv.min()), float(xv.max()), n)
    return {"xs": xs, "ys": np.polyval(coef, xs), "r2": r2, "coef": coef, "n": int(len(xv)),
            "p": int(degree)}


def seg_fit(x: pd.Series, y: pd.Series, n: int = 120, grid: "np.ndarray | None" = None) -> dict:
    """Piecewise **balance-point** (HDD/CDD) two-line fit — the physically-grounded load↔temperature
    model: `y = a + b_h·max(Tbp − T, 0) + b_c·max(T − Tbp, 0)`, i.e. an independent **heating** slope
    below the balance point `Tbp` and **cooling** slope above it, meeting at `Tbp` (chosen by least
    squares over a temperature grid). Returns the same shape as `poly_fit` (`xs`, `ys`, `r2`, `coef`,
    `n`, `p`) plus `tbp` (the fitted balance point) and `kind='piecewise'`; `{}` if too few/degenerate
    points. `p=4` (intercept + 2 slopes + the balance point) for honest adjusted-R²."""
    x = pd.to_numeric(pd.Series(x), errors="coerce")
    y = pd.to_numeric(pd.Series(y), errors="coerce")
    m = x.notna() & y.notna()
    xv, yv = x[m].to_numpy(dtype=float), y[m].to_numpy(dtype=float)
    if len(xv) <= 4 or float(np.ptp(xv)) == 0.0:
        return {}
    if grid is None:                                          # search Tbp over most of the observed range
        grid = np.linspace(float(np.percentile(xv, 5)), float(np.percentile(xv, 95)), 30)

    def basis(t: np.ndarray, tbp: float) -> np.ndarray:
        return np.column_stack([np.ones_like(t), np.clip(tbp - t, 0, None), np.clip(t - tbp, 0, None)])

    best = None                                               # (sse, tbp, coef)
    for tbp in grid:
        B = basis(xv, float(tbp))
        coef, *_ = np.linalg.lstsq(B, yv, rcond=None)
        sse = float(((yv - B @ coef) ** 2).sum())
        if best is None or sse < best[0]:
            best = (sse, float(tbp), coef)
    sse, tbp, coef = best
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2 = (1.0 - sse / ss_tot) if ss_tot > 0 else float("nan")
    xs = np.linspace(float(xv.min()), float(xv.max()), n)
    return {"xs": xs, "ys": basis(xs, tbp) @ coef, "r2": r2, "coef": coef, "n": int(len(xv)),
            "p": 4, "tbp": tbp, "kind": "piecewise"}


def adj_r2(r2: float, n: int, p: int) -> float:
    """Adjusted R² — penalises extra parameters so models of different complexity (linear vs quadratic
    vs piecewise) can be compared fairly. NaN if too few residual degrees of freedom."""
    if not np.isfinite(r2) or (n - p - 1) <= 0:
        return float("nan")
    return 1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)


def to_daily(df: pd.DataFrame, value: str, base: float = 65.0, tz: str = DISPLAY_TZ) -> pd.DataFrame:
    """Collapse the hourly panel to one row per local calendar day: daily-mean temperature
    (→ CDD/HDD vs `base`) and the daily mean of `value`. Degree days are a *daily* quantity, so
    this is the basis for the degree-day response (and the weather-normalized demand view)."""
    local_day = pd.Index(df.index.tz_convert(tz).date, name="day")
    daily = df.groupby(local_day)[["temp", value]].mean()
    daily["cdd"] = (daily["temp"] - base).clip(lower=0)
    daily["hdd"] = (base - daily["temp"]).clip(lower=0)
    daily["weekend"] = (pd.to_datetime(pd.Index(daily.index)).dayofweek >= 5).astype(float)
    return daily


def response_by_cdd(df: pd.DataFrame, value: str, kind: str = "cdd", width: float = 1.0,
                    min_count: int = 3) -> pd.DataFrame:
    """Daily mean of `value` by degree-day bin → the weather-response curve in degree-day units
    (kind ∈ {cdd, hdd}). Same idea as response_by_temp but x = degree days (trader units). Reading
    two periods at the same degree-day bin isolates the structural change."""
    daily = to_daily(df, value)
    binc = (daily[kind] / width).round() * width
    g = daily.assign(_bin=binc).groupby("_bin")[value].agg(["mean", "count"])
    return g[g["count"] >= min_count]


def diurnal(df: pd.DataFrame, value: str, temp_lo: float, temp_hi: float) -> pd.Series:
    """Mean of `value` by hour-of-day (CPT), within a temperature bin (holds weather ~constant)."""
    sub = df[(df["temp"] >= temp_lo) & (df["temp"] < temp_hi)]
    return sub.groupby("hour")[value].mean()


def fit_cdd_model(df: pd.DataFrame, value: str = "demand", kind: str = "cdd") -> tuple[float, float]:
    """Fit `value = a + b·DD` on daily data (cooling/heating days only). Returns (a, b) in the raw
    units of `value` (MW for demand). The transparent glass-box demand model we validate."""
    d = to_daily(df, value)
    d = d[d[kind] > 0]
    x, y = d[kind], d[value]
    b = y.cov(x) / x.var()
    a = y.mean() - b * x.mean()
    return float(a), float(b)


def eval_cdd_model(a: float, b: float, df: pd.DataFrame, value: str = "demand",
                   kind: str = "cdd") -> dict:
    """Apply model (a, b) to `df`'s degree days, compare to actual. Returns MAE, bias (mean error),
    R², and the aligned predicted/actual daily series — the backtest of the model's accuracy."""
    d = to_daily(df, value)
    d = d[d[kind] > 0]
    pred = a + b * d[kind]
    actual = d[value]
    err = pred - actual
    ss_res = float((err ** 2).sum())
    ss_tot = float(((actual - actual.mean()) ** 2).sum())
    return {
        "mae": float(err.abs().mean()),
        "bias": float(err.mean()),
        "r2": (1 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
        "n": int(len(d)),
        "pred": pred, "actual": actual, "cdd": d[kind],
    }


def cv_resolution(df: pd.DataFrame, value: str = "demand", kind: str = "cdd",
                  resolution: str = "month", weekend: bool = False,
                  min_days: int = 4, min_spread: float = 2.0) -> dict:
    """Leave-one-out cross-validation of `value = a + b·DD` (optionally `+ c·weekend`) at a time
    resolution (season=per year, month/week/day = calendar period). For each *fittable* window, hold
    out each day, refit on the rest, predict the held-out day → **out-of-sample** error. The
    overfitting-safe experiment: a finer resolution (or an extra parameter) that merely memorises
    scores badly out-of-sample even if its in-sample MAE looks low.

    A window is **underpowered** (skipped + counted) if it has < `min_days` days, < 3 distinct DD
    values, or DD spread < `min_spread` (Daily → 1 point → all underpowered). With `weekend=True` a
    window also needs ≥2 weekday and ≥2 weekend days. Returns OOS + in-sample MAE, OOS bias/R², the
    mean weekend coefficient (GW shift), and window counts."""
    d = to_daily(df, value)
    d = d[d[kind] > 0].copy()
    empty = {"n_windows": 0, "n_under": 0, "n_fit": 0, "pred": [], "actual": [],
             "oos_mae": float("nan"), "oos_bias": float("nan"), "oos_r2": float("nan"),
             "ins_mae": float("nan"), "weekend_effect": float("nan")}
    if d.empty:
        return empty
    d.index = pd.to_datetime(d.index)
    if resolution == "season":
        keys = d.index.year
    elif resolution == "month":
        keys = d.index.to_period("M")
    elif resolution == "week":
        keys = d.index.to_period("W")
    else:  # daily
        keys = d.index.to_period("D")
    feats = [kind] + (["weekend"] if weekend else [])

    oos_err: list[float] = []
    actual: list[float] = []
    pred: list[float] = []
    ins_abs: list[float] = []
    wk_coefs: list[float] = []
    window_sizes: list[int] = []
    n_windows = n_under = n_fit = 0
    for _, g in d.groupby(keys):
        n_windows += 1
        x = g[kind]
        ok = len(g) >= min_days and x.nunique() >= 3 and (x.max() - x.min()) >= min_spread
        if weekend:  # need both weekday & weekend days to estimate the calendar term
            we = g["weekend"].astype(bool)
            ok = ok and int(we.sum()) >= 2 and int((~we).sum()) >= 2
        if not ok:
            n_under += 1
            continue
        n_fit += 1
        window_sizes.append(len(g))
        X = np.column_stack([np.ones(len(g))] + [g[f].to_numpy(dtype=float) for f in feats])
        y = g[value].to_numpy(dtype=float)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        ins_abs.extend(np.abs(X @ coef - y).tolist())
        if weekend:
            wk_coefs.append(float(coef[-1]))
        for i in range(len(g)):                           # leave-one-out within the window
            m = np.ones(len(g), dtype=bool)
            m[i] = False
            try:
                c2, *_ = np.linalg.lstsq(X[m], y[m], rcond=None)
            except Exception:
                continue
            p = float(X[i] @ c2)
            oos_err.append(p - y[i])
            pred.append(p)
            actual.append(float(y[i]))

    if not oos_err:
        return {**empty, "n_windows": n_windows, "n_under": n_under, "n_fit": 0}
    err = pd.Series(oos_err)
    act = pd.Series(actual)
    ss_res = float((err ** 2).sum())
    ss_tot = float(((act - act.mean()) ** 2).sum())
    n_params = 2 + (1 if weekend else 0)  # intercept + slope (+ weekend)
    return {
        "n_windows": n_windows, "n_under": n_under, "n_fit": n_fit,
        "oos_mae": float(err.abs().mean()), "oos_bias": float(err.mean()),
        "oos_r2": (1 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
        "ins_mae": float(np.mean(ins_abs)) if ins_abs else float("nan"),
        "weekend_effect": float(np.mean(wk_coefs)) if wk_coefs else float("nan"),
        "n_test": len(actual),                               # total held-out test-days (1 per fold)
        "median_days": int(np.median(window_sizes)) if window_sizes else 0,  # days per window
        "min_days": int(min(window_sizes)) if window_sizes else 0,
        "max_days": int(max(window_sizes)) if window_sizes else 0,
        "n_params": n_params,
        "pred": pred, "actual": actual,
    }
