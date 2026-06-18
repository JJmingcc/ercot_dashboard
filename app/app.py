"""ERCOT-area Weather & Net-Load Monitor — local Streamlit MVP.

Run from the project root inside dash_env:
    streamlit run app/app.py

No sidebar (deployment wraps its own navigation) — all controls are in-page.
Hero = temperature map: pick a market (ERCOT/PJM/CAISO/SPP/MISO) and a view
(current, or the change vs yesterday … one year ago). Below = ERCOT net load
(demand − wind − solar) from Meteologica with the ECMWF-ENS ensemble fan.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

# Streamlit Community Cloud: copy app Secrets → environment variables so src/config.py's os.environ
# reads work in the cloud (there's no .env file there). Local runs use .env via python-dotenv and are
# unaffected (st.secrets raises when no secrets file exists → caught and skipped).
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

from src.geo import (  # noqa: E402
    assign_nearest_index, load_counties, market_counties, nearest_zone, subsample, zone_boundaries,
)
from src.netload import compute_dashboard_frame, implied_gas_burn_bcfd  # noqa: E402
from src.historical import available_months  # noqa: E402
from src.wxnorm import (  # noqa: E402
    adj_r2, cv_resolution, era_panel, lt_scatter, poly_fit, quantile_bands, response_by_cdd,
    seg_fit, to_daily, wn_seasonal_curves)
from src.storage import save_now_snapshot, snapshot_count  # noqa: E402
from src.weather import (  # noqa: E402
    FORECAST_MODEL, FORECAST_MODELS, LOOKBACKS, MARKET_MEAN, MARKETS, forecast_by_zone,
    historical_forecast_by_zone, points_at_lookback, points_climatology, points_now,
)

CLIM_VIEW = "vs 10-yr ERA5 normal"
VIEWS = list(LOOKBACKS) + [CLIM_VIEW]

DISPLAY_TZ = "America/Chicago"


def style_fig(fig: go.Figure, title: str | None = None, *, title_size: int = 19,
              legend_size: int = 14, base_size: int = 14, axis_title_size: int = 17) -> go.Figure:
    """Center + enlarge the chart title and legend, enlarge the x/y axis titles, and bump the base
    font, so every figure reads cleanly (esp. in dark mode). Applied *after* a figure's own
    update_layout so it overrides both the figure defaults and Streamlit's injected plotly theme.
    update_layout MERGES nested layout objects, so an existing legend orientation/y is preserved —
    only x/xanchor/font are changed.

    Pass `title` to set a centered title; if omitted, an existing title is just re-centered/enlarged.
    """
    fig.update_layout(font=dict(size=base_size),
                      legend=dict(x=0.5, xanchor="center", font=dict(size=legend_size)))
    fig.update_xaxes(title_font_size=axis_title_size)        # larger x/y axis labels
    fig.update_yaxes(title_font_size=axis_title_size)
    has_title = title is not None or (fig.layout.title is not None and fig.layout.title.text)
    if has_title:
        td: dict = dict(x=0.5, xanchor="center", font=dict(size=title_size))
        if title is not None:
            td["text"] = title
        fig.update_layout(title=td)
    return fig


st.set_page_config(page_title="Weather & Net-Load Monitor", layout="wide",
                   initial_sidebar_state="collapsed")


@st.cache_data(ttl=86400, show_spinner="Loading county boundaries…")
def counties_geojson():
    return load_counties()


@st.cache_data(ttl=86400, show_spinner=False)
def zone_outline(market: str):
    return zone_boundaries(market, counties_geojson(), MARKETS[market]["zones"])


MAX_FETCH_POINTS = 200  # cap Open-Meteo locations per request (keeps big markets in quota)


@st.cache_data(ttl=1800, show_spinner="Loading per-county temperatures…")
def county_now(market: str, unit: str, model: str):
    """Current temp per county for the chosen model; also persists a snapshot."""
    recs = market_counties(market, counties_geojson())
    samples = subsample(recs, MAX_FETCH_POINTS)
    now_s, now_t = points_now([s[1] for s in samples], [s[2] for s in samples], unit, model)
    idx = assign_nearest_index(recs, samples)
    now_v = [now_s[i] for i in idx]
    zones = MARKETS[market]["zones"]
    fips = [r[0] for r in recs]
    lats = [r[1] for r in recs]
    lons = [r[2] for r in recs]
    zlist = [nearest_zone(la, lo, zones) for la, lo in zip(lats, lons)]
    try:  # accumulate a local archive (idempotent per hour); never block the UI on it
        save_now_snapshot(market, model, unit, fips, lats, lons, now_v, now_t)
    except Exception:
        pass
    return fips, lats, lons, zlist, now_v, now_t


@st.cache_data(ttl=1800, show_spinner="Loading reference period…")
def county_past(market: str, unit: str, lookback_days: int, model: str):
    recs = market_counties(market, counties_geojson())
    samples = subsample(recs, MAX_FETCH_POINTS)
    past_s, past_t = points_at_lookback([s[1] for s in samples], [s[2] for s in samples],
                                        lookback_days, unit, model)
    idx = assign_nearest_index(recs, samples)
    return [past_s[i] for i in idx], past_t


@st.cache_data(ttl=1800, show_spinner="Comparing forecast models…")
def market_model_forecast(market: str, unit: str, forecast_days: int):
    """All-model forecast + ensemble band, per zone and market-mean."""
    return forecast_by_zone(MARKETS[market]["zones"], unit, forecast_days)


@st.cache_data(ttl=3600, show_spinner="Loading historical forecasts…")
def market_historical_forecast(market: str, unit: str, start: str, end: str):
    """All-model *archived past forecast* per zone for a date window."""
    return historical_forecast_by_zone(MARKETS[market]["zones"], unit, start, end)


@st.cache_data(ttl=21600, show_spinner="Computing 10-yr ERA5 climatology (multi-year)…")
def county_climatology(market: str, unit: str):
    """Per-county ERA5 normal (mean) + inter-annual std for today's date/hour."""
    recs = market_counties(market, counties_geojson())
    samples = subsample(recs, 120)  # coarser: this is a heavy multi-year fetch
    mean_s, std_s, years = points_climatology([s[1] for s in samples], [s[2] for s in samples], unit)
    idx = assign_nearest_index(recs, samples)
    return [mean_s[i] for i in idx], [std_s[i] for i in idx], years


def load_county_temp(market: str, view: str, unit: str, model: str):
    fips, lats, lons, zlist, now_v, now_t = county_now(market, unit, model)
    base = {"fips": fips, "lat": lats, "lon": lons, "zone": zlist, "now": now_v}
    if view == CLIM_VIEW:
        mean_v, std_v, years = county_climatology(market, unit)
        diff = [(n - m) if (n == n and m == m) else None for n, m in zip(now_v, mean_v)]
        cdf = pd.DataFrame({**base, "past": mean_v, "diff": diff, "pm": std_v})
        cdf["value"] = cdf["diff"]
        meta = {"mode": "diff", "now": now_t, "past": None, "clim_years": (years[0], years[-1], len(years))}
    elif LOOKBACKS[view] == 0:
        cdf = pd.DataFrame({**base, "past": None, "diff": None})
        cdf["value"] = cdf["now"]
        meta = {"mode": "absolute", "now": now_t, "past": None}
    else:
        past_v, past_t = county_past(market, unit, LOOKBACKS[view], model)
        diff = [(n - p) if (n == n and p == p) else None for n, p in zip(now_v, past_v)]
        cdf = pd.DataFrame({**base, "past": past_v, "diff": diff})
        cdf["value"] = cdf["diff"]
        meta = {"mode": "diff", "now": now_t, "past": past_t}
    meta.update(unit=unit, center=MARKETS[market]["center"], scale=MARKETS[market]["scale"],
                label=MARKETS[market]["label"])
    return cdf, meta


@st.cache_data(ttl=1800, show_spinner="Pulling latest ERCOT forecasts…")
def load_netload():
    frame, meta = compute_dashboard_frame()
    return frame.tz_convert(DISPLAY_TZ), meta


# Multi-model demand: ERCOT power-demand forecast (MW, hourly) under each Meteologica weather-model
# variant, per region. Models are the three the catalog carries a demand forecast for.
DEMAND_MODELS = ("Meteologica", "ECMWF-ENS", "ECMWF-ENSEXT")
DEMAND_MODEL_DESC = {"Meteologica": "Meteologica's own blend (best central estimate)",
                     "ECMWF-ENS": "ECMWF ensemble (~6-day)",
                     "ECMWF-ENSEXT": "ECMWF extended ensemble (~6-week, sub-seasonal)"}
DEMAND_MODEL_COLOR = {"Meteologica": "#2ca02c", "ECMWF-ENS": "#1f77b4", "ECMWF-ENSEXT": "#d62728"}
DEMAND_MODEL_FILL = {"ECMWF-ENS": "rgba(31,119,180,0.12)", "ECMWF-ENSEXT": "rgba(214,40,40,0.10)"}
# Dashboard zone label → Meteologica region path segment ('Total' = whole-ERCOT system).
DEMAND_ZONE_REGION = {"Whole ERCOT": "Total", "Coast": "Coast", "East": "East", "Far West": "FarWest",
                      "North": "North", "North Central": "NorthCentral", "South Central": "SouthCentral",
                      "Southern": "Southern", "West": "West"}


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def demand_model_catalog():
    """{model_label: {region: content_id}} for ERCOT hourly PowerDemand forecasts, parsed from the
    Meteologica catalog paths (`…/PowerDemand/Forecast/<model>/<region>/Total/Hourly`). None if down."""
    from src.meteologica_client import MeteologicaClient
    try:
        cats = MeteologicaClient().list_datasets()
    except Exception:
        return None
    out: dict[str, dict[str, int]] = {}
    for x in cats:
        p = x["path"]
        if "/ERCOT/PowerDemand/Forecast/" not in p or not p.endswith("/Hourly"):
            continue
        parts = p.split("/")
        i = parts.index("Forecast")
        model, region = parts[i + 1], parts[i + 2]
        if model in DEMAND_MODEL_DESC:
            out.setdefault(model, {})[region] = int(x["id"])
    return out or None


@st.cache_data(ttl=3600, show_spinner="Loading multi-model demand (Meteologica)…")
def load_demand_models(region: str = "Total"):
    """ERCOT demand forecast (MW, hourly, local tz) for one `region` ('Total' = whole system, else a
    weather-zone segment like 'Coast'/'FarWest') under each Meteologica weather-model variant.
    Returns {label: (central_series, p10|None, p90|None)} (p10/p90 from ensemble members) or None."""
    cat = demand_model_catalog()
    if not cat:
        return None
    from src.meteologica_client import MeteologicaClient
    from src.parsing import parse_data, central_column, member_columns
    try:
        client = MeteologicaClient()
    except Exception:
        return None
    out = {}
    for lab in DEMAND_MODELS:
        cid = cat.get(lab, {}).get(region)
        if cid is None:
            continue
        try:
            f = parse_data(client.get_content_data(cid)).frame.tz_convert(DISPLAY_TZ)
            cen = f[central_column(f)].dropna()
            mems = member_columns(f)
            p10 = f[mems].quantile(0.10, axis=1) if mems else None
            p90 = f[mems].quantile(0.90, axis=1) if mems else None
            if not cen.empty:
                out[lab] = (cen, p10, p90)
        except Exception:
            continue
    return out or None


def demand_spread_by_zone():
    """Cross-model demand spread (mean & peak MW over the common window) per weather zone — the
    'where do the demand models disagree' view. Reuses the per-zone cached loaders."""
    rows = {}
    for zlabel, region in DEMAND_ZONE_REGION.items():
        if zlabel == "Whole ERCOT":
            continue
        dmz = load_demand_models(region)
        if not dmz or len(dmz) < 2:
            continue
        cdf = pd.DataFrame({lab: dmz[lab][0] for lab in dmz}).dropna()
        if cdf.shape[0] and cdf.shape[1] >= 2:
            sp = cdf.max(axis=1) - cdf.min(axis=1)
            rows[zlabel] = {"mean": float(sp.mean()), "peak": float(sp.max())}
    return rows


@st.cache_data(ttl=1800, show_spinner="Loading per-zone demand (Meteologica)…")
def load_zone_demand_frame():
    """Hourly per-zone ERCOT demand forecast (MW, local-tz indexed) — the panel slices it by the
    chosen forecast day. Returns the frame, or None."""
    from src.zonal import zone_demand_forecast
    dem = zone_demand_forecast()
    if dem.empty:
        return None
    return dem.tz_convert(DISPLAY_TZ)


@st.cache_data(ttl=3600, show_spinner=False)
def hist_panel(year: int, months: tuple) -> pd.DataFrame:
    """Cached read of a year's ERCOT history panel (parquet) — reused across the Load-vs-temperature
    scatter and its per-zone summary so the 8-zone sweep doesn't re-read the same files."""
    return era_panel(year, months)


@st.cache_data(ttl=24 * 3600, show_spinner="Reconstructing Feb-2021 Uri demand (EIA + ERA5)…")
def uri_bundle():
    """Everything the Uri case-study panel needs: (res, stats, train_daily, curve, uri_daily) — or None
    if the cache isn't built. EIA-930 demand + ERA5 (Meteologica has no 2021)."""
    import src.uri2021 as uri
    p = uri.load_panel()
    if p.empty:
        return None
    res, stats = uri.analyze(p)
    train_daily, curve = uri.temp_curve(p)
    return res, stats, train_daily, curve, res.resample("1D").mean()


def render_uri_panel():
    """Feb-2021 Uri counterfactual case study — rendered inside the Load-vs-temperature page."""
    import src.uri2021 as uri
    st.markdown(
        "During Uri (mid-Feb 2021) ERCOT shed **~20 GW** of load (rolling blackouts), so the **observed "
        "demand on Feb 15–18 is curtailed served-load, not true demand** — on the coldest day (Feb 16, "
        "12.7 °F) observed demand *fell* below milder days, impossible without load shed. We reconstruct "
        "two counterfactuals from a weather→demand model fit on **un-curtailed** winter hours: **latent "
        "demand** (no curtailment) and **no-storm demand** (normal February weather). Source: **EIA-930 "
        "demand + ERA5** (Meteologica has no 2021). Method: `docs/winter-storm-uri-2021.md`.")
    ub = uri_bundle()
    if ub is None:
        st.info("Uri cache not built — run `python -m src.uri2021` (one-time EIA + ERA5 pull).")
        return
    res, s, train_daily, curve, ud = ub
    m = st.columns(5)
    m[0].metric("Served peak (observed)", f"{s['peak_observed']:.0f} GW",
                help="Highest demand actually served during the blackout window.")
    m[1].metric("Latent peak (modelled)", f"{s['peak_latent']:.0f} GW",
                delta=f"+{s['peak_latent'] - s['peak_observed']:.0f} vs served",
                help="What demand would have been at the storm's cold with no curtailment.")
    m[2].metric("Max unserved load", f"{s['max_unserved']:.0f} GW", help="latent − observed ≈ cut load.")
    m[3].metric("No-storm peak", f"{s['nostorm_peak']:.0f} GW", help="Demand at normal February weather.")
    m[4].metric("Model R²", f"{s['r2']:.2f}",
                help=f"hourly fit, residual ±{s['resid_std']:.1f} GW; coldest training hour "
                     f"{s['coldest_train']:.0f} °F (event reached {s['coldest_event']:.0f} °F).")
    fig = go.Figure()                                          # (1) time-series reconstruction
    fig.add_trace(go.Scatter(x=res.index, y=res["latent"] + res["band"], line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=res.index, y=res["latent"] - res["band"], fill="tonexty",
                             fillcolor="rgba(214,40,40,0.13)", line=dict(width=0), name="latent 95% band"))
    fig.add_trace(go.Scatter(x=res.index, y=res["latent"], line=dict(color="#d62728", width=2.6),
                             name="latent (no curtailment)"))
    fig.add_trace(go.Scatter(x=res.index, y=res["observed"], line=dict(color="#111", width=2),
                             name="observed (served / curtailed)"))
    fig.add_trace(go.Scatter(x=res.index, y=res["no_storm"], line=dict(color="#2ca02c", width=2, dash="dash"),
                             name="no-storm (normal weather)"))
    fig.add_trace(go.Scatter(x=res.index, y=res["temp"], line=dict(color="#4393c3", width=1.1),
                             name="temperature (°F, right)", yaxis="y2"))
    fig.add_vrect(x0=uri.CURTAIL_START, x1=uri.CURTAIL_END, fillcolor="rgba(110,110,110,0.10)",
                  line_width=0, annotation_text="rolling blackouts", annotation_position="top left")
    fig.update_layout(height=460, margin=dict(t=20, b=10), yaxis_title="ERCOT demand (GW)",
                      yaxis2=dict(title="temp (°F)", overlaying="y", side="right", color="#4393c3",
                                  showgrid=False), legend=dict(orientation="h", y=1.04), hovermode="x unified")
    st.plotly_chart(style_fig(fig), use_container_width=True)
    storm = (ud.index >= uri.CURTAIL_START) & (ud.index < uri.CURTAIL_END)   # (2) demand-vs-temp analog
    uds, solid, extr = ud[storm], curve[~curve["extrapolated"]], curve[curve["extrapolated"]]
    ts = go.Figure()
    ts.add_trace(go.Scattergl(x=train_daily["temp"], y=train_daily["demand"], mode="markers",
                 marker=dict(color="#c8c8c8", size=4, opacity=0.55), name="winter days (training)"))
    ts.add_trace(go.Scatter(x=solid["temp"], y=solid["demand"], mode="lines",
                 line=dict(color="#1f77b4", width=2.5), name="demand–temp fit"))
    if not extr.empty:
        ts.add_trace(go.Scatter(x=extr["temp"], y=extr["demand"], mode="lines",
                     line=dict(color="#1f77b4", width=2.5, dash="dot"), name="extrapolation (Uri-class cold)"))
    ts.add_trace(go.Scatter(x=uds["temp"], y=uds["observed"], mode="markers",
                 marker=dict(color="#111", size=11, symbol="x"), name="Uri observed (curtailed)"))
    ts.add_trace(go.Scatter(x=uds["temp"], y=uds["latent"], mode="markers",
                 marker=dict(color="#d62728", size=11, symbol="star"), name="Uri latent (modelled)"))
    ts.update_layout(height=420, margin=dict(t=30, b=10), title="Demand vs temperature — analog reference",
                     xaxis_title="ERCOT temperature (°F)", yaxis_title="daily-mean demand (GW)",
                     legend=dict(orientation="h", y=1.02), hovermode="closest")
    st.plotly_chart(style_fig(ts), use_container_width=True)
    st.caption(
        f"**Top:** observed (collapses in blackouts) vs **latent** (~{s['peak_latent']:.0f} GW, unserved "
        f"~{s['max_unserved']:.0f} GW) vs **no-storm** (~{s['nostorm_peak']:.0f} GW). **Bottom:** "
        f"demand↔temp curve from un-curtailed winters — **✕** = curtailed observed (below curve), "
        f"**★** = latent on the curve. Model R²={s['r2']:.2f}. Source: EIA-930 + ERA5.")


