# ERCOT Weather-Driven Fundamentals Monitor — Reconciled Plan

> **v1.0 — 2026-06-10 status update (supersedes the v0.3 framing below).**
> Credentials arrived and the build pivoted from a *temperature-difference* view to a
> **net-load → gas-burn fundamentals** monitor (the Meteologica feed has wind/solar/demand/
> price/battery but **no temperature**, so temperature comes from Open-Meteo). See
> [docs/trading-strategies.md](docs/trading-strategies.md) (per-signal input/output/data/status),
> [docs/concepts.md](docs/concepts.md) (definitions), [docs/data-sources.md](docs/data-sources.md)
> (provenance), and the CHANGELOG.
>
> **Architecture — two dashboards (top toggle):**
> - **📡 Live monitor:** ① temperature anomaly map (per-county, all US ISOs, lookbacks +
>   10-yr ERA5 normal); ② forecast-model comparison (9 NWP models + GFS ensemble, look-ahead /
>   historical-forecast modes, per-market); ERCOT net load (demand−wind−solar) with the
>   ECMWF-ENS fan; and **implied gas burn (Bcf/d)** with configurable heat rate + baseload.
> - **🔋 Weather-normalized history:** flexible year/month comparison (2022–2025, summer +
>   winter) with the temperature distribution + weather-response curve + diurnal shape (solar
>   vs battery), holding temperature constant.
>
> **Data:** Meteologica (forecasts/obs/ENS/price/battery, vintaged, by zone) · Open-Meteo (temp
> forecast + ERA5, free) · EIA-930 (actual hourly gas generation, free key — `src/eia.py`,
> wires in next) · StormVista (paid, no creds yet).
>
> **Roadmap (highest-value next):** (2) run-over-run revision · (4) spark spread · EIA-grounded
> burn + full fuel mix (removes the baseload assumption) · ensemble spike-probability ·
> forecast-vs-actual skill. Stack stays lean: Python + Parquet/DuckDB + Streamlit; dbt/Snowflake
> deferred until transforms multiply.
>
> *Quantitative note:* weather-normalized burn fell ~1.5 Bcf/d at a fixed 98°F from 2022→2025
> (solar mostly; battery shows in the evening peak) — so seasonal burn expectations must be
> adjusted down for the same weather as the grid changes.

---

*v0.3 — 2026-06-09. Merges the original dashboard plan (v0.1) with the uploaded `ercot-weather-monitor-project.md`. Data source: Meteologica "API markets" (docs login-gated; flagged assumptions below to confirm once credentials arrive).*

**Phase-1 decision (locked):** ship **both** difference options — **(E) run-over-run forecast revision** and **(B) anomaly vs. seasonal normal** — as a UI toggle. Anomaly uses a published climate-normals baseline (NOAA), so it does *not* require accumulating our own history. Anything depending on a **predictive/ML forecast** (and forecast-vs-realized error) is **deferred** — added later, not now.*

---

## 0. What changed from v0.1

The uploaded monitor doc is a major upgrade and I'm adopting most of it. Three of its ideas are keepers v0.1 lacked:

- **Forecast vintage** (`issue_time` + `valid_time` on every record). This is the single most important design decision in either doc — without it you can't backtest or avoid lookahead bias.
- **Medallion + dbt portability** (bronze/silver/gold, DuckDB now → Snowflake later, transforms unchanged). Clean, standard, defensible.
- **Reframing** from "weather dashboard" to "weather → net load → price" monitor. More valuable, and it gives the future dashboards a coherent through-line instead of a grab-bag.

What v0.1 still contributes: the explicit enumeration of *what "temperature difference" actually means* — which the monitor doc skips, and which is the thing blocking a concrete Phase-1 build (see §3).

---

## 1. Evaluation of the monitor doc

### Strong (keep as-is)
- Vintage dimension — critical, correct.
- Parquet-as-canonical + DuckDB→Snowflake via dbt — pragmatic, low migration cost.
- Airport-level, population-weighted temperature for load — industry standard; matches v0.1.
- Compute-cost discipline (materialized aggregates / serving cache so the dashboard never hits warehouse compute per refresh).
- Timezone handling called out (CPT, DST).
- Phased roadmap toward fundamentals.

