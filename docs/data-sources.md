# Data Sources & Forecasting Models

Exact provenance for every number on the dashboard. Two providers:

| Layer | Provider | What |
|-------|----------|------|
| Power-market forecasts (net load: wind / solar / demand / price) | **Meteologica "API markets"** | see [meteologica-api.md](meteologica-api.md) |
| Temperature map (current, lookback differences, climatology) | **Open-Meteo** | this document |

---

## 1. Why we use Open-Meteo at all

The Meteologica feed (our market-data provider) is a **power-market product** — it has
**no temperature / weather variables** (verified: 0 of 2748 catalog items). Its ERCOT *demand*
forecast is **ECMWF-driven** (the catalog serves demand under `ECMWF-ENS`/`ECMWF-ENSEXT`/its own
blend) — confirmed empirically: forward demand correlates with StormVista **EC/EPS CDD at R² ≈
0.75–0.82 but GFS at only R² ≈ 0.06** (so the ③·a weather axis defaults to EC, not GFS). But the
whole point of the map is the *weather* driver, so we need a second source that provides:

1. **Temperature forecasts** for any lat/lon (the per-county map), and
2. **Historical temperature** (the lookback differences and the multi-year climatology).

Open-Meteo provides both, for free, with no API key, for any coordinate — which is why it
is used **only** for the temperature map. Nothing in the net-load section depends on it.

---

## 2. Forecast temperature — the exact model

The map's **current ("now")** temperature and recent (<=2-day) lookbacks come from the
**Open-Meteo Forecast API** with the model **pinned explicitly** (not auto `best_match`):

```
GET https://api.open-meteo.com/v1/forecast?...&models=gfs_seamless
```
(`src/weather.py: FORECAST_MODEL = "gfs_seamless"`)

**`gfs_seamless` = NOAA "GFS Seamless"**, a seamless blend run by **NOAA / NCEP**:

| Component | Model | Run by | Resolution | Range used |
|-----------|-------|--------|-----------|------------|
| 0–48 h | **HRRR** (High-Resolution Rapid Refresh) | NOAA/NCEP | ~3 km, hourly, updated hourly | the "now" value |
| beyond 48 h | **GFS** (Global Forecast System) | NOAA/NCEP | ~13 km (0.13°), updated 4×/day | longer ranges |

These are **physics-based Numerical Weather Prediction (NWP)** models — primitive-equation
atmospheric models with observational data assimilation. **Open-Meteo does not run any
forecast of its own**; it ingests the agencies' GRIB output and bilinearly interpolates the
model grid to the requested coordinate. We confirmed `best_match` for US points resolves to
exactly `gfs_seamless` (identical values), so pinning it changes nothing except making the
source explicit and reproducible.

> Footnote for figures: *"Temperature forecast: NOAA GFS Seamless (HRRR ~3 km ≤48 h + GFS
> ~13 km), via Open-Meteo; interpolated to county centroids."*

**Selectable models.** The UI exposes a *Forecast model* dropdown with all 9 US-covering
Open-Meteo methods — `gfs_seamless`, `gfs_hrrr`, `gfs_global`, `ncep_nbm_conus` (NOAA NBM),
`ecmwf_ifs025` (ECMWF IFS), `icon_seamless` (DWD ICON), `gem_seamless` (Environment Canada),
`jma_seamless` (Japan), `meteofrance_seamless` (ARPEGE/AROME). Different methods disagree by
a few °F; comparing them is a model-uncertainty read.

**Forecast ensemble ± (uncertainty).** A toggle adds the **NOAA GFS ensemble** (`gfs025`,
31 members) via Open-Meteo's *ensemble API* (`ensemble-api.open-meteo.com`). The per-county
**std across members** is the forecast spread (`fcst±`) — a genuine forecast-side uncertainty
(distinct from the spatial and climatological ±).

## 3. Historical temperature — the exact dataset

Lookbacks ≥ 3 days and the **10-year climatology** come from the **Open-Meteo Archive API**:

```
GET https://archive-api.open-meteo.com/v1/archive?...
```

This serves **ECMWF ERA5** (the default archive dataset):