@st.cache_data(ttl=3600, show_spinner="Loading actual gas generation (EIA-930)…")
def actual_gas_burn(start: str, end: str, heat_rate: float):
    """Actual ERCOT gas burn (Bcf/d) from EIA-930 generation — no baseload assumption."""
    from src.eia import ercot_gas_generation
    gen = ercot_gas_generation(start, end)               # MW, UTC
    return implied_gas_burn_bcfd(gen, 0.0, heat_rate)    # gas gen × heat rate → Bcf/d


@st.cache_data(ttl=3600, show_spinner="Loading ERCOT degree days (StormVista)…")
def load_ercot_wdd(kind: str):
    """ERCOT load-proxy (population-weighted) degree days from StormVista, for one `kind`
    ('cdd' cooling or 'hdd' heating): deterministic forecast, GEFS ensemble members, ~7-day
    actuals, and the 30-yr normal. Returns a WddBundle (or None if no key is configured)."""
    import src.stormvista as sv
    if not sv.is_configured():
        return None
    return sv.ercot_bundle(kind)


@st.cache_data(ttl=3600, show_spinner=False)
def load_model_wdd(model: str, kind: str):
    """One weather model's ERCOT pop-weighted degree-day forecast (its own latest run) for the
    multi-model overlay. Returns (series, date, cycle) or None if unavailable / not subscribed.
    Ensemble model ids (gfs-ens, ecmwf-eps, …) resolve to that ensemble's mean WDD."""
    import src.stormvista as sv
    if not sv.is_configured():
        return None
    try:
        date, cycle = sv.latest_run(model, kind=kind)
        s = sv.ercot_wdd(model=model, date=date, cycle=cycle, kind=kind)
        return (s, date, cycle) if s.notna().any() else None   # guard empty / all-NaN (ghost legend)
    except Exception:
        return None                                          # out-of-season / not subscribed → skip


@st.cache_data(ttl=3600, show_spinner="Loading ERCOT temperature (StormVista)…")
def load_ercot_temp():
    """Load-weighted *absolute* ERCOT daily temperature (°F: tmax/tmin/tavg) from StormVista
    city-extraction — the raw weather behind the degree days. None if no key is configured."""
    import src.stormvista as sv
    if not sv.is_configured():
        return None
    return sv.ercot_temperature()


@st.cache_data(ttl=3600, show_spinner="Loading sub-daily ERCOT temperature (StormVista)…")
def load_ercot_temp_hourly():
    """Per-station + load-weighted ERCOT sub-daily (3-hourly) temperature (°F) from StormVista —
    columns = the ERCOT stations (KIAH…) plus 'load-weighted'. None if no key is configured."""
    import src.stormvista as sv
    if not sv.is_configured():
        return None
    return sv.ercot_station_temps_hourly()


@st.cache_data(ttl=86400, show_spinner=False)
def prune_stormvista_cache():
    """Bound `data/stormvista/` growth — drop run files older than 14 days, at most once a day."""
    import src.stormvista as sv
    try:
        return sv.prune_cache(max_age_days=14)
    except Exception:
        return 0


def build_map(cdf: pd.DataFrame, meta: dict, market: str) -> go.Figure:
    """Per-county temperature choropleth with dissolved zone outlines + labels on top."""
    unit, mode = meta["unit"], meta["mode"]
    counties = counties_geojson()
# Saturated diverging scale (ColorBrewer RdBu, reversed) — vivid blues/reds, less white.
DIVERGING = [[0.0, "#2166ac"], [0.15, "#4393c3"], [0.35, "#92c5de"], [0.5, "#f7f7f7"],
             [0.65, "#f4a582"], [0.85, "#d6604d"], [1.0, "#b2182b"]]


def build_map(cdf: pd.DataFrame, meta: dict, market: str) -> go.Figure:
    unit, mode = meta["unit"], meta["mode"]
    counties = counties_geojson()
    if mode == "diff":
        # robust range: saturate at the 92nd percentile of |Δ| so colours read strongly
        m = max(float(cdf["value"].abs().quantile(0.92)), 1.0)
        cs, zmin, zmax, zmid, cbar = DIVERGING, -m, m, 0, f"Δ ({unit})"
        cust = cdf[["zone", "now", "past"]].to_numpy()
        ht = ("%{customdata[0]} county<br>now %{customdata[1]:.1f}" + unit
              + " · then %{customdata[2]:.1f}" + unit
              + "<br><b>Δ %{z:+.1f}" + unit + "</b><extra></extra>")
    else:
        cs, zmin, zmax, zmid = "Turbo", cdf["value"].min(), cdf["value"].max(), None
        cbar = f"Temp ({unit})"
        cust = cdf[["zone"]].to_numpy()
        ht = "%{customdata[0]} county<br>%{z:.1f}" + unit + "<extra></extra>"
    fig = go.Figure(go.Choropleth(
        geojson=counties, locations=cdf["fips"], z=cdf["value"], featureidkey="id",
        colorscale=cs, zmin=zmin, zmax=zmax, zmid=zmid, customdata=cust, hovertemplate=ht,
        marker_line_width=0, colorbar_title=cbar,  # no white county lines (kept colours washed)
    ))
    # Dissolved zone outlines + labels (dark text + a light halo so it stays readable).
    olats, olons = zone_outline(market)
    fig.add_trace(go.Scattergeo(lat=olats, lon=olons, mode="lines",
                  line=dict(width=1.8, color="#000"), hoverinfo="skip", showlegend=False))
    zs = MARKETS[market]["zones"]
    fig.add_trace(go.Scattergeo(
        lat=[v[0] for v in zs.values()], lon=[v[1] for v in zs.values()], text=list(zs.keys()),
        mode="text", textfont=dict(size=12, color="#000", family="Arial Black"),
        hoverinfo="skip", showlegend=False))
    fig.update_geos(
        scope="usa", resolution=110, showsubunits=True, subunitcolor="#000", subunitwidth=1.1,
        showcountries=True, countrycolor="#000",
        center=dict(lat=meta["center"][0], lon=meta["center"][1]), projection_scale=meta["scale"],
    )
    fig.update_layout(height=660, margin=dict(t=10, b=10, l=0, r=0))
    return fig


def build_demand_map(zone_demand: dict, metric_label: str, *, colorbar_title: str = "GW",
                     value_fmt: str = "{:.1f}", unit: str = "GW", colorscale: str = "YlOrRd",
                     height: int = 560) -> go.Figure:
    """ERCOT choropleth: each county filled by its **zone's value**, with zone outlines and the value
    labelled on each zone. Reuses the county→zone assignment. Defaults render forecast demand (GW);
    pass colorbar_title/value_fmt/unit to render another per-zone quantity (e.g. GW/°F sensitivity)."""
    counties = counties_geojson()
    recs = market_counties("ERCOT", counties)             # [(fips, lat, lon)]
    zones = MARKETS["ERCOT"]["zones"]
    fips = [r[0] for r in recs]
    zlist = [nearest_zone(la, lo, zones) for _, la, lo in recs]
    vals = [zone_demand.get(z) for z in zlist]
    fig = go.Figure(go.Choropleth(
        geojson=counties, locations=fips, z=vals, featureidkey="id", colorscale=colorscale,
        customdata=[[z] for z in zlist], marker_line_width=0, colorbar_title=colorbar_title,
        hovertemplate="%{customdata[0]} zone<br>" + metric_label + " %{z:.2f} " + unit + "<extra></extra>"))
    olats, olons = zone_outline("ERCOT")
    fig.add_trace(go.Scattergeo(lat=olats, lon=olons, mode="lines",
                  line=dict(width=1.8, color="#000"), hoverinfo="skip", showlegend=False))
    labels = [f"{z}<br>{value_fmt.format(zone_demand[z]) if zone_demand.get(z) == zone_demand.get(z) and z in zone_demand else '—'}"
              for z in zones]
    fig.add_trace(go.Scattergeo(
        lat=[v[0] for v in zones.values()], lon=[v[1] for v in zones.values()], text=labels,
        mode="text", textfont=dict(size=11, color="#000", family="Arial Black"),
        hoverinfo="skip", showlegend=False))
    fig.update_geos(scope="usa", resolution=110, showsubunits=True, subunitcolor="#000",
                    subunitwidth=1.1, showcountries=True, countrycolor="#000",
                    center=dict(lat=31.2, lon=-99.4), projection_scale=3.6)
    fig.update_layout(height=height, margin=dict(t=10, b=10, l=0, r=0))
    return fig


# Saturated diverging endpoints for table cells.
_MID, _WARM, _COOL = (247, 247, 247), (178, 24, 43), (33, 102, 172)


def _cell_style(v: float, m: float) -> str:
    """Vivid red(warmer)/blue(cooler) background with a contrasting (never white-on-light) text."""
    if pd.isna(v):
        return ""
    t = max(-1.0, min(1.0, v / m))
    a = abs(t) ** 0.6  # boost mid-range saturation so small values aren't near-white
    end = _WARM if t >= 0 else _COOL
    r, g, b = (int(_MID[i] + (end[i] - _MID[i]) * a) for i in range(3))
    fg = "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) < 150 else "#111111"
    return f"background-color: rgb({r},{g},{b}); color: {fg}; font-weight: 600"


def _temp_bg(v: float, vmin: float, vmax: float) -> str:
    """Sequential cool→warm temperature background (matplotlib-free) with readable text."""
    if pd.isna(v):
        return ""
    t = max(0.0, min(1.0, (v - vmin) / max(vmax - vmin, 1e-9)))
    if t < 0.5:  # blue -> pale yellow
        a = t / 0.5
        r, g, b = (int(_COOL[i] + ((255, 255, 191)[i] - _COOL[i]) * a) for i in range(3))
    else:        # pale yellow -> red
        a = (t - 0.5) / 0.5
        r, g, b = (int((255, 255, 191)[i] + (_WARM[i] - (255, 255, 191)[i]) * a) for i in range(3))
    fg = "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) < 150 else "#111111"
    return f"background-color: rgb({r},{g},{b}); color: {fg}"


def _hilo_col(col: pd.Series) -> list[str]:
    """Per-column: highlight the highest forecast red and the lowest blue (rest neutral)."""
    valid = col.dropna()
    if valid.empty:
        return [""] * len(col)
    mx, mn = valid.max(), valid.min()
    out = []
    for v in col:
        if pd.isna(v):
            out.append("")
        elif v == mx:
            out.append("background-color:#d6604d; color:#fff; font-weight:700")
        elif v == mn:
            out.append("background-color:#4393c3; color:#fff; font-weight:700")
        else:
            out.append("")
    return out


def zone_table(cdf: pd.DataFrame, mode: str):
    """Per-zone summary (county mean), colour-coded, with ± column(s).

    `±`     = inter-annual std (ERA5-normal view) or spatial spread otherwise.
    `fcst±` = forecast spread (GFS ensemble member std), only when enabled.
    """
    spec = {"now": ("now", "mean"), "past": ("past", "mean"), "diff": ("diff", "mean")}
    spec["pm"] = ("pm", "mean") if "pm" in cdf.columns else \
                 ("diff" if mode == "diff" else "now", "std")
    if "fcst_pm" in cdf.columns:
        spec["fcst"] = ("fcst_pm", "mean")
    agg = cdf.groupby("zone").agg(**spec).reset_index().rename(columns={"pm": "±", "fcst": "fcst±"})

    cols = ["zone", "now"] + (["past", "diff"] if mode == "diff" else []) + ["±"]
    if "fcst_pm" in cdf.columns:
        cols.append("fcst±")
    fmt = {"now": "{:.1f}", "past": "{:.1f}", "diff": "{:+.1f}", "±": "±{:.1f}", "fcst±": "±{:.1f}"}
    fmt = {k: v for k, v in fmt.items() if k in cols}
    styler = agg[cols].style.format(fmt)
    if mode == "diff":
        m = max(abs(agg["diff"].dropna()).max(), 1.0)
        return styler.map(lambda v: _cell_style(v, m), subset=["diff"])
    lo, hi = agg["now"].min(), agg["now"].max()
    mid, half = (lo + hi) / 2, max((hi - lo) / 2, 1e-9)
    return styler.map(lambda v: _cell_style(v - mid, half), subset=["now"])


# ============================ page ========================================
st.title("🌡️ Weather & Net-Load Monitor")
# Load vs temperature is the priority view → first option, so it is the default landing page.
DASH = st.radio("Dashboard", ["📈 Load vs temperature", "📡 Live monitor",
                              "🔋 Weather-normalized history"],
                horizontal=True, label_visibility="collapsed")