### Gaps & risks (where I'd push back)
1. **Scope creep vs. the actual near-term ask.** The concrete deliverable is *one view*: temperature difference over a seasonal interval. The doc balloons to gas, congestion, ORDC, ancillary, ML across 4 phases. That's the right *vision*, but Phase 1 must stay ruthlessly small or it won't ship. The doc says "don't over-engineer," yet dbt + Prefect + medallion + Grafana is already a non-trivial stack for a solo MVP. Recommendation: Phase 1 = Python + Parquet + DuckDB + one Streamlit page. Introduce dbt the moment transforms multiply (Phase 2), keeping the portability story intact.
2. **The "difference" is still undefined — and there are now FIVE readings.** The doc's `fct_forecast_delta` ("run-over-run changes") is actually a *new* one v0.1 didn't have. Full list: (A) forecast − observed, (B) anomaly vs. seasonal normal, (C) period-over-period / YoY, (D) cross-zone, (E) **run-over-run forecast revision**. These need different inputs (see §3). This must be pinned before building.
3. **No observations / actuals ingest path.** The doc pulls *only* Meteologica (forecasts). But forecast-vs-actual error (A) and seasonal normals (B) both require an **observations source** (ASOS/airport, or ERCOT actuals). That's a second, separate ingest pipeline the doc doesn't account for. Real gap.
4. **Seasonal-normal baseline has a data dependency.** Mode (B) needs either a climatology product or *years* of accumulated history. On day 1 we have neither. Either source a normals dataset or accept that (B) matures over time — which makes (E) the better day-1 metric (it needs only two consecutive runs).
5. **Unverified Meteologica facts.** "14-day horizon, CSV/JSON via SFTP or API per run" is stated as fact but the docs are gated. Treat as assumptions to confirm: delivery mechanism (push SFTP vs. pull REST), auth, resolution, history depth, whether observed series exist, rate limits, units, timezone.
6. **Alerting is named but not specified** — no thresholds or trigger logic yet. Fine to defer, but list it as undesigned.

### Net
Adopt the monitor doc's architecture wholesale; tighten Phase 1 scope; add an observations pipeline; and resolve the difference definition — which the vintage model actually makes easy (next section).

---

## 2. Pipeline & workflow (reconciled)

```
Meteologica (forecast, per NWP run)  ─┐
                                      ├─► Ingestion ─► Bronze (raw Parquet, vintaged) ─► Silver (clean/normalize) ─► Gold (marts) ─► Serve API ─► Dashboard + Alerts
Observations (ASOS / ERCOT actuals) ─┘
```

- **Two ingest paths, not one.** Forecast (vintaged: `issue_time`+`valid_time`) and observations (single `valid_time`). They meet in the Gold layer where differences are computed.
- **Differencing + seasonal aggregation live in the Serve/Gold layer**, not the browser — so every future dashboard inherits the same interval logic.
- **Never query Meteologica per page load.** Scheduled pull → own store. A Cowork scheduled task can drive the recurring pull during MVP.
- **Vintage is non-negotiable** on the forecast path from record one.

---

## 3. Dashboard difference options

The dashboard exposes a **difference-mode toggle**. Phase 1 ships the two modes that need **no observations feed and no self-accumulated history**; the rest light up later as their data dependencies are satisfied. Forecasting-dependent modes are deferred per decision.

| Mode | What it shows the user | Inputs needed | Status |
|------|------------------------|---------------|--------|
| **B. Anomaly vs. seasonal normal** | Forecast temp − climate normal → "this week runs +4 °C hotter than a typical mid-June" (demand-stress read) | Meteologica forecast **+ NOAA climate normals** (loaded once) | **Phase 1** |
| **E. Run-over-run revision** | How the forecast for a given `valid_time` moved between consecutive runs → "next week's peak jumped +3 °C since the last run" (fresh-information / trading read) | Meteologica forecast only (≥2 runs) | **Phase 1** |
| D. Cross-zone | Zone A − Zone B at the same time → spatial spread across ERCOT | Meteologica forecast only | Optional Phase 1 |
| A. Forecast − observed | Forecast error vs. what actually happened | Forecast + **observations feed** | Phase 2 |
| C. Period-over-period / YoY | This season vs. the same window last year | ≥1 yr accumulated history | Phase 2+ |
| *(ML predictive overlays)* | Model-driven forecasts, backtests | Forecasting models | **Deferred** |

### Why the two Phase-1 modes are both feasible now

- **(E) Run-over-run** needs only the Meteologica feed — it's pure arithmetic over two forecast vintages (`issue_time` A vs. B for the same `valid_time`). Directly exploits the vintage model.
- **(B) Anomaly** would normally need years of history to define "normal" — **but we don't accumulate it ourselves.** We load **NOAA U.S. Climate Normals (1991–2020)**, a free public product with daily temperature normals for the ERCOT airport stations (IAH, DFW, AUS, SAT, …). Anomaly is then `Meteologica forecast − NOAA normal`. One-time load, no waiting. *(Confirm station coverage when we wire it up.)*

