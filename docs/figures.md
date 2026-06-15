# Figure Guide — what each figure implies & how a trader reads it

Every figure on the dashboard, in screen order, with three lines each:
**Shows** (what's on it) · **Implies** (the question it answers) · **Read → action** (the trade signal).

The whole dashboard is one chain: `weather → demand → net load → gas burn → price`. Each figure is
one link. Concepts: [concepts.md](concepts.md) · data provenance: [data-sources.md](data-sources.md).

---

## 📡 Live monitor — "what's coming" (forward-looking)

### ① Temperature anomaly map (hybrid: StormVista + Open-Meteo)
- **Shows:** per-county temperature choropleth for the selected ISO. The *View* selector is hybrid:
  **forecast views** — High °, Low °, Anomaly vs the 30-yr ERA5 normal — come from **StormVista**
  (each county coloured by its nearest station, with a **forecast-day slider**); **lookback views** —
  vs Yesterday … vs 1 week / 1 month / **1 year ago**, and vs the 10-yr normal — come from
  **Open-Meteo's ERA5 archive** (the year-over-year comparison StormVista's forward feed can't do).
  Red = warmer, blue = cooler; zone outlines + a per-zone table.
- **Implies:** *Is a heat/cold event building, where, and how anomalous?*
- **Read → action:** big **+anomaly** in the load-heavy zones (Coast/Houston, North-Central/DFW) in summer ⇒ AC surge ⇒ flag for burn (long NG/power). Winter **−anomaly** ⇒ heating + gas freeze-off risk. The *vs-normal* view is the **demand surprise** the market may not have priced.

### 🗺️ ERCOT forecast demand by zone
- **Shows:** Texas choropleth with each ERCOT weather zone coloured by its **forecast demand (GW)** (Meteologica), value labelled; Peak/Mean + horizon toggle.
- **Implies:** *Where does the load — and the gas/thermal need — physically sit, and how much?*
- **Read → action:** North-Central (DFW ~25 GW) and Coast (Houston ~21 GW) dominate; total ≈ ERCOT peak. Pairs with the temperature map: *the map shows where it's hot, this shows where that heat turns into load.* A heat anomaly over a big-demand zone matters far more than over a rural one.

### 🗺️ ERCOT forecast demand by zone
- **Shows:** Texas choropleth, each ERCOT weather zone coloured by its **forecast demand (GW)** (Meteologica), value labelled; a **Forecast-day slider** + Peak/Mean toggle.
- **Implies:** *Where does the load — and the gas/thermal need — physically sit, and how much?*
- **Read → action:** North-Central (DFW ~25 GW) and Coast (Houston ~21 GW) dominate; total ≈ ERCOT peak. Slide the forecast day to watch it evolve. Pairs with the temperature map: *map = where it's hot, this = where that turns into load.*

### ③ ERCOT degree days — demand-weather
- **Shows:** forecast **CDD/HDD** (load-weighted, StormVista) as **one line per selected weather model** via a **"Forecast models" multiselect** (default **GFS + EC**; also GEFS / EPS / GEPS / GFS-BC — each its own latest run), + GEFS **p10–p90 band** + the **30-yr normal** (dashed) + recent **actuals** (green); look-ahead slider; metrics for next-day level, anomaly, ensemble spread.
- **Implies:** *How much demand-weather is coming, in the NG-demand units traders quote — is it above/below normal, and do the models agree?*
- **Read → action:** the **gap to the dashed normal is the anomaly** — above normal ⇒ more AC demand ⇒ **bullish power & gas burn**. **Where the model lines diverge (classically GFS vs EC) is the forecast risk** — a wide model spread *or* band ⇒ low confidence, **size down**; when they converge, conviction is higher. CDD = summer (cooling), HDD = winter (heating). (Live example: a Jun-17 read of GFS 13.7 vs EC 18.1 CDD — a 4.4 spread on one day — that resolves by Jun-18.)

  **③·a Weather → load** (sub-figure)
  - **Shows:** forecast **demand** (red) and **net load** (blue) vs **CDD / high-°F**, each with its slope (GW per degree). A **"Weather model" selector** drives the x-axis, defaulting to the model the demand forecast tracks best (not GFS — see below). Below: a **per-model R² table** (forward CDD vs the Meteologica demand) and a **model-disagreement → demand-range** line. The R² expander also has an **hourly drill-down** — pick a forecast day (defaults to the max model-disagreement day) to see that day's **24-hour Meteologica demand** profile with the **load-weighted intraday temperature** (StormVista 3-hourly) overlaid — so you can see the intraday shape (and the ~1 h demand-peak-lags-temp-peak) behind the daily-mean scatter point.
  - **Implies:** *Does the forecast weather turn into load — and which weather model is the demand forecast actually built on?*
  - **Read → action:** demand tracks weather cleanly (+slope); **net load is decoupled** (slope ≈ 0/negative) because wind+solar swing it — **the vertical gap between the clouds is renewable generation.** A hot day only means high burn **if it's also calm/cloudy**. **Key finding (probed live): Meteologica's demand forecast is ECMWF-driven** — its forward CDD correlation is **EC/EPS R² ≈ 0.75–0.82 vs GFS R² ≈ 0.06**, so GFS is the *worst* weather to relate the demand to; the axis defaults to **EC**. **Trade the demand off EC weather, and read GFS-vs-EC divergence as demand-revision risk.** The bridge turns model disagreement into GW: *cross-model CDD spread × the historical sensitivity (≈ 0.98 GW per StormVista-CDD)* ≈ implied demand uncertainty (e.g. a 4.4-CDD GFS↔EC gap ≈ ~4 GW).

  **③·b Hourly / sub-daily** (sub-figure)
  - **Shows:** 3-hourly temperature (per city or load-weighted, red) + hourly **net load** (blue dotted, whole-ERCOT).
  - **Implies:** *The intraday shape — when does the heat peak and the load ramp?*
  - **Read → action:** temperature peaks mid-afternoon; **net load ramps into the evening as solar fades** — that evening window is where peaker burn and price spikes live. Pick a city (Houston/Dallas) to see its own swing.

### ERCOT net load forecast (demand − wind − solar)
- **Shows:** net load + the ECMWF-ENS **p10–p90 fan**; peak net-load + evening-ramp metrics.
- **Implies:** *The core power fundamental — how much must gas/thermal serve, and how tight is the system?*
- **Read → action:** high peak + steep evening ramp ⇒ **tight system** ⇒ ancillary / peak-price risk. Wide, high **P90** ⇒ spike risk ⇒ **long power / long volatility** (convex payoff). This sets the marginal unit and price.

### Implied power-sector gas burn (ERCOT)
- **Shows:** implied forecast burn (brown) + **actual EIA-930 burn** (green) + ENS band + max ramp; adjustable heat rate / baseload.
- **Implies:** *Power-sector gas demand — forecast vs actual, vs the NG forward.*
- **Read → action:** forecast burn **> market consensus** ⇒ long NG & power; **<** ⇒ short. Green (actual) persistently above brown (proxy) ⇒ your proxy is low (raise baseload/heat-rate or trust EIA). This is the calibration check on the whole chain.

### ERCOT demand forecast — multi-model (Meteologica)
- **Shows:** ERCOT demand forecast under each Meteologica weather-model variant, one line per model — **Meteologica** (their own blend / best central estimate), **ECMWF-ENS** (~6-day ensemble) and **ECMWF-ENSEXT** (**~6-week sub-seasonal** ensemble) — each toggleable; an optional **± ensemble band** (p10–p90 across the ECMWF members); horizon slider out to ~6 weeks. A **Zone selector** runs the whole panel for **Whole ERCOT or any of the 8 weather zones** (the same 3 models exist per zone), and an opt-in **"📊 Spread by zone"** bar chart ranks the cross-model disagreement across all zones.
- **Implies:** *How much demand is coming, how much do the demand models disagree (and **where**), and what's the forward sub-seasonal outlook?*
- **Read → action:** **where the model lines diverge is demand-forecast model risk** (the caption prints the cross-model spread, e.g. whole-ERCOT ~0.8 GW mean / ~3 GW peak — smaller than the ③ *weather* spread because Meteologica's variants are all ECMWF-family). **The system total hides locational risk:** by zone, the disagreement concentrates — e.g. **Coast/Houston ~1.4 GW peak spread vs Far West ~0.3 GW** (sea-breeze/humidity is hard to forecast), so a big slice of the system uncertainty is one zone — relevant to **congestion/zonal** positioning. The **ENSEXT** line is the **forward sub-seasonal demand outlook**, far beyond the ③ weather horizon — useful for positioning into a heat ramp weeks out. (This replaced the old net-load/wind/solar *decomposition* stack.)

---

## 🔋 Weather-normalized history — "is the grid drifting?" (positioning)

### Temperature box
- **Shows:** the temperature distribution (median/quartiles/mean) for each selected period (years or months).
- **Implies:** *What weather each period actually had — the confound normalization removes.*
- **Read → action:** confirms the periods you're comparing had different weather, so the curves below can strip it out and leave only structure.

### ① Weather → demand: correlation & drift
- **Shows:** daily **demand or net-load** vs **CDD/HDD** (gas burn lives on the Live monitor, not here), one fitted line `a + b·DD` per period (dots = binned means, dotted = fit) + a coefficient table (**r**, baseline **a**, slope **b**, value **@DD=15**).
- **Implies:** *How tight is the weather→demand link, and how is it structurally drifting year to year?*
- **Read → action:** **r ≈ 0.9** ⇒ weather almost fully explains demand. The **@DD=15** column = demand at *identical* weather; its climb (e.g. **53.5 → 61.8 GW, 2022→25, +15%**) is **pure structural growth** (data centers/electrification) — *not* weather. **Recalibrate your seasonal burn expectation to today's level, or you'll be structurally too short NG.**

### 🎯 Validation — backtest the model (out-of-sample, leave-one-out CV)
- **Shows:** OOS leave-one-out CV of the demand model at a **resolution toggle** (Season/Month/Week/Daily) + optional **weekday/weekend split**; OOS MAE/bias/R², overfit gap, weekend effect, the **train/test sizes**, and a predicted-vs-actual scatter.
- **Implies:** *How accurate is the model, and is every added piece real rather than overfit?*
- **Read → action:** OOS MAE ≈ **1 GW (~1.5%)** at season/month ⇒ trust the demand/burn forecast and size accordingly; **Week overfits, Daily can't fit** (flagged). The negative **bias** = the drift (a stale model under-predicts). The weekend term cuts OOS error only because it's validated out-of-sample — discipline that keeps the forecast honest.
- **→ Use it to predict:** the fitted `a + b·CDD` (figure ①) **is** a demand forecaster — plug ③'s forecast CDD into the *latest* period's coefficients, attach this OOS MAE as the error bar. Full recipe, rules, and the *demand-not-net-load* caveat in [concepts.md §7](concepts.md#7-using-the-weatherdemand-fit-for-prediction).

---

## 📈 Load vs temperature — "the raw relationship" (historical scatter)

### ERCOT load vs temperature scatter
- **Shows:** every historical point of ERCOT **load (y)** vs **temperature (x, °F)**, one dot per
  chosen **Resolution** (Hourly / Daily / Weekly / Monthly / Yearly = the bucket mean), with a
  **regression curve**. **Zone** selector: *Whole ERCOT*, *All zones (overlay)*, or any of the **8
  weather zones** (a zone plots its *own* demand vs its *own* temperature). **Colour by** Year (a
  curve per year), Month, or None; **Fit** Quadratic (default), Linear, or None; **Load** = Demand or
  Net load (whole-ERCOT only — per-zone is demand-only).
- **Implies:** *What is the actual shape of the temperature→load relationship, where does it bite, and is it drifting?*
- **Read → action:** the cloud is a **U / hockey-stick** — load climbs at the **cold** end (heating)
  and the **hot** end (cooling), with a trough near **65 °F**; that's why the fit is **quadratic**
  (toggle Linear to watch it fail, R²≈0.44 vs 0.94). **Colour by Year** and watch the curve shift
  **up** year-over-year — same temperature, more load = **structural growth** (bullish baseline NG),
  not weather. **Overlay the zones** to see *where* heat becomes load: AC-heavy **North Central (DFW
  ≈ +0.33 GW/°F)** and **Coast (Houston ≈ +0.31)** have steep cooling arms, while **Far West ≈ −0.05,
  R²≈0** is flat (oil-&-gas industrial base load ignores weather) — so a heat anomaly over DFW/Houston
  matters far more than over Far West. Switch to **Net load** (whole-ERCOT) and the curve **flattens**
  — wind + solar decouple it. The 🔋 dashboard quantifies the drift; this one *shows* it raw.
- **Why net load is whole-ERCOT only:** demand splits by zone, but wind is published by geo-region and
  solar is system-only, so `demand − wind − solar` can't be formed per zone — net load stays a system
  quantity.
- **Data in:** load = **Meteologica *observed* demand** (system id 1969 + per-zone 1970–1977); temperature
  = **ECMWF ERA5 reanalysis** (Open-Meteo archive), per zone city, averaged for the system. Net load
  subtracts system wind+solar. Full provenance + the **battery-era** caveat: [data-sources.md §9](data-sources.md).

### 📅 Full-year vs selected month window (apples-to-apples)
- **Shows:** a **2×2** — two Full-year vs window pairs: **① all selected years** and **② 2025 & 2026 only**
  (same format, R² in every legend + a per-pair table) for a close battery-era comparison. Left = each
  year's full data; **right** = every year clipped to the *same* window. Four independent controls let a
  trader slice the relationship freely:
  - **Resolution** (Hourly / Daily / Weekly / Monthly) — the point aggregation.
  - **Month window** — a **range slider** (drag *either* handle): clip every year to *any* contiguous
    span (e.g. **Mar→May** or **Jun→Aug**), or start the low handle at the first month for the classic
    **YTD**. Options span the **union** of all selected years' cached months (so the window can reach
    Aug/Sep/Dec on the full-history years; the newest year just contributes fewer/no points there).
  - **Zone / station** — drill the whole pair to **one of the 8 weather zones** (its city = the station):
    that zone's demand vs **its own** temperature (more precise than the system mean; demand-only,
    since net load can't be zoned). "Whole ERCOT" = the system view.
  - **Hours (trader block)** — keep only a **local-time hour block** before aggregating: *Overnight 1–6 /
    Morning 7–9 / Midday 10–17 / Evening peak 18–22 / Late 23–24 / All*. Each point then becomes that
    **block's mean** — so you read the load–temp curve *for that block* (e.g. the **on-peak** curve, where
    scarcity actually bites, vs the overnight curve).

  All four apply to **both** panels and **both** pairs. Each year's **R² shows in both legends**, plus a
  **per-year table**: fit R² for *both* panels + the **actual temperature each window had** (mean /
  min–max) and the level at a common reference temp — so you separate real growth from a warmer/colder year.
- **Implies:** *Is the current (partial) year actually growing — and does that hold zone-by-zone and in the
  on-peak block I trade?*
- **Read → action:** the newest year (e.g. 2026) has **no summer yet**, so on the full-year panel its
  curve looks short and low — misleading. On a fixed **month window** all years cover the same months, so
  the **vertical gap between the year-fits at a fixed temperature is the clean growth** (e.g. system demand
  @55 °F climbed **39.9 → 48.5 GW, 2022→2026, +22 %**). Drill to **Evening peak 18–22** to see whether the
  *on-peak* curve is drifting faster than the daily average (the block that sets scarcity prices), and to a
  single zone (e.g. North Central / DFW) to localise the growth. Use it to size your seasonal baseline —
  per block, per zone — before the hot months arrive.

### 🗺️ Per-zone temperature sensitivity (map + table)
- **Shows:** **side-by-side with the scatter (1×2, shared years)** — a Texas choropleth (same format
  as the Live monitor's demand-by-zone map) colouring each weather zone by its **cooling sensitivity**
  (GW of demand per +1 °F on hot days; toggle to heating sensitivity or mean demand), with a
  full-width table below of Mean GW · Cool GW/°F · Cool R² · Heat GW/°F · Heat R². It has its **own
  Interval selector** (Hourly→Yearly), independent of the scatter — so you can read e.g. *Per-zone
  response (hourly)* while the scatter stays daily. A **Quantile band**
  toggle on the scatter overlays the **P10–P90** spread of load at each temperature (+ P50) — the
  conditional distribution, not just the mean fit.
- **Implies:** *Where does a heat event actually turn into load?*
- **Read → action:** the **AC-driven Texas Triangle** lights up — **Coast (Houston ≈ +0.35 GW/°F)**,
  **North Central (DFW ≈ +0.34)**, South Central (+0.17) — while **Far West (≈ −0.03, R²≈0)** is flat
  (oil-&-gas industrial base load ignores weather). So weight a heat anomaly by *which* zone it sits
  over: hot over Houston/DFW ⇒ big demand/burn response; hot over Far West ⇒ little. The historical,
  weather-only structural companion to the Live monitor's *forecast* demand-by-zone map.

### 🔬 Per-station fits (expander, open by default)
- **Shows:** a 2×4 grid (enlarged, height 700), one subplot per ERCOT weather zone (its city = the
  weather station): that zone's **actual demand (GW) vs its own ERA5 temperature (°F)**, with **one fit
  curve per selected year, colour-matched to that year's points** — so the **year-over-year drift** of the
  demand↔temperature curve is overlaid on the same panel (curves rising = structural growth). Per-year
  **R²** is in a **zone × year table below the grid** (not in the titles — 5 values won't fit; blank cell
  = too few points / too flat to fit). **Its own independent control set** (separate from the 2×2 pair):
  a **"Years to show" multiselect** (the year menu — pick which years overlay; independent of the top
  Years selector, colours stay stable per calendar year), **Resolution** (Hourly/Daily/Weekly/Monthly), a
  **Month range slider** (contiguous span, e.g. Jun→Aug = summer), a **double-ended Hour range**
  (*from-hour → to-hour*, local Central, 0–23 — e.g. 18→22 = evening peak, 0→6 = overnight), and a
  **Fit method** selector. A live header states the resulting **frequency, hour range, month span, exact
  date span and point count**; if the chosen years have no data in the window it says so instead of
  drawing an empty grid.
- **Choosing the fit (Fit method + comparison table).** Demand↔temperature is a **U / hockey-stick** —
  heating arm at the cold end, cooling arm at the hot end, a flat deadband near a **balance point** (~60–65 °F)
  — so a straight line is wrong (it can only follow one arm). Options: **Quadratic** (default — a robust
  smooth U), **Piecewise** (the physically-grounded balance-point HDD/CDD model: independent heating &
  cooling slopes meeting at `Tbp`), **Cubic**, **Linear**, or **Auto (best fit)** (picks per zone). The
  **second table** below the grid reports **adjusted R²** for all four methods per zone + the **Best** one
  + the piecewise **BalPt °F**. Empirically (5-fold CV on the cache): **linear is much worse everywhere**;
  **Quadratic and Piecewise are close and best** (Piecewise wins the cooling/heating-split metros —
  Coast/Houston, North, South Central; Quadratic the rest); **Cubic never genuinely beats quadratic** (it's
  tail-overfit, so Auto never picks it); **Far West is weather-decoupled** (all ≈ 0 — no fit helps).
- **Implies:** *How weather-driven is each part of ERCOT, and is its curve drifting up — in the block and
  season I trade?*
- **Read → action:** **R² is the headline** (the table) — the fraction of a zone's demand variation
  explained by temperature. **North Central 0.89 / Coast 0.85** (AC metros, tight U) vs **Far West 0.00**
  (flat cloud — oil-&-gas industrial load decoupled from weather) and **North 0.24** (sparse/mixed). So a
  heat forecast is "load news" for DFW/Houston but noise for Far West; weight your weather signal by each
  zone's R². The **per-year curves** show *where* on the temperature axis growth is concentrated (e.g. the
  hot-end arm lifting faster = cooling-load growth). Narrow **Years to show** to 2025 vs 2026, **Hours** to
  18→22 and **Months** to Jun→Aug to compare the *summer evening peak* curve year-over-year, zone by zone.

### 📉 Per-zone load — time series (TradingView-style)
- **Shows:** the raw observed demand curve over the full cached history (2022→2026) with a
  **selectable Interval** (Hourly / Daily / Weekly / Monthly = the bar size), a **Zones multiselect**
  (tags — overlay any combination of Whole ERCOT + the 8 zones), and plotly **range buttons**
  (1w/1m/3m/6m/1y/all) + drag-to-zoom — like a TradingView chart.
- **Implies:** *What did load actually do, hour by hour / day by day, and when?*
- **Read → action:** scrub the history at any interval — summer cooling peaks (~70–75 GW), winter
  dips, and the **winter-storm spikes** (Elliott Dec-22, the Jan freezes) jump out at hourly/daily.
  Overlay zones to compare their shapes, or zoom a single event. The raw-data companion to the
  weather-normalized views.

### 📈 Weather-normalized load growth
- **Shows:** each year's daily demand with the **weather removed** (held at the normal seasonal
  temperature), one line per year across the calendar (Jan→Dec). Its **own Zone selector** (Whole
  ERCOT or any of the 8 zones, independent of the scatter), a **Method** toggle (**Quadratic**
  `demand~temp` or the **degree-day model** `a + b·CDD + c·HDD`), and an **Interval** selector (Daily /
  Weekly / Monthly = the seasonal-curve granularity). Years aren't extrapolated past the temperatures
  they actually saw (a partial year stops mid-curve).