if DASH == "🔋 Weather-normalized history":
    # ===================== DASHBOARD 2: Weather-normalized history =====================
    st.subheader("🔋 Weather-normalized comparison — temperature & demand")
    _AVAIL = available_months()
    if not _AVAIL:
        st.info("No historical panels yet — run `python -m src.backfill_history` to cache ERCOT "
                "observations + ERA5 temperature.")
        st.stop()
    st.markdown("Compare ERCOT across **years** or **months**. The **temperature** box shows the weather "
                "each period actually had; the weather-normalized curves compare *at the same temperature*, "
                "so their gap is **structural** (solar + batteries + demand growth), not weather.")
    MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#17becf", "#e377c2"]
    yrs = list(_AVAIL)
    cc = st.columns([1.0, 1.8, 1.6, 1.1])
    compare_by = cc[0].radio("Compare", ["Years", "Months"])
    if compare_by == "Years":
        sel = cc[1].multiselect("Years", yrs, default=sorted({yrs[0], yrs[-1]}))
        common = sorted(set.intersection(*[set(_AVAIL[y]) for y in sel])) if sel else []
        msel = cc[2].multiselect("Months", common, default=common, format_func=lambda m: MONTHS[m])
        entities = [(str(y), era_panel(y, tuple(msel))) for y in sel]
    else:
        y = cc[1].selectbox("Year", yrs, index=len(yrs) - 1)
        msel = cc[2].multiselect("Months", _AVAIL[y], default=_AVAIL[y], format_func=lambda m: MONTHS[m])
        entities = [(MONTHS[m], era_panel(y, (m,))) for m in msel]
    metric = cc[3].radio("Metric", ["Demand (GW)", "Net load (GW)"])
    entities = [(lab, p) for lab, p in entities if not p.empty]
    if not entities:
        st.info("Select at least one period with cached data.")
        st.stop()
    valcol = {"Demand": "demand", "Net load": "net_load"}[metric.split(" (")[0]]
    yt = "GW"
    scale = lambda s: s / 1000.0  # noqa: E731  (MW → GW)

    ft = go.Figure()
    for i, (lab, p) in enumerate(entities):
        ft.add_trace(go.Box(y=p["temp"], name=lab, marker_color=COLORS[i % len(COLORS)], boxmean=True))
    ft.update_layout(height=300, margin=dict(t=10, b=10), yaxis_title="ERCOT temperature (°F)", showlegend=False)
    st.markdown("**Temperature** — what the weather actually was each period (median, quartiles, mean ◇). "
                "This is the difference normalization removes.")
    st.plotly_chart(style_fig(ft), use_container_width=True)

    # ① weather → load: the correlation + the fitted line a + b·DD per period. b (units/°day) is the
    # weather-sensitivity, a is the weather-independent baseline; the drift in a,b across years is the
    # structural signal (growth/solar/batteries). Dots = binned means; dotted = the OLS fit.
    ddk = "cdd" if st.radio("Degree-day axis", ["CDD (cooling)", "HDD (heating)"], horizontal=True,
                            key="wxnorm_ddkind").startswith("CDD") else "hdd"
    mname = metric.split(" (")[0].lower()
    fa = go.Figure()
    coef_rows = []
    for i, (lab, p) in enumerate(entities):
        col = COLORS[i % len(COLORS)]
        binned = response_by_cdd(p, valcol, kind=ddk)                 # dots = binned means
        fa.add_trace(go.Scatter(x=binned.index, y=scale(binned["mean"]), name=lab, mode="markers",
                                marker=dict(color=col, size=7)))
        daily = to_daily(p, valcol)
        daily = daily[daily[ddk] > 0]                                 # days where this DD is active
        if len(daily) >= 5:
            x, yv = daily[ddk], scale(daily[valcol])
            b = yv.cov(x) / x.var()                                   # slope: units per degree day
            a = yv.mean() - b * x.mean()                              # intercept: baseline
            xl = [x.min(), x.max()]
            fa.add_trace(go.Scatter(x=xl, y=[a + b * v for v in xl], mode="lines",
                                    line=dict(color=col, dash="dot"), showlegend=False))
            coef_rows.append({"period": lab, "r": x.corr(yv), f"baseline a ({yt})": a,
                              f"slope b ({yt}/°day)": b, f"@{ddk.upper()}=15": a + b * 15})
    fa.update_layout(height=340, margin=dict(t=10, b=10),
                     xaxis_title=f"ERCOT {ddk.upper()} (°-days, daily)",
                     yaxis_title=yt, legend=dict(orientation="h", y=1.02), hovermode="closest")
    st.markdown(f"**① Weather → {mname}: correlation & drift** — daily {yt} vs **{ddk.upper()}**, with "
                f"the fitted line `a + b·{ddk.upper()}` per period (dots = binned means, dotted = fit). "
                "**r** = how tightly weather explains it; **a** = weather-independent baseline; "
                f"**b** = sensitivity ({yt} per degree day). Same {ddk.upper()} → the gap (and the "
                "**a, b drift across years**) is structural, not weather.")
    st.plotly_chart(style_fig(fa), use_container_width=True)
    if coef_rows:
        cdf = pd.DataFrame(coef_rows).set_index("period")
        fmt = {c: ("{:.2f}" if (c == "r" or "slope" in c) else "{:.1f}") for c in cdf.columns}
        st.dataframe(cdf.style.format(fmt), use_container_width=True)
        st.caption("`r` ≈ 0.9+ → weather explains the day-to-day swing. Rising **a** = always-on growth; "
                   "rising **b** = more weather-sensitive load; `@DD=15` = demand at identical weather "
                   "(its climb across years is the structural change).")

    # 🎯 Validation backtest — fit `value = a + b·DD` at a chosen time RESOLUTION, scored
    # OUT-OF-SAMPLE by leave-one-out CV (so a finer resolution can't win by memorising). Underpowered
    # windows (too little weather spread to fit a slope, e.g. every Daily window) are flagged + skipped.
    st.markdown(f"**🎯 Validation — backtest the weather → {mname} model (out-of-sample, leave-one-out CV)**")
    rc = st.columns([3, 1.6])
    res = rc[0].radio("Fit resolution", ["Season", "Month", "Week", "Daily"], horizontal=True,
                      key="bt_resolution",
                      help="How local the a+b·DD fit is. Finer = more windows with fewer days each → "
                           "overfitting risk. Scored OUT-OF-SAMPLE (leave-one-out) so memorising is penalised.")
    split_we = rc[1].toggle("Split weekday/weekend", key="bt_weekend",
                            help="Add a calendar term a + b·DD + c·weekend (weekends draw less load at the "
                                 "same weather). One extra parameter — checked OUT-OF-SAMPLE so it only "
                                 "counts if it genuinely helps.")
    pooled = pd.concat([p for _, p in entities]) if entities else pd.DataFrame()
    cv = cv_resolution(pooled, value=valcol, kind=ddk, resolution=res.lower(), weekend=split_we)
    cv_base = (cv_resolution(pooled, value=valcol, kind=ddk, resolution=res.lower())
               if split_we else None)
    if cv["n_under"]:
        st.warning(f"⚠️ {cv['n_under']} of {cv['n_windows']} **{res.lower()}** windows were "
                   "**underpowered** (too few days / too little weather spread"
                   + (", or lacked ≥2 weekday & ≥2 weekend days" if split_we else "")
                   + ") and skipped" + (" — every window is a single day, so the slope can't be estimated."
                   if res == "Daily" else "."))
    if cv["n_fit"] > 0 and cv["pred"]:
        gap = scale(cv["oos_mae"] - cv["ins_mae"])
        # train/test sizes — leave-one-out: each fold trains on (window − 1) days, tests on 1.
        st.caption(
            f"**Setup:** {cv['n_fit']} {res.lower()} window(s) ~**{cv['median_days']} days** each; "
            f"leave-one-out → **{cv['n_test']} held-out test-days**, **{cv['n_params']} parameters**.")
        vm = st.columns(4)
        vm[0].metric(f"OOS MAE ({yt})", f"{scale(cv['oos_mae']):.2f}",
                     delta=(f"{scale(cv['oos_mae'] - cv_base['oos_mae']):+.2f} vs weather-only"
                            if cv_base and cv_base["n_fit"] else None), delta_color="inverse",
                     help=f"out-of-sample (leave-one-out). In-sample {scale(cv['ins_mae']):.2f}.")
        vm[1].metric(f"OOS bias ({yt})", f"{scale(cv['oos_bias']):+.2f}")
        vm[2].metric("OOS R²", f"{cv['oos_r2']:.2f}")
        if split_we:
            vm[3].metric(f"Weekend effect ({yt})", f"{scale(cv['weekend_effect']):+.2f}",
                         help="GW shift on Sat/Sun at the same weather (negative = lower — offices/industry idle).")
        else:
            vm[3].metric(f"Overfit gap ({yt})", f"{gap:+.2f}",
                         help="OOS MAE − in-sample MAE. ~0 = generalises; large = memorising the window.")
        pa = pd.DataFrame({"pred": scale(pd.Series(cv["pred"])), "actual": scale(pd.Series(cv["actual"]))})
        lim = [float(pa.values.min()) * 0.98, float(pa.values.max()) * 1.02]
        fv = go.Figure()
        fv.add_trace(go.Scatter(x=pa["actual"], y=pa["pred"], mode="markers",
                                marker=dict(color="#d6604d", size=6, opacity=0.6),
                                name=f"held-out days ({cv['n_test']})"))
        fv.add_trace(go.Scatter(x=lim, y=lim, mode="lines", line=dict(color="#888", dash="dot"),
                                name="perfect (y = x)"))
        fv.update_layout(height=300, margin=dict(t=10, b=10), xaxis_title=f"actual {mname} ({yt})",
                         yaxis_title=f"predicted (OOS, {yt})", legend=dict(orientation="h", y=1.02))
        st.plotly_chart(style_fig(fv), use_container_width=True)
        if split_we and cv_base and cv_base["n_fit"]:
            dhelp = scale(cv_base["oos_mae"] - cv["oos_mae"])
            verdict_we = (f"**helps** — OOS MAE {scale(cv_base['oos_mae']):.2f} → {scale(cv['oos_mae']):.2f} "
                          f"({dhelp:+.2f} {yt}); a *real* effect, validated out-of-sample (not overfit)"
                          if dhelp > 0.02 else
                          f"**doesn't help** out-of-sample ({dhelp:+.2f} {yt}) — not worth the extra parameter")
            st.caption(
                f"**Weekday/weekend split.** Weekends draw **{scale(cv['weekend_effect']):+.2f} {yt}** at the "
                f"same weather. Adding the calendar term {verdict_we}.")
        else:
            verdict = ("generalises well" if gap < 0.2 else
                       "**overfitting** — low in-sample MAE but the gap shows it isn't real skill")
            st.caption(
                f"**Out-of-sample backtest** of `{mname} = a + b·{ddk.upper()}` per **{res.lower()}** window "
                f"(leave-one-out, {cv['n_fit']} windows). OOS MAE ≈ **{scale(cv['oos_mae']):.2f} {yt}**, "
                f"in-sample {scale(cv['ins_mae']):.2f} → **overfit gap {gap:+.2f}** ({verdict}).")
    elif cv["n_fit"] == 0:
        st.error(f"At **{res}** resolution the slope can't be fit out-of-sample — that *is* the honest "
                 "result (a window needs enough hot-and-mild days; a single day has none).")

    st.caption("ERCOT zone-mean temperature · Meteologica obs + ERA5. "
               "Add periods: `python -m src.backfill_history <years>`.")
    st.stop()