Both sit under the same seasonal interval picker unchanged.

### The two readings are complementary, not redundant
- **Anomaly (B)** answers *"is the absolute weather extreme?"* — the demand/stress signal. Good for "how hot is the upcoming heat wave vs. typical."
- **Revision (E)** answers *"did our information just change?"* — the news/trading signal. Good for "the forecast moved, the market may not have repriced yet."

A trader-oriented monitor genuinely wants both.

## 4. Phase-1 view spec (temperature difference)

- **Controls:** season/interval picker (Summer Jun–Sep, Winter Dec–Feb, custom range); zone/metro selector (all-ERCOT pop-weighted or IAH/DFW/AUS/SAT…); **difference-mode toggle — (B) anomaly vs. normal and (E) run-over-run revision in Phase 1**, (D) cross-zone optional, others greyed-out until their data lands; aggregation (hourly / daily mean / daily max).
- **Visuals:** headline mean difference over the interval with direction (anomaly mode: "forecast runs +4.0 °C above normal this week"; revision mode: "next-week peak revised +3.1 °C vs. prior run"); two series overlaid + difference as filled area/bars; CDD/HDD summary cards; zone small-multiples when multiple zones selected.
- **ERCOT map (choropleth).** A map of Texas shaded by the selected difference value per **ERCOT weather zone** (Coast, East, Far West, North, North Central, South, South Central, West) — diverging color scale (blue = cooler/below, red = hotter/above) so spatial heat differences read at a glance. The map respects the active difference-mode toggle and the interval picker (it shows the interval-aggregated difference). Hover → zone name + value + station(s); click → filters the charts/table to that zone. *Geometry: use ERCOT weather-zone boundaries if we can source them; otherwise approximate by coloring the metro/airport points or county groups mapped to zones.*
- **Summary table.** One row per zone (and an all-ERCOT pop-weighted total row), columns: current/forecast temp, seasonal normal, **anomaly (B)**, **run-over-run Δ (E)**, CDD/HDD for the interval, min/mean/max. Sortable, exportable (CSV), and the numeric companion to the map — the map shows *where*, the table shows *how much*.

## 5. Tech stack (tightened for MVP, doc's vision preserved)

- **Phase 1:** Python (requests) ingest → Parquet (Hive-partitioned by `issue_date`) → DuckDB → **Streamlit** one-pager. cron / Cowork scheduled task. No dbt/Prefect/Snowflake yet.
- **Phase 2+:** introduce **dbt-duckdb** as transforms multiply; FastAPI serve layer; React/ECharts hub when productizing; migrate to **dbt-snowflake** (models unchanged) when scale/sharing demands it — exactly the doc's migration path.

## 6. Phased roadmap (merged)

| Phase | Scope | Storage | Difference modes live |
|-------|-------|---------|-----------------------|
| **1 — MVP** | Meteologica ingest w/ vintages + NOAA normals → DuckDB → Streamlit view with **B + E toggle**, ERCOT map + summary table, simple run-over-run alert | Local Parquet + DuckDB | **B, E** (+ D optional) |
| **2 — Fundamentals** | Add observations feed; load, wind/solar forecast vs actual, DAM/RTM price overlay; introduce dbt | Local / evaluate Snowflake | **A, C** |
| **3 — Microstructure** | Gas (Henry Hub/Waha/HSC), congestion/basis, ORDC, ancillary; net-load & forecast-delta → price | **Snowflake** | all |
| **4 — Predictive** | Forecasting models (TimeXer), backtesting via zero-copy clone, what-if | Snowflake | all |

## 7. Open items to confirm (most need the gated docs)

1. **Difference modes** — Phase 1 ships **B (anomaly)** + **E (run-over-run)** as a toggle (§3). Confirm (D) cross-zone in/out for Phase 1.
2. **Meteologica delivery & spec** — push SFTP vs. pull REST; auth; resolution; history depth; observed-series availability; rate limits; units/timezone.
3. **NOAA Climate Normals** — confirm the 1991–2020 daily-temperature normals cover the ERCOT airport stations we use (IAH, DFW, AUS, SAT, …) and pick the load mechanism (NCEI download once).
4. **ERCOT map geometry** — source weather-zone boundary shapes (GeoJSON) if available; fallback to airport-point or county-to-zone coloring.
5. **Observations source** for mode A (Phase 2) — ASOS/airport vs. ERCOT actuals.
6. **Personal tool vs. shared product** — affects how early we invest in dbt/FastAPI/Snowflake vs. staying on the lean Streamlit MVP.