- **Implies:** *After stripping weather, how much has baseline demand grown — where, and in which season?*
- **Read → action:** the curves **stack upward** year-over-year = **structural growth** (data centres,
  electrification) — system-wide, normal-summer demand climbed **58.6 → 69.6 GW (2022→2025, +19 %)**,
  all of it non-weather. **Switch zones** to see *where* it's growing: **Far West +58 %** (Permian /
  West-Texas data centres — and its curve is *flat*, i.e. industrial not AC) vs ~+10 % for Coast /
  North Central. The **summer hump is cooling**, the winter rise is heating; the seasonal gap is the
  growth. The seasonal-curve form of the 🔋 dashboard's `@DD=15` drift — **recalibrate your seasonal
  burn baseline to today's level, not 2022's**, and weight the fastest-growing zones.

---

## ❄️ Feb 2021 Winter Storm Uri — "what was the real demand?"

*Location:* an **expander directly under the Per-station fits, in the 📈 Load vs temperature dashboard** (not a standalone tab).
Full method write-up: [`docs/winter-storm-uri-2021.md`](winter-storm-uri-2021.md) (summary in `concepts.md §8`).

### (1) Counterfactual demand reconstruction (time series)
- **Shows:** the Uri week (Feb 8–20, 2021), hourly: **observed** demand (black — *collapses* during the
  blackouts, because it's curtailed served-load, not real demand), **latent** demand (red + 95 % band —
  what demand *would* have been with no curtailment), **no-storm** demand (green — at normal Feb weather),
  and temperature (blue, right axis); the rolling-blackout window is shaded.