if DASH == "📈 Load vs temperature":
    # ===================== DASHBOARD 3: Load vs temperature scatter =====================
    # The raw historical relationship: ERCOT load (y) vs load-weighted temperature (x), one point
    # per chosen time bucket. Load↔temperature is a U / "hockey stick" — heating drives it up at the
    # cold end, cooling at the hot end, with a minimum near the 65°F balance point — so the default
    # fit is QUADRATIC (a straight line can only follow one arm). Colour-by-year exposes the
    # structural drift: the same temperature drawing more load each year = growth, not weather.
    st.subheader("📈 ERCOT load vs temperature — historical scatter")
    _AVAIL = available_months()
    if not _AVAIL:
        st.info("No historical panels yet — run `python -m src.backfill_history` to cache ERCOT "
                "observations + ERA5 temperature.")
        st.stop()
    MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#17becf", "#e377c2",
              "#bcbd22", "#7f7f7f", "#393b79", "#e7969c"]
    ZONES = ["Coast", "East", "Far West", "North", "North Central", "South Central", "Southern", "West"]
    yrs = list(_AVAIL)
    # All controls are uniform dropdown menus on two even rows of four — no radio "dots" / toggles —
    # so the control bar reads as one clean, aligned grid above the scatter.
    r1 = st.columns(4)
    zone = r1[0].selectbox("Zone", ["Whole ERCOT", "All zones (overlay)"] + ZONES,
                           help="Whole ERCOT, all 8 weather zones overlaid, or a single zone. Per zone "
                                "we plot that zone's demand vs its OWN temperature — more precise than "
                                "the system mean (e.g. Far West is industrial → weak temp sensitivity).")
    sel_years = r1[1].multiselect("Years", yrs, default=yrs)
    resolution = r1[2].selectbox("Resolution", ["Hourly", "Daily", "Weekly", "Monthly", "Yearly"],
                                 index=1, help="Each scatter point is the mean over this bucket. "
                                 "Hourly = every observation (intraday spread); Daily = the classic "
                                 "load–temp scatter; coarser = the trend.")
    overlay = zone == "All zones (overlay)"
    is_zone = zone not in ("Whole ERCOT", "All zones (overlay)")
    demand_only = overlay or is_zone                       # net load is a system quantity (no zoning)
    load_opts = ["Demand"] if demand_only else ["Demand", "Net load"]
    metric = r1[3].selectbox("Load", load_opts,
                             help="Per-zone is demand-only — net load can't be zoned (renewables are "
                                  "dispatched grid-wide). Demand tracks temperature; net load is decoupled.")
    # Colour-by is fixed to Year (the structural-drift read) — the menu is removed by design. In overlay
    # mode the scatter still colours by zone (handled by `cmode` below).
    color_by = "Year"
    r2 = st.columns(3)
    fit_kind = r2[0].selectbox("Method", ["Quadratic", "Linear", "None"], index=0, key="lt_method",
                               help="Load↔temperature is U-shaped, so a quadratic fits both the heating "
                                    "and cooling arms; a line only follows one. R² is shown on each "
                                    "legend entry.")
    qband = r2[1].selectbox("Quantile band", ["Off", "On"], index=0,
                            help="Overlay the **P10–P90** spread of load at each temperature (+ P50 line) — "
                                 "the conditional distribution, pooled over the shown points.") == "On"
    bat_mode = r2[2].selectbox("Remove battery charging", ["Off", "2025 only", "2025 & 2026"], index=0,
                               key="bat_mode", help="Subtract battery **charging** (load) from whole-ERCOT "
                               "demand for the chosen years — `demand + min(battery_net,0)`. Battery obs "
                               "exist ~late-2024+; system-only (ignored for single zones / overlay).")
    bat_years = {"Off": set(), "2025 only": {2025}, "2025 & 2026": {2025, 2026}}[bat_mode]
    deg = {"Quadratic": 2, "Linear": 1}.get(fit_kind)      # None ⇒ no curve
    res_key = resolution.lower()
    cmode = "Zone" if overlay else color_by

    def _cols_for(z: str) -> tuple[str, str]:
        """(temp_col, value_col) for whole-ERCOT or a specific zone."""
        if z in ("Whole ERCOT", "All zones (overlay)"):
            return "temp", {"Demand": "demand", "Net load": "net_load"}[metric]
        return f"temp_{z}", f"demand_{z}"

    # assemble points: one row per (zone × year) bucket → a long frame (GW)
    recs = []
    bat_applied = 0.0                                      # GW of charging removed (for the caption)
    for z in (ZONES if overlay else [zone]):
        tcol, vcol = _cols_for(z)
        for y in sel_years:
            p = hist_panel(y, tuple(_AVAIL[y]))
            if z == "Whole ERCOT" and y in bat_years and not p.empty and "battery_net" in p.columns:
                adj = p["battery_net"].clip(upper=0).fillna(0.0)   # charging (≤0); 0 where no battery data
                bat_applied = max(bat_applied, -adj.mean() / 1000.0)
                p = p.assign(demand=p["demand"] + adj, net_load=p["net_load"] + adj)  # new df, cache safe
            agg = lt_scatter(p, vcol, res_key, temp_col=tcol) if not p.empty else pd.DataFrame()
            if agg.empty:
                continue
            ts = pd.DatetimeIndex(agg.index)
            recs.append(pd.DataFrame({"temp": agg[tcol].to_numpy(),
                                      "value": agg[vcol].to_numpy() / 1000.0,   # MW → GW
                                      "year": y, "month": ts.month, "zone": z}))
    data = pd.concat(recs, ignore_index=True) if recs else pd.DataFrame()
    if data.empty:
        st.info("No cached data for this selection. If you just added zones, run "
                "`python -m src.backfill_history --force` to cache the per-zone columns.")
        st.stop()

    def _fit_curve(x, y):
        """Polynomial fit dict (or None) for these points, honouring the Fit selector."""
        return poly_fit(x, y, deg) if deg is not None else None

    def _add_fit_line(fig, f, color, group):
        """Dotted fit curve with NO own legend entry — the per-group R² rides on that group's marker
        name instead (e.g. '2021 · R²=0.93'), so each colour is a SINGLE legend item that still shows
        the R² and the legend stays on one row on a wide screen."""
        fig.add_trace(go.Scatter(x=f["xs"], y=f["ys"], mode="lines", legendgroup=group,
                                 showlegend=False, line=dict(color=color, width=2.6, dash="dot")))

    def _leg(base, f):
        """Legend label: 'base · R²=…' when a fit exists, else the plain base label."""
        return f"{base} · R²={f['r2']:.2f}" if f else base

    fig = go.Figure()
    big = len(data) > 4000  # hourly / overlay across many years → WebGL keeps it smooth
    Scatter = go.Scattergl if big else go.Scatter
    if cmode == "Zone":
        for i, z in enumerate(ZONES):
            d = data[data["zone"] == z]
            if d.empty:
                continue
            col = COLORS[i % len(COLORS)]
            f = _fit_curve(d["temp"], d["value"])
            fig.add_trace(Scatter(x=d["temp"], y=d["value"], mode="markers", legendgroup=z,
                                  marker=dict(color=col, size=5, opacity=0.5), name=_leg(z, f)))
            if f:
                _add_fit_line(fig, f, col, z)
    elif cmode == "Year":
        for i, y in enumerate(sorted(data["year"].unique())):
            col = COLORS[i % len(COLORS)]
            d = data[data["year"] == y]
            f = _fit_curve(d["temp"], d["value"])
            fig.add_trace(Scatter(x=d["temp"], y=d["value"], mode="markers", legendgroup=str(y),
                                  marker=dict(color=col, size=5, opacity=0.5), name=_leg(str(y), f)))
            if f:
                _add_fit_line(fig, f, col, str(y))
    elif cmode == "Month":
        for m in sorted(data["month"].unique()):
            col = COLORS[(m - 1) % len(COLORS)]
            d = data[data["month"] == m]
            fig.add_trace(Scatter(x=d["temp"], y=d["value"], mode="markers", legendgroup=MONTHS[m],
                                  marker=dict(color=col, size=5, opacity=0.5), name=MONTHS[m]))
        f = _fit_curve(data["temp"], data["value"])
        if f:
            _add_fit_line(fig, f, "#111", "overall")
    else:
        f = _fit_curve(data["temp"], data["value"])
        fig.add_trace(Scatter(x=data["temp"], y=data["value"], mode="markers", legendgroup="overall",
                              marker=dict(color="#1f77b4", size=5, opacity=0.45), name=_leg("points", f)))
        if f:
            _add_fit_line(fig, f, "#111", "overall")
    if qband:  # optional P10–P90 band + P50 (conditional spread of load at each temperature)
        qb = quantile_bands(data["temp"], data["value"], width=2.0, qs=(0.1, 0.5, 0.9))
        if not qb.empty:
            fig.add_trace(go.Scatter(x=qb.index, y=qb["p90"], mode="lines", line=dict(width=0),
                                     showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=qb.index, y=qb["p10"], mode="lines", line=dict(width=0),
                                     fill="tonexty", fillcolor="rgba(70,70,70,0.18)", name="P10–P90"))
            fig.add_trace(go.Scatter(x=qb.index, y=qb["p50"], mode="lines", name="P50 (median)",
                                     line=dict(color="#222", width=2)))
    mlabel = "Demand" if demand_only else metric
    xlab = ("zone temperature (°F)" if overlay else
            f"{zone} temperature (°F)" if is_zone else "ERCOT load-weighted temperature (°F)")
    fig.update_layout(height=470, margin=dict(t=58, b=10), xaxis_title=xlab,
                      yaxis_title=f"{mlabel} (GW)", legend=dict(orientation="h", y=1.02),
                      hovermode="closest")

    # per-zone temperature sensitivity (its OWN Interval selector) — RENDERED at the bottom now.
    HOT, COLD = 70.0, 55.0

    def _arm_slope(sub: pd.DataFrame) -> tuple[float, float]:
        """(slope GW/°F, R²) of demand vs temp on one arm — NaN if too few/degenerate points."""
        if len(sub) < 5 or sub["t"].nunique() < 3 or sub["t"].var() == 0:
            return float("nan"), float("nan")
        s = sub["v"].cov(sub["t"]) / sub["t"].var() / 1000.0          # GW per °F
        return s, float(sub["t"].corr(sub["v"]) ** 2)

    def _zone_sensitivity(sens_key, years, m_lo, m_hi, hours_arg):
        """Per-zone Mean/Cool/Heat sensitivity — pooled over the chosen YEARS, restricted to a
        contiguous MONTH window [m_lo, m_hi] and an HOUR-of-day filter (this panel's own controls,
        fully decoupled from the scatter)."""
        rows = {}
        for z in ZONES:
            tcol, vcol = f"temp_{z}", f"demand_{z}"
            parts = []
            for y in years:
                p = lt_scatter(hist_panel(y, tuple(_AVAIL[y])), vcol, sens_key, temp_col=tcol,
                               hours=hours_arg)
                if not p.empty:
                    p = p[p.index.year == y]                            # drop tz-edge rows
                if not p.empty:
                    p = p[(p.index.month >= m_lo) & (p.index.month <= m_hi)]   # this panel's month window
                if not p.empty:
                    parts.append(p.rename(columns={tcol: "t", vcol: "v"}))
            if not parts:
                continue
            d = pd.concat(parts)
            cs, cr = _arm_slope(d[d["t"] >= HOT])
            hs, hr = _arm_slope(d[d["t"] <= COLD])
            rows[z] = {"Mean GW": d["v"].mean() / 1000.0, "Cool GW/°F": cs, "Cool R²": cr,
                       "Heat GW/°F": abs(hs) if hs == hs else float("nan"), "Heat R²": hr}
        return pd.DataFrame(rows).T

    # ======================= ROW 1 (2×2 top): scatter | weather-normalized load growth =======================
    # Growth controls sit in a thin control row ABOVE the figures (right half) so the two charts below
    # start at the SAME vertical level — the scatter is no longer pulled up by having no controls of its
    # own above it (the empty left half gives it matching height).
    _ctl_l, ctl_r = st.columns(2)
    with ctl_r:
        wn_c = st.columns(3)
        wn_zone = wn_c[0].selectbox("Zone (growth)", ["Whole ERCOT"] + ZONES, key="wn_zone",
                                    help="Weather-normalize the whole system or a single zone (its own "
                                         "demand vs its own temperature).")
        wn_method = wn_c[1].selectbox("Method", ["Quadratic", "Degree-day (CDD/HDD)"], key="wn_method",
                                      help="How each year's load↔temperature fit is built before "
                                      "normalizing: a **quadratic** in temperature, or the **degree-day "
                                      "model** `a + b·CDD + c·HDD` (separates baseline, cooling, heating).")
        wn_interval = wn_c[2].selectbox("Resolution", ["Daily", "Weekly", "Monthly"], index=1,
                                        key="wn_interval", help="Seasonal x-axis granularity: **Daily** "
                                        "(365 pts, smoothest), **Weekly** (52), or **Monthly** (12).")
    g_left, g_right = st.columns(2)
    with g_left:
        st.plotly_chart(style_fig(fig, "Load vs temperature — relationship & drift"),
                        use_container_width=True)
    with g_right:
        freq = {"Daily": "day", "Weekly": "week", "Monthly": "month"}[wn_interval]
        wtcol, wvcol = (("temp", "demand") if wn_zone == "Whole ERCOT"
                        else (f"temp_{wn_zone}", f"demand_{wn_zone}"))
        method = "dd" if wn_method.startswith("Degree") else "poly"
        daily_by_year = {}
        for y in sel_years:
            p = hist_panel(y, tuple(_AVAIL[y]))
            dd = lt_scatter(p, wvcol, "daily", temp_col=wtcol)    # [temp_col, value] daily
            if not dd.empty:
                daily_by_year[y] = dd.rename(columns={wtcol: "temp", wvcol: "demand"})
        curves, _normal = wn_seasonal_curves(daily_by_year, "demand", degree=2, method=method, freq=freq)
        znm = "ERCOT" if wn_zone == "Whole ERCOT" else wn_zone
        if curves.empty:
            st.info("Not enough cached history to weather-normalize — backfill more months "
                    "(`python -m src.backfill_history --force`).")
        else:
            curves = curves / 1000.0                              # MW → GW
            if freq == "day":                                     # map the period key → a date for the axis
                xref = [pd.Timestamp(dt.date(2023, 1, 1)) + pd.Timedelta(days=int(k) - 1) for k in curves.index]
                summer = range(182, 213)                          # ~Jul day-of-year
            elif freq == "month":
                xref = [pd.Timestamp(2023, int(k), 15) for k in curves.index]
                summer = [7]
            else:
                xref = [pd.Timestamp(dt.date.fromisocalendar(2023, int(k), 1)) for k in curves.index]
                summer = range(27, 32)                            # ~Jul week-of-year
            years_sorted = sorted(curves.columns)
            fig3 = go.Figure()
            for i, y in enumerate(years_sorted):
                fig3.add_trace(go.Scatter(x=xref, y=curves[y], mode="lines", name=str(y),
                                          line=dict(color=COLORS[i % len(COLORS)], width=2.4)))
            fig3.update_layout(height=470, margin=dict(t=58, b=10),
                               yaxis_title=f"weather-normalized {znm} demand (GW)",
                               legend=dict(orientation="h", y=1.02), hovermode="x unified")
            fig3.update_xaxes(tickformat="%b", dtick="M1")
            st.plotly_chart(style_fig(fig3, f"Weather-normalized {znm} load growth"),
                            use_container_width=True)

    # ===================== ROW 2 (2×2): Full-year vs month-window — all selected years =====================
    # Follows the dashboard's Zone / Load / Fit selectors (+ the battery toggle for whole-ERCOT). The window
    # compares YEARS (colour = year), so an 8-zone overlay would be unreadable → overlay falls back to whole.
    st.divider()
    st.markdown("**📅 Full-year vs selected month window** — each year's demand vs temperature: "
                "full data (left) vs a chosen month/hour window (right).")
    # Window options span the UNION of all selected years' cached months, so the trader can extend the
    # window to Aug/Sep/Dec on the full-history years (the data vendor has them). The newest year (2026)
    # only has ~through May cached, so it simply contributes fewer/no points in a later window.
    av_m = sorted(set().union(*[set(_AVAIL[y]) for y in sel_years])) if sel_years else list(range(1, 13))
    cut_lbls = [MONTHS[mn] for mn in av_m]
    # Trader hour-of-day blocks (LOCAL Central): each point becomes the block-mean of demand & temp.
    HOUR_BLOCKS = {"All hours (24)": None, "Overnight 1–6": {1, 2, 3, 4, 5, 6}, "Morning 7–9": {7, 8, 9},
                   "Midday 10–17": {10, 11, 12, 13, 14, 15, 16, 17},
                   "Evening peak 18–22": {18, 19, 20, 21, 22}, "Late 23–24": {23, 0}}
    ycc = st.columns([1.0, 1.4, 1.6])
    ytd_res = ycc[0].selectbox("Resolution", ["Hourly", "Daily", "Weekly", "Monthly"], index=1,
                               key="ytd_res", help="Aggregation of the scatter points — each is the mean "
                               "over this bucket (Hourly = every observation; coarser = fewer, smoother).")
    zone_opts = ["Whole ERCOT"] + ZONES
    zdef = zone if zone in ZONES else "Whole ERCOT"        # default to the top zone if a single one is picked
    ytd_zone = ycc[1].selectbox("Zone / station (this pair)", zone_opts, index=zone_opts.index(zdef),
                                key="ytd_zone", help="Drill this pair to one weather zone (its city = the "
                                "station) — demand vs that zone's OWN temperature — or the whole system. "
                                "Independent of the scatter's Zone selector; per-zone is demand-only.")
    hour_lbl = ycc[2].selectbox("Hours (local, trader block)", list(HOUR_BLOCKS), index=0, key="ytd_hours",
                                help="Keep only these local hours-of-day before aggregating — the classic "
                                "trading blocks (overnight / midday-solar / evening peak / late). Each point "
                                "becomes the block-mean, so you read the load–temp curve *for that block*.")
    hour_block = HOUR_BLOCKS[hour_lbl]
    # Range slider: clip every year to an ARBITRARY contiguous month window (drag either handle) — e.g.
    # Mar→May — applied identically to every year. Start handle at the first month ⇒ the classic YTD.
    seg = st.select_slider("Month window — clip every year to (drag either handle):", options=cut_lbls,
                           value=(cut_lbls[0], cut_lbls[-1]), key="ytd_seg",
                           help="Pick any contiguous span of months — e.g. Mar→May — applied identically "
                           "to every year for an apples-to-apples fit. Start at the first month = YTD.")
    seg_lo_lbl, seg_hi_lbl = seg
    start_month = av_m[cut_lbls.index(seg_lo_lbl)]
    end_month = av_m[cut_lbls.index(seg_hi_lbl)]
    ytd_res_key = ytd_res.lower()
    if ytd_zone == "Whole ERCOT":                          # this pair's own zone drives the columns
        ytd_tcol, ytd_vcol = "temp", {"Demand": "demand", "Net load": "net_load"}[metric]
        ytd_what = f"ERCOT {metric.lower()}"
        ytd_whole = True                                   # battery adj only applies to whole-ERCOT
    else:
        ytd_tcol, ytd_vcol, ytd_what = f"temp_{ytd_zone}", f"demand_{ytd_zone}", f"{ytd_zone} demand"
        ytd_whole = False
    if seg_lo_lbl == seg_hi_lbl:                            # window label used in titles/caption
        win_lbl = f"{seg_lo_lbl} only"
    elif start_month == av_m[0]:
        win_lbl = f"Jan → end of {seg_hi_lbl} (YTD)"
    else:
        win_lbl = f"{seg_lo_lbl} → {seg_hi_lbl}"
    hour_suffix = "" if hour_block is None else f" · {hour_lbl}"
    ytd_xlab = f"{ytd_zone if ytd_zone != 'Whole ERCOT' else 'ERCOT'} temperature (°F)"
    ytd_ylab = f"{ytd_what} (GW)"

    def _peryear_fig(frame: pd.DataFrame, title: str) -> go.Figure:
        f = go.Figure()
        for i, yy in enumerate(sorted(frame["year"].unique())):
            dY = frame[frame["year"] == yy]
            col = COLORS[i % len(COLORS)]
            ff = poly_fit(dY["temp"], dY["value"], deg) if deg else {}
            # R² shows in the legend (on the fit line); markers carry the legend only when no fit
            nm = f"{yy} · R²={ff['r2']:.2f}" if ff else str(yy)           # R² on the one entry per year
            f.add_trace(go.Scattergl(x=dY["temp"], y=dY["value"], mode="markers", legendgroup=str(yy),
                                     marker=dict(color=col, size=4, opacity=0.45), name=nm,
                                     showlegend=True))
            if ff:
                f.add_trace(go.Scatter(x=ff["xs"], y=ff["ys"], mode="lines", legendgroup=str(yy),
                                       showlegend=False, line=dict(color=col, width=2.4, dash="dot")))
        f.update_layout(height=400, margin=dict(t=58, b=10), title=title, xaxis_title=ytd_xlab,
                        yaxis_title=ytd_ylab, legend=dict(orientation="h", y=1.02), hovermode="closest")
        return f

    def _ytd_compute(years_list: list):
        """Build (full-year frame, window frame) for a set of years, or (None, None) if no data."""
        yrecs = []
        for y in years_list:
            p = hist_panel(y, tuple(_AVAIL[y]))
            if ytd_whole and y in bat_years and not p.empty and "battery_net" in p.columns:
                adj = p["battery_net"].clip(upper=0).fillna(0.0)
                p = p.assign(demand=p["demand"] + adj, net_load=p["net_load"] + adj)
            dd = (lt_scatter(p, ytd_vcol, ytd_res_key, temp_col=ytd_tcol, hours=hour_block)
                  if not p.empty else pd.DataFrame())
            if dd.empty:
                continue
            ts = pd.DatetimeIndex(dd.index)
            m = ts.year == y                       # drop tz-edge rows landing in an adjacent calendar year
            if not m.any():
                continue
            yrecs.append(pd.DataFrame({"temp": dd[ytd_tcol].to_numpy()[m],
                                       "value": dd[ytd_vcol].to_numpy()[m] / 1000.0,
                                       "year": y, "month": ts[m].month}))
        if not yrecs:
            return None, None
        yall = pd.concat(yrecs, ignore_index=True)
        yytd = yall[(yall["month"] >= start_month) & (yall["month"] <= end_month)]   # the chosen window
        return yall, yytd

    def _ytd_figs(yall: pd.DataFrame, yytd: pd.DataFrame) -> None:
        """Render the Full-year | Window figure pair (no table — that goes to the bottom)."""
        fcol, ycol = st.columns(2)
        with fcol:
            st.plotly_chart(style_fig(_peryear_fig(yall, f"Full year — all available data{hour_suffix}")),
                            use_container_width=True)
        with ycol:
            st.plotly_chart(style_fig(_peryear_fig(yytd, f"Window — {win_lbl}{hour_suffix}")),
                            use_container_width=True)

    def _ytd_table(yall: pd.DataFrame, yytd: pd.DataFrame) -> pd.DataFrame:
        """Per-year R²/weather table for a pair — returned (rendered later in Fitting statistics)."""
        ref = (int(round(float(yytd["temp"].median()))) if not yytd.empty and yytd["temp"].notna().any()
               else int(round(float(yall["temp"].median()))))
        srows = {}
        for yy in sorted(yall["year"].unique()):
            fy, ty = yall[yall["year"] == yy], yytd[yytd["year"] == yy]
            ff_full = poly_fit(fy["temp"], fy["value"], deg) if deg else {}
            ff_win = poly_fit(ty["temp"], ty["value"], deg) if deg else {}
            batt = 0.0                                      # daily-mean battery charging removed (GW)
            if ytd_whole and yy in bat_years:
                bp = hist_panel(yy, tuple(_AVAIL[yy]))
                if "battery_net" in bp.columns:
                    li = bp.index.tz_convert(DISPLAY_TZ)    # match the scatter: local month + hour block
                    bmask = (li.month >= start_month) & (li.month <= end_month)
                    if hour_block is not None:
                        bmask = bmask & li.hour.isin(list(hour_block))
                    bn = bp["battery_net"][bmask]
                    batt = float(-bn.clip(upper=0).fillna(0.0).mean() / 1000.0) if len(bn) else 0.0
            srows[str(yy)] = {
                "Win mean °F": round(float(ty["temp"].mean()), 1) if not ty.empty else float("nan"),
                "Win min–max °F": (f"{ty['temp'].min():.0f}–{ty['temp'].max():.0f}" if not ty.empty else "—"),
                "Full-yr R²": round(ff_full["r2"], 2) if ff_full else float("nan"),
                "Win R²": round(ff_win["r2"], 2) if ff_win else float("nan"),
                f"Win @{ref}°F (GW)": round(float(np.polyval(ff_win["coef"], ref)), 1) if ff_win else float("nan"),
                "Batt −GW removed": round(batt, 2),         # 0 unless this year is being adjusted
            }
        return pd.DataFrame(srows).T

    st.markdown("**① All selected years** — full year (left) vs the chosen window (right).")
    yall_all, yytd_all = _ytd_compute(sel_years)
    full_year_table = None
    if yall_all is None:
        st.info("No cached history for this selection.")
    else:
        _ytd_figs(yall_all, yytd_all)
        full_year_table = _ytd_table(yall_all, yytd_all)

    # ===================== ROW 3: per-station (per-zone) fits — each zone's own demand vs its own temp =====================
    ps_r2_df = ps_cmp_df = None                            # filled below; rendered in Fitting statistics
    with st.expander("🔬 Per-station fits — each zone's *actual* demand vs its *own* temperature, "
                     "with the fit curve + R²", expanded=True):
        st.caption("**Independent controls** — frequency, month span, hour range & years to show "
                   "(separate from the panels above).")
        psc = st.columns([1.0, 1.5, 1.6])
        ps_res = psc[0].selectbox("Resolution", ["Hourly", "Daily", "Weekly", "Monthly"], index=1,
                                  key="ps_res", help="Point aggregation: Hourly = every kept hour; coarser = "
                                  "the block-mean over the chosen hours per day/week/month.")
        ps_all_m = sorted(set().union(*[set(_AVAIL[y]) for y in sel_years])) if sel_years else list(range(1, 13))
        ps_mlbls = [MONTHS[m] for m in ps_all_m]
        ps_seg = psc[1].select_slider("Months (drag either handle)", options=ps_mlbls,
                                      value=(ps_mlbls[0], ps_mlbls[-1]), key="ps_seg",
                                      help="Restrict to a contiguous month span (e.g. Jun→Aug = summer), "
                                      "pooled across the selected years.")
        ps_h = psc[2].slider("Hours (local Central, from → to)", min_value=0, max_value=23, value=(0, 23),
                             key="ps_hours", help="Double-ended hour-of-day filter — pick from-hour → to-hour "
                             "(0 = midnight, 23 = 11 pm). e.g. 18→22 = evening peak, 0→6 = overnight. Each "
                             "point becomes the mean over those hours before aggregating.")
        pyc = st.columns([2.4, 1.3])
        ps_years = pyc[0].multiselect("Years to show", options=sorted(sel_years), default=sorted(sel_years),
                                      key="ps_years", help="This panel's independent year filter — which years "
                                      "to overlay here (one fit curve per year). Does not change the top Years "
                                      "selector or the month/hour windows.")
        ps_method = pyc[1].selectbox("Method",
                                     ["Quadratic", "Linear", "Cubic", "Piecewise", "Auto (best fit)"],
                                     index=0, key="ps_fit", help="How each year's points are fit. **Quadratic** "
                                     "= robust default for the U-shape; **Piecewise** = balance-point HDD/CDD "
                                     "(independent heating & cooling slopes meeting at a balance point); "
                                     "**Cubic** rarely beats quadratic; **Linear** can't follow the U; **Auto** "
                                     "= best per zone by adjusted R². Comparison is in Fitting statistics.")
        ps_key = ps_res.lower()
        ps_m_lo, ps_m_hi = ps_all_m[ps_mlbls.index(ps_seg[0])], ps_all_m[ps_mlbls.index(ps_seg[1])]
        ps_hours = set(range(ps_h[0], ps_h[1] + 1))
        ps_hours_arg = None if ps_hours == set(range(24)) else ps_hours      # None = no filter (all 24 h)
        yr_color = {yy: COLORS[i % len(COLORS)] for i, yy in enumerate(sorted(sel_years))}  # stable per cal-year
        FIT_DEG = {"Linear": 1, "Quadratic": 2, "Cubic": 3}
        # Tie-break preference among near-equal fits: robust/physical first (cubic is tail-overfit-prone,
        # never genuinely beats quadratic on cross-validation, so it's least preferred above linear).
        FIT_PREF = {"Quadratic": 0, "Piecewise": 1, "Cubic": 2, "Linear": 3}

        def _fit(xv, yv_, method):                           # one fit → (dict, n_params); {} if too few pts
            if method == "Piecewise":
                ff = seg_fit(xv, yv_)
                return ff, ff.get("p", 4)
            d = FIT_DEG[method]
            return poly_fit(xv, yv_, d), d

        if not ps_years:
            st.info("Pick at least one year in **Years to show** to draw the per-station fits.")
        else:
            titles, zd, r2_rows, fit_cmp = [], {}, {}, {}
            span_lo = span_hi = None                         # actual date span of the shown, filtered data
            npts = 0
            for z in ZONES:
                tcol, vcol = f"temp_{z}", f"demand_{z}"
                parts = []
                for y in sorted(ps_years):                   # only the SHOWN years
                    pp = lt_scatter(hist_panel(y, tuple(_AVAIL[y])), vcol, ps_key, temp_col=tcol,
                                    hours=ps_hours_arg)
                    if not pp.empty:                         # drop tz-edge rows landing in an adjacent local
                        pp = pp[pp.index.year == y]          # year, then apply this panel's own month window
                    if not pp.empty:
                        pp = pp[(pp.index.month >= ps_m_lo) & (pp.index.month <= ps_m_hi)]
                    if not pp.empty:
                        parts.append(pp)
                if not parts:
                    zd[z] = None
                    titles.append(z)
                    r2_rows[z] = {}
                    fit_cmp[z] = {}
                    continue
                d = pd.concat(parts)
                lo, hi = d.index.min(), d.index.max()
                span_lo = lo if span_lo is None else min(span_lo, lo)
                span_hi = hi if span_hi is None else max(span_hi, hi)
                npts = max(npts, len(d))
                x, yv = d[tcol].to_numpy(dtype=float), d[vcol].to_numpy(dtype=float) / 1000.0
                yr = d.index.year.to_numpy()
                # fit-method comparison on the POOLED points (adjusted R² so complexity is penalised)
                cmp, pooled = {}, {}
                for mth in ["Linear", "Quadratic", "Cubic", "Piecewise"]:
                    ff, p = _fit(x, yv, mth)
                    pooled[mth] = ff
                    cmp[mth] = round(adj_r2(ff["r2"], ff["n"], p), 3) if ff else float("nan")
                valid = {m: v for m, v in cmp.items() if v == v}        # drop NaN
                if valid:                                               # among fits within 0.005 adj-R² of the
                    top = max(valid.values())                           # top, take the most-preferred (robust/
                    near = [m for m, v in valid.items() if v >= top - 0.005]   # physical) → not cubic-by-noise
                    best_m = min(near, key=lambda m: FIT_PREF[m])
                else:
                    best_m = "Quadratic"
                pf = pooled["Piecewise"]
                fit_cmp[z] = {**cmp, "Best": best_m, "BalPt°F": (round(pf["tbp"], 0) if pf else float("nan"))}
                use_method = best_m if ps_method == "Auto (best fit)" else ps_method
                fits = {}                                    # year -> fit dict (one curve per year, chosen method)
                for yy in sorted(ps_years):
                    msk = yr == yy
                    if msk.sum() <= 4:                       # need >4 points for any candidate
                        continue
                    fyy, _p = _fit(x[msk], yv[msk], use_method)
                    if fyy:                                  # {} if degenerate (zero x-spread)
                        fits[yy] = fyy
                zd[z] = (x, yv, yr, fits)
                titles.append(z)                             # zone name only — R² moved to the table below
                r2_rows[z] = {yy: round(fits[yy]["r2"], 2) for yy in fits}
            if span_lo is None:                              # years selected, but no data in this window
                st.info("No data for the selected years in this month/hour window — widen the **Months** "
                        "or **Hours** range, or add a year in **Years to show**.")
            else:
                _freq_word = {"Hourly": "hour", "Daily": "day", "Weekly": "week", "Monthly": "month"}[ps_res]
                hr_txt = "all 24 h" if ps_hours_arg is None else f"hours {ps_h[0]:02d}→{ps_h[1]:02d}"
                mo_txt = ("all cached months" if (ps_m_lo == ps_all_m[0] and ps_m_hi == ps_all_m[-1])
                          else f"{MONTHS[ps_m_lo]}→{MONTHS[ps_m_hi]}")
                st.markdown(
                    f"⏱️ **Frequency:** {ps_res} (one point per **{_freq_word}**, **{hr_txt}** mean) · "
                    f"**Months:** {mo_txt} · **Date span:** {span_lo:%Y-%m-%d} → {span_hi:%Y-%m-%d} · "
                    f"**Years shown:** {', '.join(str(y) for y in sorted(ps_years))} (≈ {npts:,} pts/zone).")
                psfig = make_subplots(rows=2, cols=4, subplot_titles=titles,
                                      horizontal_spacing=0.045, vertical_spacing=0.13)
                seen_yr = set()                              # emit each year's legend swatch once (where it has pts)
                for i, z in enumerate(ZONES):
                    if zd[z] is None:
                        continue
                    x, yv, yr, fits = zd[z]
                    r, c = i // 4 + 1, i % 4 + 1
                    for yy in sorted(ps_years):
                        msk = yr == yy
                        if msk.any():                        # faint context points for this year
                            show = yy not in seen_yr
                            if show:
                                seen_yr.add(yy)
                            psfig.add_trace(go.Scattergl(x=x[msk], y=yv[msk], mode="markers", name=str(yy),
                                            legendgroup=str(yy), showlegend=show,
                                            marker=dict(color=yr_color[yy], size=3, opacity=0.5)), row=r, col=c)
                        f = fits.get(yy)
                        if f:                                # per-year fit curve, solid, colour-matched
                            psfig.add_trace(go.Scatter(x=f["xs"], y=f["ys"], mode="lines", legendgroup=str(yy),
                                            showlegend=False, line=dict(color=yr_color[yy], width=2)), row=r, col=c)
                psfig.update_layout(height=700, margin=dict(t=104, b=10),
                                    legend=dict(orientation="h", yanchor="bottom", y=1.06,
                                                title_text="Year", itemsizing="constant"))
                psfig.update_xaxes(title_text="°F", row=2)
                psfig.update_yaxes(title_text="GW", col=1)
                psfig.update_annotations(font_size=15)       # enlarge the per-zone subplot titles
                st.plotly_chart(style_fig(psfig, legend_size=16), use_container_width=True)
                r2_df = pd.DataFrame(r2_rows).T.reindex(ZONES).reindex(columns=sorted(ps_years))
                cmp_df = (pd.DataFrame(fit_cmp).T.reindex(ZONES)
                          .reindex(columns=["Linear", "Quadratic", "Cubic", "Piecewise", "Best", "BalPt°F"]))
                ps_r2_df, ps_cmp_df = r2_df, cmp_df

    # ===================== ROW 4 (2×2): Full-year vs window — 2025 & 2026 only =====================
    st.divider()
    yr_2526 = [y for y in sel_years if y in (2025, 2026)]
    pair2526_table = None
    if not yr_2526:
        st.caption("**② 2025 & 2026 only** — select 2025 and/or 2026 in the top **Years** to show the "
                   "battery-era pair here.")
    else:
        st.markdown("**② 2025 & 2026 only** — full year (left) vs the chosen window (right), "
                    "battery-era years.")
        yall_b, yytd_b = _ytd_compute(yr_2526)
        if yall_b is None:
            st.info("No cached 2025/2026 history for this selection.")
        else:
            _ytd_figs(yall_b, yytd_b)
            pair2526_table = _ytd_table(yall_b, yytd_b)

    # ===================== ROW 5: ❄️ Feb 2021 Winter Storm Uri — counterfactual case study (EIA + ERA5) =====================
    st.divider()
    with st.expander("❄️ Feb 2021 Winter Storm Uri — what was the *real* demand? (EIA + ERA5 case study)"):
        render_uri_panel()

    # ===================== BOTTOM · supplementary: per-zone load time series =====================
    st.divider()
    st.markdown("**📉 Per-zone load — time series** — raw demand over the cached history.")
    tv = st.columns([2.6, 1.7])
    tv_zones = tv[0].multiselect("Zones", ["Whole ERCOT"] + ZONES, default=["Whole ERCOT"],
                                 key="tv_zones", help="Pick one or more zones to overlay (tags) — add "
                                 "'Whole ERCOT' and/or any weather zones.")
    tv_int = tv[1].selectbox("Resolution", ["Hourly", "Daily", "Weekly", "Monthly"], index=1,
                             key="tv_int", help="Each point is the mean over this bucket "
                             "(TradingView-style bar size). Hourly = every observation.")
    panels = [hist_panel(y, tuple(_AVAIL[y])) for y in sel_years]
    panels = [p for p in panels if not p.empty]
    if not tv_zones:
        st.info("Pick at least one zone to plot.")
    elif not panels:
        st.info("No cached history for the selected years.")
    else:
        big = pd.concat(panels).sort_index()
        big = big[~big.index.duplicated(keep="last")].tz_convert(DISPLAY_TZ)
        series = {("ERCOT" if z == "Whole ERCOT" else z): ("demand" if z == "Whole ERCOT" else f"demand_{z}")
                  for z in tv_zones}
        rule = {"Daily": "D", "Weekly": "W", "Monthly": "MS"}.get(tv_int)
        traces, total = [], 0
        for i, (nm, col) in enumerate(series.items()):
            if col not in big.columns:
                continue
            s = big[col] / 1000.0                                  # GW
            s = s.dropna() if rule is None else s.resample(rule).mean().dropna()   # Hourly = raw
            total += len(s)
            traces.append((nm, s, COLORS[i % len(COLORS)]))
        TVScatter = go.Scattergl if total > 4000 else go.Scatter   # WebGL for dense hourly series
        ftv = go.Figure()
        for nm, s, c in traces:
            ftv.add_trace(TVScatter(x=s.index, y=s.values, mode="lines", name=nm,
                                    line=dict(color=c, width=1.3)))
        ylab = "demand (GW)" if len(traces) != 1 else f"{traces[0][0]} demand (GW)"
        ftv.update_layout(height=460, margin=dict(t=58, b=10), yaxis_title=ylab,
                          legend=dict(orientation="h", y=1.02), hovermode="x unified")
        ftv.update_xaxes(rangeslider_visible=False, rangeselector=dict(buttons=[
            dict(count=7, label="1w", step="day", stepmode="backward"),
            dict(count=1, label="1m", step="month", stepmode="backward"),
            dict(count=3, label="3m", step="month", stepmode="backward"),
            dict(count=6, label="6m", step="month", stepmode="backward"),
            dict(count=1, label="1y", step="year", stepmode="backward"),
            dict(step="all", label="all")]))
        st.plotly_chart(style_fig(ftv, "Per-zone load — time series"), use_container_width=True)

    # ===================== BOTTOM · per-zone temperature sensitivity (standalone, independent filters) =====================
    st.divider()
    with st.expander("🗺️ Per-zone temperature sensitivity — *where* heat becomes load "
                     "(standalone: independent period & hour filters)", expanded=True):
        st.caption("**Standalone controls** — own year / month / hour filters, decoupled from the "
                   "scatter. Slope = GW of demand per +1 °F.")
        zsc = st.columns([1.2, 1.2, 1.6])
        map_metric = zsc[0].selectbox("Map", ["Cooling", "Heating", "Mean demand"],
                                      key="zone_sens_metric", help="Colour the zones by cooling "
                                      "sensitivity (summer AC — the headline), heating sensitivity "
                                      "(winter), or mean demand.")
        sens_res = zsc[1].selectbox("Resolution", ["Hourly", "Daily", "Weekly", "Monthly", "Yearly"],
                                    index=1, key="zone_sens_res", help="Point aggregation for the per-zone "
                                    "response. Coarse (Monthly/Yearly) may be unfittable → blank.")
        zs_years = zsc[2].multiselect("Years", yrs, default=yrs, key="zs_years",
                                      help="Independent year pool for this map — does NOT follow the "
                                      "scatter's Years selector.")
        zs_all_m = (sorted(set().union(*[set(_AVAIL[y]) for y in zs_years])) if zs_years
                    else list(range(1, 13)))
        zs_mlbls = [MONTHS[m] for m in zs_all_m]
        zsc2 = st.columns(2)
        zs_seg = zsc2[0].select_slider("Period — months (drag either handle)", options=zs_mlbls,
                                       value=(zs_mlbls[0], zs_mlbls[-1]), key="zs_seg",
                                       help="Restrict the map to a contiguous month window — e.g. Jun→Aug "
                                       "= summer cooling, Dec→Feb = winter heating.")
        zs_h = zsc2[1].slider("Time interval — hours (local Central, from → to)", min_value=0,
                              max_value=23, value=(0, 23), key="zs_hours", help="Double-ended hour-of-day "
                              "filter (0 = midnight, 23 = 11 pm). e.g. 18→22 = evening peak — see *where* "
                              "the on-peak heat sensitivity bites.")
        zs_m_lo, zs_m_hi = zs_all_m[zs_mlbls.index(zs_seg[0])], zs_all_m[zs_mlbls.index(zs_seg[1])]
        zs_hours = set(range(zs_h[0], zs_h[1] + 1))
        zs_hours_arg = None if zs_hours == set(range(24)) else zs_hours
        zs_hr_txt = "all 24 h" if zs_hours_arg is None else f"hours {zs_h[0]:02d}→{zs_h[1]:02d}"
        zs_mo_txt = ("all cached months" if (zs_m_lo == zs_all_m[0] and zs_m_hi == zs_all_m[-1])
                     else f"{MONTHS[zs_m_lo]}→{MONTHS[zs_m_hi]}")
        if not zs_years:
            st.info("Pick at least one year for the sensitivity map.")
            ztab = pd.DataFrame()
        else:
            ztab = _zone_sensitivity(sens_res.lower(), sorted(zs_years), zs_m_lo, zs_m_hi, zs_hours_arg)
            if ztab.empty:
                st.info("No per-zone data for this window — widen the **Period**/**hours** or add a year "
                        "(or run `python -m src.backfill_history --force` if columns aren't cached).")
            else:
                st.caption(f"Window: **{zs_mo_txt}** · **{zs_hr_txt}** · years "
                           f"{', '.join(str(y) for y in sorted(zs_years))}.")
                mcol = {"Cooling": "Cool GW/°F", "Heating": "Heat GW/°F", "Mean demand": "Mean GW"}[map_metric]
                is_sens = map_metric != "Mean demand"
                unit = "GW/°F" if is_sens else "GW"
                vfmt = "{:.2f}" if is_sens else "{:.1f}"
                zdict = {z: v for z, v in ztab[mcol].items() if v == v}
                if not zdict:
                    st.info(f"No **{map_metric}** signal in this window — cooling needs hours ≥ 70 °F, "
                            "heating needs ≤ 55 °F. Widen the Period/hours or switch the Map metric.")
                else:
                    st.plotly_chart(style_fig(build_demand_map(zdict,
                                    f"{map_metric} sensitivity" if is_sens else map_metric,
                                    colorbar_title=unit, unit=unit, value_fmt=vfmt, height=470)),
                                    use_container_width=True)

    # ===================== BOTTOM · 📊 Fitting statistics (all tables, clearly labeled) =====================
    st.divider()
    st.subheader("📊 Fitting statistics")
    st.caption("Each table names the **figure** it belongs to (↳ matches the chart's title/emoji above) "
               "and the **fit function** behind its numbers, so every stat stays tied to its chart.")

    st.markdown(f"**↳ Load vs temperature** (Row 1, left) — overall fit & coverage · fit function: "
                f"**{fit_kind}** (R² across all shown points; per-group R² is on the scatter legend).")
    mc = st.columns(4)
    mc[0].metric("Points", f"{len(data):,}")
    mc[1].metric("Temp range", f"{data['temp'].min():.0f}–{data['temp'].max():.0f} °F")
    mc[2].metric(f"{mlabel} range", f"{data['value'].min():.0f}–{data['value'].max():.0f} GW")
    fov = ({} if (overlay or not deg) else poly_fit(data["temp"], data["value"], deg))
    mc[3].metric("Overall R²", f"{fov['r2']:.2f}" if fov else "—",
                 help="Fit quality across all shown points (per-group R² is in the scatter legend; "
                      "n/a in overlay since zones have different baselines).")

    if not ztab.empty:
        st.markdown(f"**↳ 🗺️ Per-zone temperature sensitivity** (map above) — per-zone response "
                    f"({sens_res.lower()} · {zs_mo_txt} · {zs_hr_txt}) · fit function: **linear arm "
                    "slopes** — GW per +1 °F + R² on the cooling arm (≥ 70 °F) and heating arm (≤ 55 °F).")
        order = ztab.sort_values("Cool GW/°F", ascending=False)
        vmax = float(ztab["Cool GW/°F"].abs().max() or 1.0)
        sty = (order.style.format({"Mean GW": "{:.1f}", "Cool GW/°F": "{:+.2f}", "Cool R²": "{:.2f}",
                                   "Heat GW/°F": "{:.2f}", "Heat R²": "{:.2f}"})
               .map(lambda v: _temp_bg(v, 0, vmax) if pd.notna(v) else "", subset=["Cool GW/°F"]))
        st.dataframe(sty, use_container_width=True)

    if full_year_table is not None:
        st.markdown(f"**↳ 📅 ① All selected years** (full-year vs window pair) — per-year fit function: "
                    f"**{fit_kind}**; columns = R² (both panels), the window's temperature, and the "
                    "windowed fit at a reference °F.")
        st.dataframe(full_year_table, use_container_width=True)

    if pair2526_table is not None:
        st.markdown(f"**↳ 📅 ② 2025 & 2026 only** (full-year vs window pair) — per-year fit function: "
                    f"**{fit_kind}**; same columns, battery-era years (`Batt −GW removed` = charging "
                    "stripped from each adjusted year).")
        st.dataframe(pair2526_table, use_container_width=True)

    if ps_r2_df is not None:
        st.markdown(f"**↳ 🔬 Per-station fits** (2×4 grid above) — R² per zone × year · fit function: "
                    f"**{ps_method}**"
                    + (" (per-zone **Best**, see next table)" if ps_method.startswith("Auto") else "")
                    + ". Blank = too few points / too flat to fit.")
        st.dataframe(ps_r2_df, use_container_width=True)

    if ps_cmp_df is not None:
        st.markdown("**↳ 🔬 Per-station fits** (2×4 grid above) — fit-function comparison: adjusted R² "
                    "for **Linear / Quadratic / Cubic / Piecewise** per zone; **Best** = the chosen model "
                    "(used when Method = Auto), **BalPt°F** = the piecewise heating/cooling balance point.")
        st.dataframe(ps_cmp_df, use_container_width=True)
    st.stop()