- **ERA5 = ECMWF Reanalysis v5**, produced by **ECMWF** under the EU **Copernicus Climate
  Change Service (C3S)**.
- A **reanalysis**, not a forecast: ECMWF's IFS model re-run over the whole historical record
  while **assimilating observations** (surface stations, radiosondes, satellites) → a
  physically consistent, **hourly, ~31 km** global record (ERA5-Land variant ~9 km).
- ~5-day lag for the most recent data (so it's used only for references ≥ 3 days back).

The **climatology** (`points_climatology`) pulls ERA5 for *today's* month/day/hour across the
last **10 years** and reports the per-county **mean** (the "normal") and the **inter-annual
standard deviation** (the ± shown in the table).

> Footnote for figures: *"Historical / normal: ECMWF ERA5 reanalysis (Copernicus C3S),
> hourly ~31 km, via Open-Meteo archive."*

---

## 4. The Open-Meteo API — access, cost, limits

- **How you "get" it:** there is nothing to install or register for the free tier — it's a
  public HTTPS endpoint you call with `GET` requests (we use the `requests` library). No API
  key, no login.
  - Forecast: `https://api.open-meteo.com/v1/forecast`
  - Archive:  `https://archive-api.open-meteo.com/v1/archive`
- **Is it free?** **Yes, for non-commercial use**, under a **CC-BY 4.0** attribution licence
  (attribute "Weather data by Open-Meteo.com"). No payment, no key.
- **Rate limits (free tier):** roughly **≤10,000 calls/day, ≤5,000/hour, ≤600/minute**,
  *weighted* by number of locations × time-range. A per-county pull (~200 points) is therefore
  ~200+ weighted units, which is why the app caps locations, uses 2–3 day windows, caches
  (30 min; climatology 6 h), and degrades gracefully on HTTP 429.
- **Commercial / higher limits:** a paid **API key** (subscription at
  `open-meteo.com/en/pricing`) unlocks a dedicated `customer-api.open-meteo.com` endpoint with
  much higher limits and an SLA. Recommended for cloud deployment — it removes the quota
  ceiling that constrains rapid browsing today.

---

## 5. Summary of every figure's provenance

| Figure | "now" | reference / history |
|--------|-------|---------------------|
| Temperature map — absolute | GFS Seamless (NOAA) | — |
| Temperature map — vs N days/weeks | GFS Seamless (NOAA) | GFS (≤2 d) or ERA5 (≥3 d) |
| Temperature map — vs 10-yr normal | GFS Seamless (NOAA) | ERA5 (10 years), mean ± inter-annual std |
| Net-load (demand − wind − solar) | Meteologica blend + ECMWF-ENS | see meteologica-api.md |

## 6. Local archive (persistence)

Open-Meteo's forecast API only reaches ~16 days ahead and keeps a short recent past;
the ERA5 archive lags ~5 days. Neither retains *historical forecasts* (what was predicted
on a past day). So each per-county "now" pull is appended to Parquet under
`data/weather/market=<M>/date=<YYYY-MM-DD>/<model>_<unit>_<hour>.parquet` (idempotent per
hour) — building our own vintage archive over time. Accumulate it on a schedule:

```bash
# hourly cron, inside dash_env
python -m src.ingest_weather                       # default model, all markets
python -m src.ingest_weather gfs_seamless ecmwf_ifs025   # specific models
```

## 7. EIA-930 — actual ERCOT gas generation (wired in)

`src/eia.py` pulls **measured** hourly ERCOT net generation by fuel from the **EIA Hourly
Electric Grid Monitor** (`api.eia.gov/v2/electricity/rto/fuel-type-data`, respondent `ERCO`).
- **Used for:** the green **actual gas burn** line (`fuel NG × heat rate`, *no baseload
  assumption*); planned: full fuel mix (real must-run baseload) and history back to ~2018.
- **Also (Feb-2021 Uri panel):** EIA-930 **demand** (`region-data`, type `D`, respondent ERCO) +
  ERA5 temperature, because **Meteologica has no pre-Dec-2021 data**. EIA `D` reaches ~2018 and is the
  only demand source for the Uri counterfactual (`src/uri2021.py`). EIA-930 also reports **battery
  storage** as fuel type `BAT` (net output, + discharge / − charge) — a free independent cross-check on
  the Meteologica battery series (id 7044); correlation ≈ 0.8 with a ~1 h labelling offset.
- **Access:** **free** API key (register at `eia.gov/opendata/register.php`), set `EIA_API_KEY`
  in `.env`. Lag is only ~13 h; limits are generous (no per-minute throttling in practice).

## 8. StormVista (SVWX) — weighted degree days (wired in)

[stormvistawxmodels.com](https://www.stormvistawxmodels.com) is a **paid** weather/energy data
vendor for traders. We use it for **weighted degree days (WDD)** — the demand-weather metric NG
desks actually quote (see [concepts.md](concepts.md) §5). `src/stormvista.py` is a working client.

- **Endpoint:** `https://api.stormvistawxmodels.com/model-data/[model]/[YYYYMMDD]/[cycle]z/wdd/[file].csv?apikey=KEY`
  — CSV files, auth via the `?apikey=` query param (the `model-data/` prefix is the base; the
  subscriber docs only show the relative tail). Key in `.env` as `STORMVISTA_API_KEY`;
  `STORMVISTA_USER/PASSWORD` are only for reading the gated web docs.
- **What we pull (ERCOT, load-weighted `pw`):** deterministic CDD/HDD forecast
  (`pw_cdd_regiso.csv`), **GEFS ensemble members** (`…_members.csv` → p10/p50/p90), 7-day
  **actuals** (`history/wdd/…`), and the **10/30-yr climatology normal** (the anomaly reference).
  Plus US-national **gas-weighted HDD** (`gw_hdd-daily.csv`, obs+fcst+normal in one file) for the
  Henry-Hub gas-demand view. Run files cached under `data/stormvista/`.
- **Models live in our subscription** (probed 2026-06-14): **6 work** — `gfs` (GFS op), `ecmwf`
  (EC op), `gfs-ens` (GEFS), `ecmwf-eps` (EPS, 51 members), `cmc-ens` (GEPS), `gfs-ens-bc` (GEFS
  bias-corrected). **Not subscribed (404):** `cmc` (CMC det.), `icon-global` (DWD ICON). The ③ chart
  exposes these 6 as a **"Forecast models" multiselect** (default GFS + EC) — each draws its own CDD/HDD
  forecast line on its own latest run; the GFS-vs-EC divergence is the model-risk read. Cycles 00/12.
- **Rate limits:** per-subscription quota (Enterprise tier here = 1000 GB/mo) — generous vs
  Open-Meteo's per-minute free throttle.

**What else StormVista offers** (mapped to the dashboard; ✅ = built):

| StormVista product | Use here | Status |
|--------------------|----------|--------|
| **Pop / gas-weighted CDD–HDD** (ISO + national) | **③ degree-day demand panel** + US gas-weighted HDD companion | ✅ **built** |
| **Multi-model CDD/HDD** (GFS / EC / GEFS / EPS / GEPS / GFS-BC) | **③ "Forecast models" overlay** — toggle each model's forecast line (model-risk read) | ✅ **built** |
| **Full ECMWF EPS + GEFS** ensembles | richer net-load / gas-burn **p10–p90** + spike probability (EPS band per model) | partial (means wired; per-model bands planned) |
| **Multi-model, bias-corrected** temps | forecast-model comparison with bias correction (GFS-BC wired) | partial |
| **Archived model runs (vintages)** | **run-over-run revision** — the highest-alpha signal | planned (*enables* strategy #2) |
| **Sub-seasonal / week 3–4 / monthly** | forward **seasonal** positioning | planned |
| **ISO load + wind/solar generation** forecasts | cross-check Meteologica net load | planned |

**Next priorities:** (2) **ECMWF EPS** ensemble (best spike-probability); (3) **archived runs →
run-over-run revision** (the alpha trigger). Sub-seasonal and cross-checks follow.

---

## 9. Historical load & temperature — the 📈 Load-vs-temperature dashboard

The historical scatter, per-zone sensitivity map/table, the **YTD** comparison, the weather-normalized
growth curve, and the per-zone time series **all read one cached panel set**
(`data/history/ercot_<YYYY>_<MM>.parquet`, built by `src/historical.py` /
`python -m src.backfill_history`). Two inputs only:

| Field | Source | Detail |
|---|---|---|
| **Load (demand) — system** | **Meteologica observation** `…/ERCOT/PowerDemand/Observation/Total/15min` (id **1969**) | the actual metered ERCOT system load; pulled as a ZIP-of-JSON via `get_historical_data`, deduped + resampled to **hourly UTC** |
| **Load (demand) — per zone** | Meteologica `…/PowerDemand/Observation/<zone>/Total/Hourly` (ids **1970–1977**, the 8 weather zones) | each zone's observed demand; sums to ~system within **0.1 %** |
| **Temperature** | **ECMWF ERA5 reanalysis** via the **Open-Meteo archive** (`fetch_archive`) | hourly, ~31 km, for the 8 ERCOT weather-zone cities; **averaged** for the system temp, kept **per-zone** for the zonal views (ERA5 detail in §3) |
| **Net load** | computed | `demand − wind − solar`; wind (id 1929) + PV (id 1865) are **system-only**, so net load can't be zoned |
| **Battery net output** | Meteologica observation | id **7044** — `BatteryStorage/NetOutput/Observation/Total/5min` (**+ = discharge, − = charge**); pulled into `battery_net`, **~2024-09 onward only** (system-wide) |

Cached coverage is whatever's on disk — currently **2022-03 → 2026-05** (2022 lacks Jan–Feb; the
current year is partial, which is exactly why the **YTD** panel clips all years to a common window).
Demand is **MW** (shown as GW); temperature **°F**.

### Batteries in the load — the "battery era"

ERCOT grid-scale battery storage (BESS) went from negligible to dominant *over exactly this window*, so
the weather→load relationship is **not stationary**:

| Date | ERCOT BESS |
|---|---|
| end-2022 | ~1–1.5 GW (negligible) |
| end-2023 | ~3.5–5 GW (transition) |
| end-2024 | ~7.2 GW |
| Apr-2025 | 8.5 GW |
| start-2026 | **13.9 GW** (≈ doubled in 2025) |
| May-2026 | **16.1 GW** |

**How it enters the data:** battery **charging is load** — it *adds* to the `demand` series (mostly
midday / overnight); battery **discharging is supply** — it *lowers net load* in the evening, **not**
demand. So the **demand** scatter carries battery *charging* from ~2023 on, while the **net-load** view
and the evening **diurnal** shape carry the *discharge* (peak-shaving) signal (concepts.md §6).

**Practical boundary:** treat **2022 as the clean, ~battery-free weather→load baseline**; **2023** is the
transition; **2024 →** is materially battery-influenced (2025–26 heavily). On the dashboard the upward
year-over-year drift is **real demand growth (data centres / electrification) + battery charging load**,
*not* weather.

**Removing it (scatter control).** A "Remove battery charging" selectbox (Off / 2025 only / 2025 & 2026)
subtracts the charging component `min(battery_net, 0)` from whole-ERCOT demand for the chosen years.
Daily-mean charging is small per-day but **grew**: ≈ **0.57 GW (2025) → 0.97 GW (2026)**, so it shifts
the 2025→2026 growth read materially — raw **+0.84 GW @66 °F** vs **+1.41** (remove 2025 only) vs **+0.44**
(remove both). "2025 only" assumes 2026's *reported* demand already excludes battery (RTC+B went live
Dec-2025) — but that's a dispatch co-optimisation change, **not** confirmed to be a demand-reporting
change, and 2026's raw demand still contains ~1 GW of charging in id 1969. Use "remove both" for a
*consistent* adjustment unless a Meteologica/ERCOT source confirms the 2026 series is battery-free.

> Sources: Modo Energy ERCOT buildout reports (12 GW Q3-2025; 14 GW entering 2026), S&P Global, FactSet
> "ERCOT Batteries Shifting from Supply to Demand". See concepts.md §6 for how to *isolate* the battery
> component (diurnal evening-peak shaving) from the weather signal.