- **Implies:** *During the blackouts we don't observe demand — what was it actually?*
- **Read → action:** the **black→red gap is unserved load** (peaks ~**43 GW**; latent peak ~**89 GW** vs
  ~69 GW served). **Green ~49 GW** is the "no-storm" counterfactual. Two lessons for risk: (1) extreme-cold
  demand is far larger than the served peak suggests (size winter reliability / scarcity to *latent*, not
  served); (2) you **cannot** fit a weather→load model on curtailed days — exclude them. Source: **EIA-930
  demand + ERA5** (Meteologica has no 2021); model `a_year + b·HDD + c·HDD² + weekend + hour`, R²=0.86,
  with a leverage band that widens into the extrapolated extreme cold.

### (2) Demand vs temperature — analog reference (the reusable tool)
- **Shows:** daily-mean **demand↔temperature** from un-curtailed winters (grey cloud) + a fitted curve
  (solid in-sample, **dotted** into Uri-class cold); **black ✕** = Uri's *curtailed* observed days sitting
  *below* the curve; **red ★** = the latent estimate *on* the curve.
- **Read → action:** for the **next** forecast deep-freeze, read **expected ERCOT demand straight off this
  curve** at the forecast temperature — a fast analog peak-demand estimate, and the censored-data lesson
  made visual (the ✕ marks fall off the curve only because load was shed). See `docs/winter-storm-uri-2021.md` §8 for
  the full trader playbook (analog demand, sizing scarcity to latent, unserved × price-cap, stress tests,
  real-time latent nowcast).

---

## One-line cheat-sheet
> *Map = is it hot/anomalous & where? · Demand map = where's the load? ·
> Degree days = how much demand-weather (vs normal)? · Weather→load = will renewables eat it? ·
> Net load/burn = how much gas demand? · Actual vs forecast = is the model right? ·
> History ①/🎯/②/③ = is the grid structurally drifting, and is my model trustworthy? ·
> Load-vs-temp scatter = what's the raw U-shaped relationship, and is the curve drifting up?*