# ---- StormVista temperature map: per-county by nearest station (replaces Open-Meteo) ---------
@st.cache_data(ttl=3600, show_spinner="Loading StormVista temperatures…")
def load_sv_temps():
    """StormVista station daily high/low + coordinates + 30-yr ERA5 normals (one fetch set).
    Returns (temps_long, station_meta, normals) or None if no key."""
    import src.stormvista as sv
    if not sv.is_configured():
        return None
    return sv.region_daily_temps(), sv.station_meta(), sv.station_normals()


def _f_to_unit(v: float, unit: str, is_delta: bool = False) -> float:
    """°F value → display unit. For a *delta* (anomaly) only the scale applies, not the −32 offset."""
    if unit == "°C":
        return v * 5.0 / 9.0 if is_delta else (v - 32.0) * 5.0 / 9.0
    return v


def sv_county_frame(market: str, day: str, view: str, unit: str,
                    temps, meta, normals) -> pd.DataFrame:
    """Per-county [fips, zone, station, value] for `market` on forecast `day`: value = that day's
    high/low temperature, or the anomaly vs the 30-yr ERA5 normal — each county takes its NEAREST
    StormVista station."""
    recs = market_counties(market, counties_geojson())
    zones = MARKETS[market]["zones"]
    tday = temps[temps["date"] == day].set_index("station")
    cand = meta.set_index("Station")
    cand = cand.loc[cand.index.intersection(tday.index)].dropna(subset=["Latitude", "Longitude"])
    slat = cand["Latitude"].to_numpy(); slon = cand["Longitude"].to_numpy(); sid = cand.index.to_numpy()
    mmdd = f"{int(day[5:7]):02d}-{int(day[8:10]):02d}"
    norm_hi = normals[normals["Date"] == mmdd].set_index("Station")["tmax"]
    anom = view.startswith("Anomaly")
    rows = []
    for fips, la, lo in recs:
        st_ = sid[int(((slat - la) ** 2 + (slon - lo) ** 2).argmin())]
        hi, lo_t = tday.loc[st_, "tmax"], tday.loc[st_, "tmin"]
        if anom:
            raw = hi - norm_hi.get(st_, float("nan"))
            raw = raw if (raw == raw and abs(raw) <= 35) else float("nan")  # drop bad/missing normals
            val = _f_to_unit(raw, unit, is_delta=True)
        else:
            val = _f_to_unit(lo_t if view.startswith("Low") else hi, unit)
        rows.append((fips, nearest_zone(la, lo, zones), st_, val))
    return pd.DataFrame(rows, columns=["fips", "zone", "station", "value"])


def build_sv_map(cdf: pd.DataFrame, view: str, unit: str, market: str) -> go.Figure:
    """Per-county choropleth of the StormVista value (high/low = Turbo, anomaly = diverging)."""
    counties = counties_geojson()
    if view.startswith("Anomaly"):
        m = max(float(cdf["value"].abs().quantile(0.95)), 1.0)
        cs, zmin, zmax, zmid, cbar = DIVERGING, -m, m, 0, f"Δ ({unit})"
    else:
        cs, zmin, zmax, zmid = "Turbo", cdf["value"].min(), cdf["value"].max(), None
        cbar = f"Temp ({unit})"
    fig = go.Figure(go.Choropleth(
        geojson=counties, locations=cdf["fips"], z=cdf["value"], featureidkey="id",
        colorscale=cs, zmin=zmin, zmax=zmax, zmid=zmid, customdata=cdf[["zone", "station"]].to_numpy(),
        hovertemplate="%{customdata[0]} · stn %{customdata[1]}<br>%{z:.1f}" + unit + "<extra></extra>",
        marker_line_width=0, colorbar_title=cbar))
    olats, olons = zone_outline(market)
    fig.add_trace(go.Scattergeo(lat=olats, lon=olons, mode="lines",
                  line=dict(width=1.6, color="#000"), hoverinfo="skip", showlegend=False))
    zs = MARKETS[market]["zones"]
    fig.add_trace(go.Scattergeo(lat=[v[0] for v in zs.values()], lon=[v[1] for v in zs.values()],
                  text=list(zs.keys()), mode="text", textfont=dict(size=11, color="#000", family="Arial Black"),
                  hoverinfo="skip", showlegend=False))
    fig.update_geos(scope="usa", resolution=110, showsubunits=True, subunitcolor="#000",
                    subunitwidth=1.0, showcountries=True, countrycolor="#000",
                    center=dict(lat=MARKETS[market]["center"][0], lon=MARKETS[market]["center"][1]),
                    projection_scale=MARKETS[market]["scale"])
    fig.update_layout(height=620, margin=dict(t=10, b=10, l=0, r=0))
    return fig


# ===================== DASHBOARD 1: Live monitor =====================
# ---- Figure 1: anomaly map (historical difference) ----
# Controls: market + view + unit only. "now" is a single canonical source (GFS Seamless);
# the historical reference is ERA5 — so this figure is about temperature-vs-the-past, not
# about comparing forecast models (that lives in Figure 2 below).
# Hybrid: StormVista forecast views (High/Low/Anomaly) + Open-Meteo lookback views (vs Yesterday …
# vs 1 year ago, vs 10-yr normal) which need the ERA5 *archive* StormVista's forward feed lacks.
sv_t = load_sv_temps()
SV_VIEWS = ["High (°)", "Low (°)", "Anomaly vs normal (high)"]
OM_VIEWS = [v for v in LOOKBACKS if LOOKBACKS[v] > 0] + [CLIM_VIEW]   # vs Yesterday … vs 1yr · vs normal
view_opts = (SV_VIEWS if sv_t is not None else []) + OM_VIEWS
c = st.columns([1.3, 1.7, 1.0, 0.7])
market = c[0].selectbox("Market", list(MARKETS), format_func=lambda k: MARKETS[k]["label"])
view = c[1].selectbox("View", view_opts,
                      help="Forecast views (High/Low/Anomaly) come from StormVista; the 'vs …' "
                           "lookbacks and the 10-yr normal come from Open-Meteo's ERA5 archive.")
unit = c[3].radio("Unit", ["°F", "°C"], horizontal=True)

if view in SV_VIEWS:
    temps, meta, normals = sv_t
    days = sorted(temps["date"].unique())
    di = c[2].slider("Forecast day", 1, len(days), 1, key="svmap_day")
    day = days[di - 1]
    st.subheader(f"① {MARKETS[market]['label']} — {view} · {day}")
    st.caption("Per-county forecast high via the nearest StormVista station; anomaly vs the 30-yr ERA5 "
               "normal. Red = warmer.")
    try:
        cdf = sv_county_frame(market, day, view, unit, temps, meta, normals)
        map_col, tbl_col = st.columns([2.4, 1])
        with map_col:
            st.plotly_chart(style_fig(build_sv_map(cdf, view, unit, market)), use_container_width=True)
        with tbl_col:
            st.markdown("**Per-zone (county mean)**")
            zt = (cdf.groupby("zone")["value"].mean().round(1).reset_index()
                  .rename(columns={"value": view.split(" (")[0]}))
            st.dataframe(zt, use_container_width=True, hide_index=True)
            st.caption(f"{cdf['station'].nunique()} StormVista stations cover {len(cdf)} counties.")
        cc = cdf.dropna(subset=["value"])
        if not cc.empty:
            hot = cc.loc[cc["value"].idxmax()]
            if view.startswith("Anomaly"):
                st.caption(f"Forecast for **{day}** · most anomalous zone: **{hot['zone']} "
                           f"{hot['value']:+.1f}{unit}** (station {hot['station']}).")
            else:
                st.caption(f"Forecast for **{day}** · hottest zone: **{hot['zone']} "
                           f"{hot['value']:.1f}{unit}** (station {hot['station']}).")
    except Exception as exc:
        st.error(f"Could not load StormVista temperature: {exc}")
else:
    # Open-Meteo lookback / climatology (year-over-year etc.) — needs the ERA5 archive.
    st.subheader(f"① {MARKETS[market]['label']} — {view}")
    st.caption("Per-county change vs a past date / 10-yr normal (now = GFS, reference = ERA5). "
               "Red = warmer, blue = cooler.")
    try:
        cdf, tmeta = load_county_temp(market, view, unit, FORECAST_MODEL)
        is_clim = "clim_years" in tmeta
        map_col, tbl_col = st.columns([2.4, 1])
        with map_col:
            st.plotly_chart(style_fig(build_map(cdf, tmeta, market)), use_container_width=True)
        with tbl_col:
            st.markdown("**Per-zone (county mean)**")
            st.dataframe(zone_table(cdf, tmeta["mode"]), use_container_width=True, hide_index=True)
            st.caption("± = inter-annual std (ERA5 normal)" if is_clim
                       else "± = spatial spread across the zone's counties")
        if is_clim:
            y0, y1, ny = tmeta["clim_years"]
            cc = cdf.dropna(subset=["diff"])
            warm = cc.loc[cc["diff"].idxmax()]
            st.caption(f"Anomaly vs the {ny}-yr ERA5 normal for {tmeta['now']:%m-%d %H:%MZ} ({y0}–{y1}) · "
                       f"{len(cdf)} counties. Most anomalous: **{warm['zone']} {warm['diff']:+.1f}{unit}** "
                       f"(normal {warm['past']:.1f}±{warm['pm']:.1f}{unit}).")
        elif tmeta["mode"] == "diff":
            cc = cdf.dropna(subset=["diff"])
            hot, cold = cc.loc[cc["diff"].idxmax()], cc.loc[cc["diff"].idxmin()]
            st.caption(f"Now {tmeta['now']:%Y-%m-%d %H:%MZ} vs {tmeta['past']:%Y-%m-%d %H:%MZ} · "
                       f"{len(cdf)} counties. Warmest move **{hot['zone']} {hot['diff']:+.1f}{unit}**, "
                       f"coolest **{cold['zone']} {cold['diff']:+.1f}{unit}**.")
    except Exception as exc:
        msg = str(exc)
        if "429" in msg:
            st.warning("Open-Meteo rate limit hit (per-county pulls are quota-heavy). Wait ~1 minute, "
                       "then re-select — views cache for 30 min. (StormVista forecast views are unaffected.)")
        elif any(k in msg for k in ("ConnectionPool", "Max retries", "timed out", "Timeout", "Connection")):
            st.warning("Open-Meteo's ERA5 archive is slow/unreachable right now (auto-retried 3×). "
                       "Try this lookback view again in a few seconds — the StormVista forecast views "
                       "are unaffected.")
        else:
            st.error(f"Could not load temperature: {exc}")

# ---- Per-zone demand (spatial) — the weather-driven demand value by ERCOT zone ----
st.subheader("🗺️ ERCOT forecast demand by zone")
zc = st.columns([1, 1.6, 3])
dz_metric = zc[0].radio("Demand", ["Peak", "Mean"], horizontal=True,
                        help="That day's peak (what the desk quotes) or its daily-mean demand.")
try:
    zframe = load_zone_demand_frame()
except Exception as exc:
    zframe = None
    if "DoLogin" in str(exc) or "Too many" in str(exc):
        st.info("Meteologica login is rate-limited (cooling down) — zone demand appears once the "
                "token refreshes.")
    else:
        st.warning(f"Could not load per-zone demand: {exc}")
zdem, target = {}, None
if zframe is not None and not zframe.empty:
    dates = sorted(set(zframe.index.date))
    full = [d for d in dates if (zframe.index.date == d).sum() >= 20]  # drop partial first/last days
    dlist = full or dates
    if len(dlist) > 1:
        di = zc[1].slider("Forecast day ahead", 1, len(dlist), 1, key="zonedemand_day",
                          help="Which forecast day to map (1 = the next full day) — slide it to watch "
                               "the demand picture evolve as the weather changes.")
    else:
        di = 1
    target = dlist[di - 1]
    day_df = zframe[zframe.index.date == target]
    agg = day_df.max() if dz_metric == "Peak" else day_df.mean()
    zdem = (agg / 1000.0).round(2).to_dict()
if zdem and target is not None:
    mlabel = "peak" if dz_metric == "Peak" else "mean"
    st.plotly_chart(style_fig(build_demand_map(zdem, mlabel)), use_container_width=True)
    tot = sum(zdem.values())
    top = sorted(zdem.items(), key=lambda kv: -kv[1])[:3]
    st.caption(
        f"**ERCOT demand by weather zone** (GW, daily {mlabel}, {target:%a %b %d}) — total ≈ **{tot:.0f} "
        "GW**; biggest: " + ", ".join(f"**{z} {v:.1f}**" for z, v in top) + ". Source: Meteologica.")

    # full table: every forecast day (rows) × zone (cols), the daily peak/mean demand in GW
    rows = {}
    for d in dlist:
        dd = zframe[zframe.index.date == d]
        rows[pd.Timestamp(d).strftime("%a %m/%d")] = (dd.max() if dz_metric == "Peak" else dd.mean()) / 1000.0
    full_tbl = pd.DataFrame(rows).T                       # index = forecast day, columns = zone
    full_tbl["TOTAL"] = full_tbl.sum(axis=1)
    zcols = sorted([c for c in full_tbl.columns if c != "TOTAL"], key=lambda z: -full_tbl[z].mean())
    full_tbl = full_tbl[zcols + ["TOTAL"]]
    st.markdown(f"**All forecast days × zone — daily {mlabel} demand (GW)**")
    _zmin = float(full_tbl[zcols].min().min()); _zmax = float(full_tbl[zcols].max().max())
    def _heat(v):  # white (low) → red (high); no matplotlib needed
        if pd.isna(v):
            return ""
        t = max(0.0, min(1.0, (v - _zmin) / (_zmax - _zmin + 1e-9)))
        return f"background-color: rgb(255,{int(255 - 150 * t)},{int(255 - 205 * t)})"
    st.dataframe(full_tbl.round(1).style.format("{:.1f}").map(_heat, subset=zcols),
                 use_container_width=True)
    st.caption(f"Each row = a forecast day ({len(dlist)}), each column = a weather zone (biggest first) + "
               f"system **TOTAL**; values = daily **{mlabel}** demand.")

st.divider()

# ---- ③ ERCOT degree days — demand-weather (StormVista weighted degree days) ----
# A degree day collapses the whole temperature map into ONE demand-relevant number:
#   CDD = max(T̄−65,0) cooling (summer AC), HDD = max(65−T̄,0) heating (winter).
# Both are "WDD" (Weighted Degree Days): population-weighted, i.e. each TX site counts by its
# share of electricity load (Houston ≫ Midland), so the index tracks ERCOT *system* demand —
# the NG-demand "language" the Fig-1 temperature map feeds into. CDD drives summer power burn;
# HDD drives winter heating (electric + direct gas). We keep BOTH and chart whichever is in
# season. WEIGHTING here is a spatial average — NOT normalization; normalization (removing the
# weather to expose solar/battery drift) is the separate Dashboard-2 step.
st.subheader("③ ERCOT degree days — demand-weather (StormVista)")

DD_HELP = {"cdd": "Cooling degree days — AC-driven summer power demand.",
           "hdd": "Heating degree days — winter heating (electric + direct gas)."}
DD_COLOR = {"cdd": "#b2182b", "hdd": "#2166ac"}  # warm red / cool blue
# Multi-model overlay: trader-facing label → StormVista model id, + a stable per-model colour.
# (Probed live: these 6 are in our subscription; cmc-det / icon-global return 404 → omitted.)
WDD_MODELS = {"GFS": "gfs", "EC": "ecmwf", "GEFS": "gfs-ens", "EPS": "ecmwf-eps",
              "GEPS": "cmc-ens", "GFS-BC": "gfs-ens-bc"}
WDD_MODEL_COLOR = {"GFS": "#1f77b4", "EC": "#d62728", "GEFS": "#17becf", "EPS": "#ff7f0e",
                   "GEPS": "#9467bd", "GFS-BC": "#8c564b"}
WDD_MODEL_DESC = {"GFS": "GFS operational (NOAA)", "EC": "ECMWF operational (the European model)",
                  "GEFS": "GFS ensemble mean", "EPS": "ECMWF ensemble mean (51 members)",
                  "GEPS": "Canadian ensemble mean", "GFS-BC": "GEFS bias-corrected mean"}


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_cdd_sensitivity():
    """Robust ERCOT demand↔CDD sensitivity in **StormVista pop-weighted CDD units** (GW per CDD).
    Fit demand ~ b·CDD on 1000+ historical cooling days (system-mean CDD), then rescale to StormVista's
    CDD definition via the ratio of its 30-yr pop-weighted CDD normal to the ERA5 system normal — so the
    slope can be applied to the forward StormVista CDD spread. Returns (b_sv, b_sys, scale) or None."""
    import src.stormvista as sv
    av = available_months()
    if not av:
        return None
    h = pd.concat([era_panel(y, tuple(av[y])) for y in sorted(av)])
    hl = h.copy()
    hl.index = hl.index.tz_convert(DISPLAY_TZ)
    daily = hl.groupby(hl.index.date).agg(temp=("temp", "mean"), demand=("demand", "mean"))
    daily.index = pd.to_datetime(daily.index)
    daily["cdd"] = (daily["temp"] - 65).clip(lower=0)
    daily["demand"] /= 1000.0
    cool = daily[daily["cdd"] > 0]
    if len(cool) < 50:
        return None
    b_sys = float(np.cov(cool["cdd"], cool["demand"])[0, 1] / cool["cdd"].var())
    scale = 1.0
    try:                                                     # rescale system-CDD → StormVista pop-weighted
        climo = sv.climatology("cdd", weight="pw", period=30)
        sv_norm = climo["ercot"] if (hasattr(climo, "columns") and "ercot" in climo.columns) else climo.squeeze()
        sv_norm = pd.to_numeric(sv_norm, errors="coerce")
        sv_norm.index = pd.Index(sv_norm.index).astype(str)
        sys_norm = daily.groupby(daily.index.strftime("%m-%d"))["cdd"].mean()
        j = pd.concat([sv_norm.rename("sv"), sys_norm.rename("sys")], axis=1).dropna()
        j = j[(j["sv"] > 2) & (j["sys"] > 2)]
        if len(j) > 20 and j["sys"].sum() > 0:
            scale = float(j["sv"].sum() / j["sys"].sum())
    except Exception:
        scale = 1.0                                          # fall back to system-CDD units
    return (b_sys / scale if scale else b_sys), b_sys, scale


@st.cache_data(ttl=3600, show_spinner=False)
def load_wdd_demand_corr(kind: str):
    """For each available StormVista model, correlate its forward CDD/HDD with the Meteologica demand
    forecast over the overlap window. Returns (table[model→{R²,GW/°-day,n}], best_model, spread) or None.
    `best_model` = highest R² (the model the demand forecast actually tracks — Meteologica is ECMWF-driven,
    so EC/EPS win and GFS is weak). `spread` = per-day max−min CDD across models (model disagreement)."""
    try:
        nl, _ = load_netload()
        dem = nl["demand"].groupby(nl.index.date).mean() / 1000.0
        dem.index = pd.to_datetime(dem.index)
    except Exception:
        return None
    rows, series = {}, {}
    for lab, mid in WDD_MODELS.items():
        got = load_model_wdd(mid, kind)
        if got is None:
            continue
        s = got[0].copy()
        s.index = pd.to_datetime(s.index)
        series[lab] = s
        pair = pd.concat([s.rename("x"), dem.rename("y")], axis=1, join="inner").dropna()
        if len(pair) < 4 or pair["x"].var() == 0:
            continue
        x, y = pair["x"].to_numpy(float), pair["y"].to_numpy(float)
        r = float(np.corrcoef(x, y)[0, 1])
        rows[lab] = {"R²": round(r * r, 3), "GW/°-day": round(float(np.cov(x, y)[0, 1] / x.var()), 2),
                     "n": int(len(pair))}
    if not rows:
        return None
    table = pd.DataFrame(rows).T.sort_values("R²", ascending=False)
    M = pd.DataFrame(series)
    spread = (M.max(axis=1) - M.min(axis=1)) if M.shape[1] >= 2 else pd.Series(dtype=float)
    return table, str(table.index[0]), spread


def _wdd_band(members: pd.DataFrame, idx) -> tuple:
    """GEFS p10/p90 across members, aligned to the forecast dates (or None if no members)."""
    if members is None or members.empty:
        return None, None
    m = members.reindex(idx)
    return m.quantile(0.10, axis=1), m.quantile(0.90, axis=1)


# Load each kind independently: a failure (or out-of-season missing file) in one must neither
# break the other nor crash the dashboard. @st.cache_data re-raises, so each call is guarded.
prune_stormvista_cache()  # bound disk growth (no-op for ~24h after the first call)
bundles: dict[str, object] = {}
for _k in ("cdd", "hdd"):
    try:
        b_ = load_ercot_wdd(_k)
        bundles[_k] = b_ if (b_ is not None and not b_.forecast.empty) else None
    except Exception as exc:
        bundles[_k] = None
        st.warning(f"Could not load StormVista {_k.upper()}: {exc}")

available = [k for k in ("cdd", "hdd") if bundles.get(k) is not None]
if not available:
    st.info("StormVista degree days unavailable — add `STORMVISTA_API_KEY` to `.env` (forecast, "
            "ensemble band, and anomaly vs the 30-yr normal).")
else:
    # keep BOTH: show next-day level + anomaly for whichever of cooling/heating loaded
    mc = st.columns(4)
    for i, k in enumerate(("cdd", "hdd")):
        b = bundles.get(k)
        if b is None:
            mc[i].metric(f"{k.upper()}", "—", help=DD_HELP[k])
            continue
        lvl, nrm = b.forecast.iloc[0], b.normal.iloc[0]
        mc[i].metric(f"{k.upper()} {b.forecast.index[0]:%a %m-%d}", f"{lvl:.1f}",
                     delta=f"{lvl - nrm:+.1f} vs normal", help=DD_HELP[k])
    # default to the in-season type (the larger near-term level) among those available
    if len(available) == 2:
        default = "cdd" if bundles["cdd"].forecast.iloc[0] >= bundles["hdd"].forecast.iloc[0] else "hdd"
    else:
        default = available[0]
    labels = {"cdd": "CDD (cooling)", "hdd": "HDD (heating)"}
    sel = mc[2].radio("Chart", [labels[k] for k in available], horizontal=True,
                      index=available.index(default), label_visibility="collapsed")
    kind = "cdd" if sel.startswith("CDD") else "hdd"
    b = bundles[kind]
    p10, p90 = _wdd_band(b.members, b.forecast.index)
    if p10 is not None:
        mc[3].metric("Ensemble spread (next day)", f"{(p90.iloc[0] - p10.iloc[0]):.1f}",
                     help="GEFS p10–p90 width on the next day — forecast confidence.")
    # freshness: the ensemble publishes ~1.5 h after the deterministic run, so the band can lag a
    # cycle — surface that rather than silently mixing runs.
    if p10 is not None and b.members_run and b.members_run != (b.date, b.cycle):
        st.caption(f"⏱ Band from the **{b.members_run[0]} {b.members_run[1]}z** ensemble run; "
                   f"forecast line is **{b.date} {b.cycle}z** (the ensemble publishes ~1.5 h later).")

    # look-ahead window: truncate the forecast view (recent actuals stay for context)
    n_fc = len(b.forecast)
    horizon = st.slider("Look-ahead (days)", 1, n_fc, min(15, n_fc), key="wdd_horizon",
                        help="How many forecast days to show — and the window for the "
                             "weather-vs-load view below.")
    cutoff = b.forecast.index[0] + pd.Timedelta(days=horizon - 1)
    fc = b.forecast[b.forecast.index <= cutoff]
    nrm_w = b.normal[b.normal.index <= cutoff]
    p10w = p10[p10.index <= cutoff] if p10 is not None else None
    p90w = p90[p90.index <= cutoff] if p90 is not None else None

    # ── multi-model overlay: one forecast line per selected weather model (its own latest run) ──
    msel = st.multiselect("Forecast models", list(WDD_MODELS), default=["GFS", "EC"], key="wdd_models",
                          help=f"Overlay each weather model's {kind.upper()} forecast (its own latest run) — "
                          "the GFS-vs-EC divergence is the model-risk read. "
                          + " · ".join(f"{k} = {WDD_MODEL_DESC[k]}" for k in WDD_MODELS))
    model_series, skipped = [], []                           # (label, series, date, cycle)
    for lab in msel:
        got = load_model_wdd(WDD_MODELS[lab], kind)
        if got is None:
            skipped.append(lab)
            continue
        s, d, c = got
        model_series.append((lab, s[s.index <= cutoff], d, c))

    fig_dd = go.Figure()
    if p10w is not None:  # ensemble p10–p90 band (forecast-weather uncertainty)
        fig_dd.add_trace(go.Scatter(x=p90w.index, y=p90w, line=dict(width=0),
                                    showlegend=False, hoverinfo="skip"))
        fig_dd.add_trace(go.Scatter(x=p10w.index, y=p10w, fill="tonexty",
                                    fillcolor="rgba(120,120,120,0.18)", line=dict(width=0),
                                    name="GEFS p10–p90"))
    # the 30-yr normal: the gap between it and the forecast IS the anomaly
    fig_dd.add_trace(go.Scatter(x=fc.index, y=nrm_w, line=dict(color="#888", dash="dash"),
                                name="30-yr normal"))
    if not b.actual.empty:  # recent actuals (past) then the deterministic forecast (future)
        fig_dd.add_trace(go.Scatter(x=b.actual.index, y=b.actual,
                                    line=dict(color="#2ca02c", width=2), name="actual (obs)"))
    for lab, s, d, c in model_series:           # one forecast line per selected model (its own run)
        fig_dd.add_trace(go.Scatter(x=s.index, y=s, mode="lines", name=f"{lab} ({d} {c}z)",
                                    line=dict(color=WDD_MODEL_COLOR[lab],
                                              width=2.6 if lab in ("GFS", "EC") else 1.8)))
    if not model_series:
        fig_dd.add_trace(go.Scatter(x=fc.index, y=fc, line=dict(color=DD_COLOR[kind], width=2.5),
                                    name=f"{kind.upper()} ({b.model})"))   # fallback if none selected/loaded
    fig_dd.update_layout(height=360, margin=dict(t=10, b=10), yaxis_title=f"{kind.upper()} (°-days)",
                         legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
    st.plotly_chart(style_fig(fig_dd), use_container_width=True)
    if skipped:
        st.caption(f"⚠️ No current run for: {', '.join(skipped)} (out-of-season or not in subscription) — skipped.")
    kname = "cooling" if kind == "cdd" else "heating"
    st.caption(
        f"**Load-weighted ERCOT {kname} degree days** (population-weighted) — one line per selected weather "
        "model (its own latest run), green = actuals, dashed = 30-yr normal, shaded = GEFS p10–p90. Gap to "
        "normal = anomaly (above ⇒ more demand); model spread (GFS vs EC) = forecast risk. Source: "
        "**StormVista WDD**."
    )

    # ── Weather → load: pair the forecast weather (degree days OR absolute high temp, both from
    # StormVista, load-weighted) with forecast DEMAND and NET LOAD (Meteologica). Showing both load
    # series makes the key point: weather drives demand cleanly, but net load (what gas serves) is
    # decoupled by wind/solar. This section has its OWN look-ahead window + weather-axis toggle.
    st.markdown("**Weather → load** — does the forecast weather translate into load? "
                "*(the demand forecast is ECMWF-driven, so the weather axis defaults to the model it tracks "
                "best — not GFS)*")
    corr = load_wdd_demand_corr(kind)                       # per-model R² vs the Meteologica demand forecast
    wmodels = list(corr[0].index) if corr else ["GFS"]
    best_m = corr[1] if corr else "GFS"
    wc = st.columns([1.0, 1.0, 1.5])
    wl_days = wc[0].slider("Look-ahead (days)", 1, n_fc, min(7, n_fc), key="wl_horizon",
                           help="Windows the scatter AND the hourly chart below.")
    wmodel = wc[1].selectbox("Weather model", wmodels,
                             index=wmodels.index(best_m) if best_m in wmodels else 0, key="wl_model",
                             help="Which model's CDD drives the x-axis. Default = the model the demand "
                             "forecast tracks best (highest R², table below). GFS tracks ERCOT demand weakly "
                             "because Meteologica is ECMWF-driven.")
    xmode = wc[2].radio("Weather axis", [f"{kind.upper()} (°-days)", "High temp (°F)"],
                        horizontal=True, key="wl_xaxis")
    wl_cut = b.forecast.index[0] + pd.Timedelta(days=wl_days - 1)        # daily cutoff (naive)
    wl_cut_ts = pd.Timestamp(b.forecast.index[0]).tz_localize(DISPLAY_TZ) + pd.Timedelta(days=wl_days)
    if xmode.startswith("High"):
        tdf = load_ercot_temp()
        xser = (tdf["tmax"] if tdf is not None else pd.Series(dtype="float64"))
        xname, xunit, xslope = "high temp", "°F", "°F"
    else:
        got = load_model_wdd(WDD_MODELS.get(wmodel, "gfs"), kind)   # selected model's CDD (default = best)
        xser = got[0].copy() if got is not None else b.forecast.copy()
        xser.index = pd.to_datetime(xser.index)
        xname, xunit, xslope = f"{kind.upper()} ({wmodel})", "°-days", kind.upper()
    xser = xser[xser.index <= wl_cut]
    try:
        _nl_df, _ = load_netload()
        g = _nl_df.groupby(_nl_df.index.date)
        dly = pd.DataFrame({"demand": g["demand"].mean() / 1000.0,
                            "net_load": g["net_load"].mean() / 1000.0,
                            "hours": g["net_load"].count()})
        dly.index = pd.to_datetime(dly.index)
        dly = dly[dly["hours"] >= 24]  # drop partial first/last forecast days (skew the daily mean)
        pair = pd.concat([xser.rename("x"), dly], axis=1, join="inner").dropna(subset=["x", "net_load"])
    except Exception:
        pair = pd.DataFrame()
    if len(pair) >= 3:
        xl = [pair["x"].min(), pair["x"].max()]
        def _fit(col):  # OLS slope (GW per weather unit) + the fit-line end-points
            s = pair[col].cov(pair["x"]) / pair["x"].var()
            b0 = pair[col].mean() - s * pair["x"].mean()
            return s, [s * x + b0 for x in xl]
        hov = [d.strftime("%a %m-%d") for d in pair.index]
        figwl = go.Figure()
        for col, color, lab in [("demand", "#d6604d", "demand"), ("net_load", "#1f77b4", "net load")]:
            s, yfit = _fit(col)
            figwl.add_trace(go.Scatter(x=pair["x"], y=pair[col], mode="markers", text=hov,
                                       marker=dict(size=9, color=color, opacity=0.8),
                                       hovertemplate="%{text}<br>%{x:.1f} " + xunit
                                       + "<br>%{y:.1f} GW " + lab + "<extra></extra>", name=lab))
            figwl.add_trace(go.Scatter(x=xl, y=yfit, mode="lines", line=dict(color=color, dash="dot"),
                                       name=f"{lab}: {s:+.2f} GW/{xslope}"))
        figwl.update_layout(height=320, margin=dict(t=10, b=10),
                            xaxis_title=f"forecast {xname} ({xunit})",
                            yaxis_title="GW (daily mean)", legend=dict(orientation="h", y=1.02, x=0))
        st.plotly_chart(style_fig(figwl), use_container_width=True)
        s_dem = pair["demand"].cov(pair["x"]) / pair["x"].var()
        s_nl = pair["net_load"].cov(pair["x"]) / pair["x"].var()
        st.caption(
            f"**Weather vs load (forward, next {wl_days} d).** Weather drives **demand** cleanly "
            f"(**{s_dem:+.2f} GW per {xslope}**, red), but **net load** (blue) is looser "
            f"(**{s_nl:+.2f} GW per {xslope}**) — wind + solar swing it; the gap = renewable generation. "
            "A hot day only means high burn if it's also calm/cloudy.")
    else:
        st.caption("Weather-vs-load pairing unavailable — net-load forecast not loaded (Meteologica "
                   "may be rate-limited), or no StormVista temperature for the High-°F axis.")

    # ── which weather model is the demand tracking? + model-disagreement → demand-range bridge ──
    if corr is not None:
        table, best, spread = corr
        sens = load_cdd_sensitivity()
        gfs_r2 = float(table.loc["GFS", "R²"]) if "GFS" in table.index else float("nan")
        bridge = ""
        if sens is not None and not spread.empty:
            sp = spread[spread.index <= wl_cut]
            if not sp.empty:
                b_sv = sens[0]
                bridge = (f" **Model-disagreement demand risk:** cross-model {kind.upper()} spread averages "
                          f"**{sp.mean():.1f} °-days** (peak {sp.max():.1f} on {sp.idxmax():%a %m-%d}) ⇒ "
                          f"~**{sp.mean() * b_sv:.1f} GW** mean (peak ~**{sp.max() * b_sv:.1f} GW**) of demand "
                          f"uncertainty, at the robust **{b_sv:.2f} GW/CDD** historical sensitivity.")
        st.caption(
            f"📐 **Which model is the demand tracking?** **{best}** fits the Meteologica demand best "
            f"(R²={float(table.loc[best, 'R²']):.2f})" +
            (f"; **GFS** only R²={gfs_r2:.2f}" if gfs_r2 == gfs_r2 else "") +
            f" — demand is **ECMWF-driven**, axis defaults to **{best}**." + bridge)
        with st.expander(f"Per-model R²: forward {kind.upper()} vs the Meteologica demand forecast"):
            st.dataframe(table, use_container_width=True)
            st.caption("**R²** = how well each model's forecast CDD explains Meteologica's demand over the "
                       "overlap window — high (EC/EPS) = the model the demand tracks, low (GFS) = weakly "
                       "related. **Use:** trade demand off EC weather; GFS-vs-EC divergence = revision risk.")
            # drill-down: a picked forecast day's HOURLY demand profile + load-weighted hourly temperature
            try:
                _nlh, _ = load_netload()
                demh = _nlh["demand"] / 1000.0                              # GW, hourly, local tz
                lo_fc = pd.Timestamp(b.forecast.index[0]).tz_localize(DISPLAY_TZ)
                demh = demh[(demh.index >= lo_fc) & (demh.index <= wl_cut_ts)]
            except Exception:
                demh = pd.Series(dtype=float)
            if not demh.empty:
                hd_days = sorted(set(demh.index.date))
                hd_opts = [pd.Timestamp(d).strftime("%a %b %d") for d in hd_days]
                # default to the day the models disagree most (the spread peak) — that's the one to inspect
                d0 = 0
                if not spread.empty:
                    sp_f = spread[spread.index <= wl_cut]
                    if not sp_f.empty and sp_f.idxmax().date() in hd_days:
                        d0 = hd_days.index(sp_f.idxmax().date())
                fday = st.selectbox("Hourly demand — focus day", hd_opts, index=d0, key="r2_hourly_day",
                                    help="Drill a daily-mean demand point into its 24-hour shape, with that "
                                    "day's load-weighted temperature. Defaults to the max model-disagreement day.")
                fd = hd_days[hd_opts.index(fday)]
                dser = demh[demh.index.date == fd]
                fh = go.Figure()
                fh.add_trace(go.Scatter(x=dser.index, y=dser.values, name="demand (GW)",
                                        line=dict(color="#d6604d", width=2.6)))
                tmat = load_ercot_temp_hourly()
                if tmat is not None and not tmat.empty and "load-weighted" in tmat.columns:
                    tser = tmat["load-weighted"].tz_convert(DISPLAY_TZ)
                    tser = tser[tser.index.date == fd]
                    if not tser.empty:
                        fh.add_trace(go.Scatter(x=tser.index, y=tser.values, name="load-wtd temp (°F, right)",
                                                line=dict(color="#1f77b4", width=1.8, dash="dot"), yaxis="y2"))
                        fh.update_layout(yaxis2=dict(title="temp (°F)", overlaying="y", side="right",
                                                     color="#1f77b4", showgrid=False))
                fh.update_layout(height=270, margin=dict(t=10, b=10),
                                 yaxis=dict(title="demand (GW)", color="#d6604d"),
                                 legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
                st.plotly_chart(style_fig(fh), use_container_width=True)
                st.caption(f"Hourly **Meteologica demand** for **{fday}** vs load-weighted temperature "
                           "(right axis) — the demand peak lags the temp peak (thermal mass + evening "
                           "occupancy), hidden by the daily-mean scatter point.")

    # ── sub-daily / hourly: intraday ERCOT temperature (StormVista, 3 h) per station + hourly load
    st.markdown("**Hourly / sub-daily** — intraday **temperature (red/solid, left °F)** vs "
                "**whole-ERCOT net load (blue/dotted, right GW)**")
    stmat = load_ercot_temp_hourly()
    if stmat is not None and not stmat.empty:
        STN_CITY = {"KIAH": "Houston", "KDFW": "Dallas", "KSAT": "San Antonio", "KAUS": "Austin",
                    "KBRO": "Brownsville", "KCRP": "Corpus Christi"}
        def _stlabel(c):
            return "Load-weighted ERCOT temp" if c == "load-weighted" else f"{STN_CITY.get(c, c)} ({c}) temp"
        ordered = ["load-weighted"] + [c for c in stmat.columns if c != "load-weighted"]
        loc_all = stmat.tz_convert(DISPLAY_TZ)
        loc_all = loc_all[loc_all.index <= wl_cut_ts]
        hdays = sorted(set(loc_all.index.date))
        day_opts = ["All days"] + [pd.Timestamp(d).strftime("%a %b %d") for d in hdays]
        hc2 = st.columns([1.1, 2.4])
        focus = hc2[0].selectbox("Focus day", day_opts, key="hourly_focus",
                                 help="Zoom to a single forecast day's intraday shape, or show the "
                                      "whole window.")
        pick = hc2[1].multiselect("Temperature station(s) to plot", ordered, default=["load-weighted"],
                                  format_func=_stlabel, key="subdaily_stations")
        if focus == "All days":
            loc, lo_b, hi_b = loc_all, None, wl_cut_ts
        else:
            fd = hdays[day_opts.index(focus) - 1]
            lo_b = pd.Timestamp(fd).tz_localize(DISPLAY_TZ)
            hi_b = lo_b + pd.Timedelta(days=1)
            loc = loc_all[loc_all.index.date == fd]
        figh = go.Figure()
        for c in (pick or ["load-weighted"]):  # red highlights the load-weighted aggregate
            figh.add_trace(go.Scatter(x=loc.index, y=loc[c], name=_stlabel(c),
                                      line=dict(width=2.8 if c == "load-weighted" else 1.4,
                                                color="#d6604d" if c == "load-weighted" else None)))
        try:
            _nl2, _ = load_netload()
            nlh = (_nl2["net_load"] / 1000.0)
            nlh = (nlh[nlh.index <= wl_cut_ts] if lo_b is None
                   else nlh[(nlh.index >= lo_b) & (nlh.index < hi_b)])
            figh.add_trace(go.Scatter(x=nlh.index, y=nlh.values,
                                      name="ERCOT net load — whole system (GW, right axis)",
                                      line=dict(color="#1f77b4", width=1.6, dash="dot"), yaxis="y2"))
            figh.update_layout(yaxis2=dict(title="ERCOT net load (GW)", overlaying="y", side="right",
                                           color="#1f77b4"))
        except Exception:
            pass
        figh.update_layout(height=340, margin=dict(t=10, b=10),
                           yaxis=dict(title="temperature (°F)", color="#d6604d"),
                           legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
        st.plotly_chart(style_fig(figh), use_container_width=True)
        st.caption(
            "**Solid line(s)** = 3-hourly temperature forecast (°F, left) for the picked station(s) — "
            "default load-weighted ERCOT (red). **Blue dotted** = whole-ERCOT net load (GW, right). "
            "Temp peaks mid-afternoon, net load ramps into the evening as solar fades. Times in CPT.")
    elif stmat is not None:
        st.caption("Sub-daily temperature: empty for the latest run.")


st.divider()

# ---- ERCOT net load (Meteologica) ----
st.subheader("ERCOT net load forecast  (demand − wind − solar)")
nc = st.columns([1, 4])
days = nc[0].slider("Horizon (days)", 1, 15, 7)
try:
    df, meta = load_netload()
except Exception as exc:
    msg = str(exc)
    if "DoLogin" in msg or "Too many" in msg:
        st.info("Meteologica login is rate-limited right now (cooling down). The token cache "
                "will reuse a token once it refreshes — temperature map above is unaffected.")
    else:
        st.error(f"Could not load net-load data: {exc}")
    st.stop()

issue = meta.get("issue_time")
st.caption(f"Issued {issue:%Y-%m-%d %H:%M UTC} · update `{meta.get('update_id','')}` · times {DISPLAY_TZ}")
view_nl = df[df.index <= df.index.min() + pd.Timedelta(days=days)]
net = view_nl["net_load"].dropna()
band = view_nl.dropna(subset=["p50"])

m = st.columns(4)
m[0].metric("Current net load", f"{net.iloc[0]:,.0f} MW")
m[1].metric("Peak net load", f"{net.max():,.0f} MW", help=f"at {net.idxmax():%a %m-%d %H:%M}")
m[2].metric("Peak renewables", f"{view_nl['renewables'].max():,.0f} MW")
if not band.empty:
    bt = band["p50"].idxmax()
    m[3].metric("Peak p50 (ENS)", f"{band.loc[bt,'p50']:,.0f} MW",
                help=f"p10–p90 width {band.loc[bt,'p90']-band.loc[bt,'p10']:,.0f} MW")

fig = go.Figure()
if not band.empty:
    fig.add_trace(go.Scatter(x=band.index, y=band["p90"], line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=band.index, y=band["p10"], fill="tonexty",
                             fillcolor="rgba(31,119,180,0.20)", line=dict(width=0),
                             name="p10–p90 (ECMWF-ENS)"))
    fig.add_trace(go.Scatter(x=band.index, y=band["p50"], line=dict(color="#1f77b4", dash="dot"),
                             name="p50 (ECMWF-ENS)"))
fig.add_trace(go.Scatter(x=view_nl.index, y=view_nl["net_load"], line=dict(color="#111", width=2),
                         name="net load (Meteologica)"))
fig.update_layout(height=400, margin=dict(t=10, b=10), yaxis_title="MW",
                  legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
st.plotly_chart(style_fig(fig), use_container_width=True)

# ---- Implied power-sector gas burn (the weather → power → NG bridge) ----
st.subheader("Implied power-sector gas burn (ERCOT)")
gc = st.columns([1, 1, 3])
heat_rate = gc[0].slider("Heat rate (MMBtu/MWh)", 6.0, 12.0, 7.5, 0.1)
baseload_gw = gc[1].slider("Must-run baseload (GW)", 0.0, 20.0, 8.0, 0.5)
base_mw = baseload_gw * 1000.0
burn = implied_gas_burn_bcfd(view_nl["net_load"], base_mw, heat_rate).dropna()
ramp = (view_nl["net_load"].diff() / 1000.0).dropna()  # GW/hr
has_band = not band.empty
if has_band:
    burn_p10 = implied_gas_burn_bcfd(band["p10"], base_mw, heat_rate)
    burn_p50 = implied_gas_burn_bcfd(band["p50"], base_mw, heat_rate)
    burn_p90 = implied_gas_burn_bcfd(band["p90"], base_mw, heat_rate)

# Actual gas burn (EIA-930) for the recent past — measured, no baseload assumption.
_now = pd.Timestamp.now(tz="UTC").floor("h")
try:
    actual = actual_gas_burn((_now - pd.Timedelta(days=10)).strftime("%Y-%m-%dT%H"),
                             _now.strftime("%Y-%m-%dT%H"), heat_rate)
    actual = actual.tz_convert(DISPLAY_TZ) if not actual.empty else None
except Exception:
    actual = None  # missing/invalid EIA_API_KEY or transient error → forecast-only

gm = st.columns(4)
gm[0].metric("Current gas burn", f"{burn.iloc[0]:.2f} Bcf/d")
gm[1].metric("Peak gas burn", f"{burn.max():.2f} Bcf/d", help=f"at {burn.idxmax():%a %m-%d %H:%M}")
gm[2].metric("Max up-ramp", f"{ramp.max():+.1f} GW/hr", help=f"net-load ramp at {ramp.idxmax():%a %m-%d %H:%M}")
if actual is not None:
    gm[3].metric("Latest actual burn", f"{actual.iloc[-1]:.2f} Bcf/d",
                 help=f"EIA-930 (no baseload assumption) · {actual.index[-1]:%m-%d %H:%M}")
elif has_band:
    bt = burn_p50.idxmax()
    gm[3].metric("Peak p50 burn", f"{burn_p50.loc[bt]:.2f} Bcf/d",
                 help=f"p10–p90 {burn_p10.loc[bt]:.2f}–{burn_p90.loc[bt]:.2f} Bcf/d (ECMWF-ENS)")

gb = go.Figure()
if has_band:
    gb.add_trace(go.Scatter(x=burn_p90.index, y=burn_p90, line=dict(width=0), showlegend=False, hoverinfo="skip"))
    gb.add_trace(go.Scatter(x=burn_p10.index, y=burn_p10, fill="tonexty", fillcolor="rgba(214,96,77,0.18)",
                            line=dict(width=0), name="p10–p90 (ECMWF-ENS)"))
    gb.add_trace(go.Scatter(x=burn_p50.index, y=burn_p50, line=dict(color="#d6604d", dash="dot"), name="p50 (ENS)"))
if actual is not None:
    gb.add_trace(go.Scatter(x=actual.index, y=actual, line=dict(color="#2ca02c", width=2),
                            name="actual gas burn (EIA-930)"))
gb.add_trace(go.Scatter(x=burn.index, y=burn, line=dict(color="#7f3b08", width=2),
                        name="implied burn forecast (Meteologica)"))
gb.update_layout(height=380, margin=dict(t=10, b=10), yaxis_title="Bcf/d",
                 legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
st.plotly_chart(style_fig(gb), use_container_width=True)

# ---- ERCOT demand forecast — multi-model overlay (Meteologica weather-model variants), per zone ----
st.subheader("ERCOT demand forecast — multi-model (Meteologica)")
zsel = st.columns([1.3, 3])
dm_zone = zsel[0].selectbox("Zone", list(DEMAND_ZONE_REGION), index=0, key="dm_zone",
                            help="Whole-ERCOT system, or one of the 8 weather zones — the same 3 models "
                            "exist per zone, so you can see *where* demand-forecast disagreement lives.")
dm = load_demand_models(DEMAND_ZONE_REGION[dm_zone])
if not dm:
    st.info("Multi-model demand forecast unavailable — Meteologica not loaded / rate-limited.")
else:
    zone_txt = "Whole-ERCOT system" if dm_zone == "Whole ERCOT" else f"{dm_zone}-zone"
    dmc = st.columns([1.8, 0.9, 1.1])
    dm_sel = dmc[0].multiselect("Demand models", list(dm), default=list(dm), key="dm_models",
                                help="Demand forecast under each Meteologica weather-model variant — "
                                "add/remove each. "
                                + " · ".join(f"{k} = {DEMAND_MODEL_DESC[k]}" for k in dm))
    dm_days = dmc[1].slider("Horizon (days)", 1, 48, 14, key="dm_days",
                            help="ECMWF-ENSEXT runs ~45 days out (~6.4 weeks, sub-seasonal); ENS ~6 d; "
                            "the blend ~14 d. Each line ends at its own data extent.")
    dm_band = dmc[2].toggle("± ensemble band", value=False, key="dm_band",
                            help="Shade p10–p90 across ensemble members (ENS / ENSEXT only).")
    t0 = min(s.index.min() for s, _, _ in dm.values())
    cut = t0 + pd.Timedelta(days=dm_days)
    figd = go.Figure()
    for lab in dm_sel:
        cen, p10, p90 = dm[lab]
        cen = cen[cen.index <= cut]
        if dm_band and p10 is not None:                          # ensemble p10–p90 shading (ENS/ENSEXT)
            p10c, p90c = p10[p10.index <= cut], p90[p90.index <= cut]
            figd.add_trace(go.Scatter(x=p90c.index, y=p90c, line=dict(width=0), showlegend=False,
                                      hoverinfo="skip"))
            figd.add_trace(go.Scatter(x=p10c.index, y=p10c, fill="tonexty", line=dict(width=0),
                                      fillcolor=DEMAND_MODEL_FILL.get(lab, "rgba(120,120,120,0.10)"),
                                      name=f"{lab} p10–p90"))
        figd.add_trace(go.Scatter(x=cen.index, y=cen, name=lab,
                                  line=dict(color=DEMAND_MODEL_COLOR[lab], width=2.2)))
    figd.update_layout(height=380, margin=dict(t=10, b=10), yaxis_title=f"{dm_zone} demand (MW)",
                       legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
    st.plotly_chart(style_fig(figd), use_container_width=True)

    # ── where do the demand models disagree, zone by zone? (opt-in — loads all 8 zones × 3 models) ──
    if st.toggle("📊 Spread by zone — where the demand models disagree", value=False, key="dm_spread_zone"):
        with st.spinner("Loading all 8 zones × 3 models…"):
            sbz = demand_spread_by_zone()
        if sbz:
            order = sorted(sbz, key=lambda z: sbz[z]["peak"], reverse=True)
            bar = go.Figure()
            bar.add_trace(go.Bar(x=order, y=[sbz[z]["peak"] for z in order], name="peak spread",
                                 marker_color="#d62728"))
            bar.add_trace(go.Bar(x=order, y=[sbz[z]["mean"] for z in order], name="mean spread",
                                 marker_color="#1f77b4"))
            bar.update_layout(height=300, margin=dict(t=10, b=10), barmode="group",
                              yaxis_title="cross-model demand spread (MW)",
                              legend=dict(orientation="h", y=1.02, x=0))
            st.plotly_chart(style_fig(bar), use_container_width=True)
            top = order[0]
            st.caption(
                f"**Where the demand models disagree most** — cross-model spread (max−min of the 3 models' "
                f"central demand) per weather zone, over each zone's common window. **{top}** is the most "
                f"contested (peak {sbz[top]['peak']:,.0f} MW). The whole-system spread is smaller than the "
                "sum of zones because zonal errors partly cancel — this shows *where* the forecast "
                "uncertainty actually lives (locational / congestion risk), which the system total hides.")
        else:
            st.caption("Per-zone spread unavailable (Meteologica rate-limited).")

