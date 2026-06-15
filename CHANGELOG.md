# Changelog

## [0.40.0] - 2026-06-14
### Added
- **Per-zone multi-model demand.** The multi-model demand overlay gained a **Zone selector** (Whole ERCOT +
  the 8 weather zones) — the same 3 Meteologica models (Meteologica blend / ECMWF-ENS / ECMWF-ENSEXT) exist
  per zone. Zone→content-id resolution is built **dynamically from the catalog paths** (`demand_model_catalog`,
  no hardcoded ids); `load_demand_models(region)` now takes a region. Plus an opt-in **"📊 Spread by zone"**
  bar chart (`demand_spread_by_zone`) ranking the cross-model disagreement across all 8 zones — surfacing
  **where** the demand-forecast uncertainty lives (validated live: **Coast/Houston ~1.4 GW peak spread vs
  Far West ~0.3 GW**), i.e. the locational risk the system total hides. End-to-end validated (catalog,
  per-zone load, spread; bare-mode clean). `app/app.py`. Docs: `docs/figures.md`.

## [0.39.0] - 2026-06-14
### Removed
- **Demand decomposition** stack (net load + wind + solar = demand) on the Live monitor, and its
  "Demand decomposition" toggle.
### Added
- **Multi-model demand overlay** (Live monitor) — ERCOT **system demand** forecast under each Meteologica
  weather-model variant on one chart, each toggleable: **Meteologica** (own blend, id 1943), **ECMWF-ENS**
  (id 1957, ~6-day) and **ECMWF-ENSEXT** (id 7355, ~6-week sub-seasonal). New cached `load_demand_models()`
  (central series via `central_column`, p10–p90 via `member_columns`); horizon slider to ~42 d; optional
  **± ensemble band**; the caption prints the **cross-model spread = demand-forecast model risk** (live:
  ~0.8 GW mean / ~3 GW peak over the common window — tighter than the ③ *weather* spread since the variants
  are all ECMWF-family). The **ENSEXT** line gives a forward sub-seasonal demand outlook beyond the ③
  weather horizon. Content IDs probed live; loader + spread validated end-to-end (bare-mode execution
  clean). `app/app.py`. Docs: `docs/figures.md`.

## [0.38.1] - 2026-06-14
### Added
- **Hourly demand drill-down in the ③·a per-model R² expander.** The R² diagnostic compares *daily-mean*
  CDD to *daily-mean* demand; the new drill-down lets the trader pick a forecast day (defaults to the **max
  model-disagreement day**) and see that day's **24-hour Meteologica demand** profile with the day's
  **load-weighted intraday temperature** (StormVista 3-hourly) on a second axis. Surfaces the intraday
  shape — and the ~1 h **demand-peak-lags-temp-peak** (thermal mass + evening occupancy) — that the daily
  mean hides. Reuses the existing `load_netload` / `load_ercot_temp_hourly` loaders; guarded. Verified
  against live data (Jun-17: demand peak 17:00 / 75.6 GW vs temp peak 16:00 / 84 °F). `app/app.py`.

## [0.38.0] - 2026-06-14
### Added
- **③·a Weather → load now uses the right weather model + quantifies model risk.** The sub-figure's
  weather x-axis was hardcoded to GFS; a live probe showed **Meteologica's ERCOT demand forecast is
  ECMWF-driven** — its forward CDD correlates with **EC/EPS at R² ≈ 0.75–0.82 but GFS at only R² ≈ 0.06**.
  So:
  - New cached **`load_wdd_demand_corr(kind)`** — correlates each StormVista model's forward CDD with the
    Meteologica demand forecast → a per-model **R² table** + the **best-tracking model** + the cross-model
    **CDD spread**. ③·a's new **"Weather model" selector** defaults to that best model (EC), with the R²
    table in an expander.
  - New cached **`load_cdd_sensitivity()`** — robust demand↔CDD slope from 1,000+ historical cooling days,
    **rescaled to StormVista pop-weighted CDD units** via the ratio of StormVista's 30-yr CDD normal to the
    ERA5 system normal (`b_sv = b_sys / scale`, scale ≈ 0.96 ⇒ **b_sv ≈ 0.98 GW/CDD**).
  - **Model-disagreement → demand-range bridge:** cross-model CDD spread × b_sv ⇒ implied demand
    uncertainty (e.g. a 4.4-CDD GFS↔EC gap ≈ ~4 GW). **Read GFS-vs-EC divergence as demand-revision risk.**
  - Methodology validated empirically (synthetic ground-truth for the rescale direction); adversarial
    review returned two findings, **both confirmed false positives** (pd.Timestamp f-string formatting; the
    rescale direction — `b_sys/scale` proven correct, recovers true slope). `app/app.py`. Docs: `figures.md`.

## [0.37.0] - 2026-06-14
### Added
- **Multi-model forecast overlay on the ③ degree-days chart.** A new **"Forecast models" multiselect**
  (default **GFS + EC**) draws one CDD/HDD forecast line per selected **StormVista** weather model, each on
  its own latest run — so the trader can add/remove models and read the **inter-model divergence as forecast
  risk** (classic GFS-vs-EC). New cached `load_model_wdd(model, kind)` loader (returns `(series, date,
  cycle)` or `None`; guards empty/all-NaN); module-level `WDD_MODELS` / `WDD_MODEL_COLOR` / `WDD_MODEL_DESC`.
  The existing GEFS p10–p90 band, 30-yr normal, and actuals are kept.
  - **API review first** (both vendors probed live, 2026-06-14): **StormVista** serves **6 ERCOT WDD models**
    in our subscription — `gfs`, `ecmwf` (EC), `gfs-ens` (GEFS), `ecmwf-eps` (EPS, 51 members), `cmc-ens`
    (GEPS), `gfs-ens-bc`; `cmc`/`icon-global` 404. **Meteologica** is a *demand/renewables* forecaster (not
    CDD): wind/PV under 9 weather models, **demand** under ECMWF-ENS / ECMWF-ENSEXT / Meteologica — noted as
    a future *demand-overlay* option. Reviewed via the `code-reviewer` agent (no high-severity issues; added
    an all-NaN guard). `app/app.py`. Docs: `docs/data-sources.md §8`, `docs/figures.md`.

## [0.36.0] - 2026-06-13
### Added
- **Per-station fits: choose the most appropriate curve, and show why.** New **Fit method** selector
  (Quadratic default / Linear / Cubic / **Piecewise** / **Auto (best fit)**) plus a second table below the
  grid comparing **adjusted R²** of all four methods **per zone** + the chosen **Best** + the piecewise
  **balance point** (`BalPt °F`).
  - New `src/wxnorm.py` helpers: **`seg_fit`** — a piecewise **balance-point HDD/CDD** two-line fit
    (`y = a + b_h·max(Tbp−T,0) + b_c·max(T−Tbp,0)`, `Tbp` chosen by grid search; same return shape as
    `poly_fit` + `tbp`/`kind`); **`adj_r2`** (adjusted R²); `poly_fit` now also returns `p` (degree).
  - **Auto** picks, per zone, the most-preferred model within 0.005 adj-R² of the top (preference
    Quadratic ▸ Piecewise ▸ Cubic ▸ Linear) — a parsimony tie-break so **cubic is never auto-selected**
    (it's tail-overfit and never beats quadratic on 5-fold CV). Replaces the previous hardcoded quadratic
    (`ps_deg`); the panel is now fully independent of the top Fit selector.
  - **Empirical basis** (5-fold CV-RMSE on the cache): linear is far worse everywhere; Quadratic &
    Piecewise are close and best (Piecewise wins the cooling/heating-split metros Coast/North/South Central,
    Quadratic the rest); Far West is weather-decoupled (all ≈ 0). Reviewed via the `code-reviewer` agent
    (no high-severity issues; widened the `seg_fit` balance-point search to the 5–95th pct for narrow
    month windows). `app/app.py` + `src/wxnorm.py`. Docs: `docs/figures.md`.

## [0.35.0] - 2026-06-13
### Changed
- **Per-station fits → per-year curves + a year menu.** The panel now classifies by **location only**
  (the 8 zone subplots) and overlays **one fit curve per selected year**, colour-matched to that year's
  points, so the **year-over-year drift** of each zone's demand↔temperature curve is visible on the same
  figure (replaces the single pooled curve). New panel-local **"Years to show" multiselect** (`ps_years`,
  independent of the top Years selector; year→colour map keyed off `sel_years` so colours stay stable per
  calendar year). Per-year **R²** moved out of the subplot titles into a **zone × year `st.dataframe`
  table** below the grid. Figure **enlarged to height 700**. Design chosen via a 3-lens design panel +
  synthesis (workflow).
- **Per-station year label** (the figure's "Year" legend) moved **up** and **enlarged** (font 16, top
  margin 104) so the year colour key reads clearly above the grid.
- **Relocated the ❄️ Feb 2021 Uri case-study expander** to sit **directly under the Per-station fits**
  (was at the bottom of the page), so the two location-level studies are adjacent. `app/app.py` only.
### Documentation
- **New standalone case-study doc: `docs/winter-storm-uri-2021.md`** — the canonical, self-contained
  write-up of the 2021 Uri counterfactual (problem, model + design matrix, the un-curtailed-training step,
  latent/no-storm reconstruction, leverage band, validation, caveats, trader playbook, code pointers).
  `concepts.md §8` collapsed to a short summary + pointer to avoid drift; in-app captions, `figures.md`,
  and the `src/uri2021.py` docstring now reference the standalone doc.
### Fixed
- **Per-station empty-window edge case** (found in adversarial review): when the chosen years had no data
  in the month/hour window, an **empty figure + all-NaN R² table** rendered instead of a message. Root
  cause was a **tz-edge leak** — `lt_scatter` converts the hourly UTC panel to local Central, so e.g. a
  Jan-2026 UTC hour maps to local `2025-12-31`; that lone off-year point passed the month filter and set
  `span_lo`, defeating the empty-state guard. Fixed by dropping tz-edge rows whose **local year ≠ the
  fetched year** in the per-station gather loop (the same idiom the 2×2 pair already uses), plus an
  explicit `st.info` when no data matches. Validated against the live data pipeline. `app/app.py` only.

## [0.34.0] - 2026-06-12
### Changed
- **2×2 Full-year vs window: month-window options now span the *union* of selected years' cached months**
  (was capped at the newest year's extent, ~May). The trader can now extend the window to **Aug/Sep/Dec**
  on the full-history years (2022–2025); the newest year (2026, cached through ~May) simply contributes
  fewer/no points in a later window (handled by the existing empty-window guards).
- **Per-station fits: points coloured by year + fit always drawn.** Each zone subplot now colours its
  points **by year** (shared legend) so the structural-growth drift is visible, and the **quadratic fit +
  R²** is drawn **independent of the scatter's Fit selector** (previously, setting Fit = None hid the
  per-station curves and R²). `ps_deg = deg or 2` guarantees a curve; the pooled fit + R² stay in each
  title. `app/app.py` only. Docs: `docs/figures.md`.

## [0.33.0] - 2026-06-12
### Added
- **Per-station fits got its own independent control set** (separate from the 2×2 pair): besides
  **Resolution**, a **Month range slider** (contiguous span across the pooled years) and a
  **double-ended Hour range slider** — the trader picks *from-hour → to-hour* (local Central, 0–23, e.g.
  18→22 evening peak) instead of preset blocks; each point becomes the mean over those hours. The header
  now reports the live **frequency · hour range · month span · exact date span · point count**. Reuses the
  `wxnorm.lt_scatter(hours=…)` filter; month/hour filtering is pooled across all selected years (the
  per-station view is intentionally all-years-pooled, not per-year). `app/app.py` only. Docs: `docs/figures.md`.

## [0.32.0] - 2026-06-12
### Added
- **Per-zone/station drill + trader hour-block filter on the Full-year vs window pair.** Two new
  selectors on that section (independent of the top scatter):
  - **Zone / station (this pair)** — `Whole ERCOT` + the 8 weather zones. Picking a zone plots that
    zone's demand vs **its own city temperature** (`temp_<zone>` / `demand_<zone>`, demand-only); defaults
    to the top Zone if a single one is selected.
  - **Hours (local, trader block)** — `All / Overnight 1–6 / Morning 7–9 / Midday 10–17 / Evening peak
    18–22 / Late 23–24`. Keeps only those **local-Central hours-of-day** before aggregating, so each point
    becomes that **block-mean** (on/off-peak load–temp curves). Implemented as a new `hours` arg on
    `wxnorm.lt_scatter` (filters after tz-convert, before resample; `hours=None` = unchanged).
  Both apply to **both** panels and **both** pairs; plot titles gain a ` · <block>` suffix, the battery
  `Batt −GW removed` figure is computed on the same local month + hour mask, and the per-year table tracks
  the chosen zone/window/block. `app/app.py` + `src/wxnorm.py`. Docs: `docs/figures.md`.

## [0.31.0] - 2026-06-12
### Changed
- **Full-year vs YTD → flexible month window.** The right-hand panel's single-ended *"Jan 1 → end of X"*
  YTD slider is now a **range slider** (`st.select_slider` with a `(start, end)` value): the trader can
  clip every year to **any contiguous month span** — e.g. **Mar→May** — for an apples-to-apples per-year
  fit, or leave the start at the first month for the classic YTD. The window is applied identically to
  every year, both pairs (all years / 2025 & 2026), and the battery-charging removal. Plot titles read
  *"Window — Mar → May"*; the per-pair table columns are relabeled `Win mean °F / Win min–max °F / Win R²
  / Win @<ref>°F` (the reference temperature follows the window's median). Empty-window edge cases are
  guarded (no-data years render `—`/`NaN` instead of erroring). `app/app.py` only.

## [0.30.0] - 2026-06-12
### Changed
- **Relocated the ❄️ Feb 2021 Uri panel** from a standalone 4th dashboard tab **into an expander at the
  bottom of the 📈 Load vs temperature dashboard** (it *is* a load-vs-temperature study, so it belongs
  with its peers). The radio is back to **3 tabs**. Logic moved into module-level `uri_bundle()` (cached)
  + `render_uri_panel()` in `app/app.py`; behaviour is otherwise unchanged.
### Added
- **Second Uri figure — "Demand vs temperature — analog reference"** (`uri2021.temp_curve`): the
  un-curtailed winter **demand↔temperature** cloud + fitted curve (solid in-sample, **dotted** into
  Uri-class cold), with **black ✕** = Uri's curtailed observed days falling *below* the curve and
  **red ★** = the latent estimate on the curve. Built to be **reused**: read expected demand straight off
  the curve for the *next* forecast deep-freeze.
- **Method documentation: `docs/concepts.md §8`** — full Uri counterfactual methodology (the censored-data
  problem, the model, the two counterfactuals, the leverage prediction interval, validation, caveats) and
  **§8.7 the trader analog playbook** (analog demand off the curve, sizing scarcity to *latent* not served,
  unserved-load × price-cap = scarcity rent, position stress-tests, real-time latent-demand nowcast).
  `docs/figures.md` updated for the new location + second figure.

## [0.29.0] - 2026-06-12
### Added
- **New dashboard: ❄️ Feb 2021 Winter Storm Uri — counterfactual demand** (4th tab, `src/uri2021.py`).
  During Uri ERCOT shed ~20 GW (rolling blackouts), so the **observed demand on Feb 15–18 is curtailed
  served-load, not true demand** (on the coldest day, Feb 16, observed demand *fell below* milder days —
  impossible without load shed). The panel reconstructs two counterfactuals from a weather→demand model
  fit on **un-curtailed** winter hours:
  - **latent demand** (no curtailment) — peaks **~89 GW** modelled vs ~69 GW served ⇒ **up to ~43 GW
    unserved load** (daily-mean latent ~78 GW on Feb 16, the better-supported figure);
  - **no-storm demand** (normal February weather) — **~49 GW** peak.
  Figure overlays observed / latent (+95 % band) / no-storm / temperature, with the blackout window shaded.
- **Model:** `demand ~ a_year + b·HDD + c·HDD² + weekend + hour-of-day`, OLS on Dec–Feb of 4 winters
  (2019–2023), **R²=0.86**; per-year intercepts absorb load growth, **HDD²** captures the extreme-cold
  steepening. Uncertainty is a **leverage-based prediction interval** that *widens* where we extrapolate.
- **New data source path: EIA-930 *demand*** (`region-data`, type `D`, respondent ERCO) + ERA5 — because
  **Meteologica has no pre-Dec-2021 data**. Cached to `data/uri2021/panel.parquet`; build with
  `python -m src.uri2021`.
### Notes & Caveats
- The storm's coldest *hours* (~5 °F) dip below the coldest training hour (~14 °F), so the hourly **peak
  latent is a short extrapolation** — the band widens there; the daily-mean (~78 GW) is the robust read.
  Headline peak (~89 GW) sits a bit above published Uri estimates (~76–82 GW), reflecting the HDD² tail.

## [0.28.0] - 2026-06-12
### Added
- **Battery column + "Remove battery charging" control** on the 📈 Load vs temperature scatter.
  `historical.build_panel` now also pulls **ERCOT battery net output** (Meteologica obs id **7044**,
  `BatteryStorage/NetOutput/Observation`; + = discharge, − = charge) into a `battery_net` column —
  available **~2024-09 → 2026-05** (older months 404 → absent). The scatter has a selectbox
  **Off / 2025 only / 2025 & 2026** that subtracts battery **charging** from whole-ERCOT demand
  (`demand + min(battery_net, 0)`, system-only; ignored for single zones/overlay).
- **YTD is now a 2×2**: the Full-year vs YTD section renders **two pairs** — ① all selected years, and
  ② **2025 & 2026 only** (same format, R² in every legend + a per-pair table) — for a close battery-era
  comparison. The "Remove battery charging" toggle flows through both pairs (whole-ERCOT). (Refactored
  into a reusable `_ytd_pair` renderer.) *Exploratory — to be pruned later.*
- **`Batt −GW removed` column** added to the per-pair YTD tables. The battery removal *works* but is
  visually tiny on the chart (~0.5–1 GW shift on a ~50 GW axis), so the column makes it explicit in
  numbers — e.g. 2025 @66 °F moves 49.1 → 48.6 GW, and the 2025→2026 growth goes +0.83 (off) → +1.40
  (remove 2025) → +0.43 (remove both). The curves "looking the same" is the small magnitude, not a bug.
### Notes & Caveats
- **Charging grew**: daily-mean charging ≈ **0.57 GW (2025) → 0.97 GW (2026)** — so the choice of mode
  materially changes the 2025→2026 growth read (whole-ERCOT demand @66 °F): **raw +0.84 GW**,
  **remove-2025-only +1.41 GW** (widens), **remove-both +0.44 GW** (narrows, because 2026 has more
  battery to remove). The "2025 only" mode assumes 2026's *reported* demand already excludes
  battery — **unverified** (RTC+B, live Dec-5-2025, is dispatch co-optimisation, not a demand-reporting
  change; we pull the same series for both years, and 2026's raw demand still contains ~1 GW of
  charging). Provided both modes so the data shows which reconciles the years.

## [0.27.0] - 2026-06-11
### Added
- **Full-year vs Year-to-date (apples-to-apples) panel** on the 📈 Load vs temperature dashboard: two
  per-year scatters side by side — left = each year's full data; right = every year clipped to the same
  calendar window (Jan 1 → the furthest day the newest year reaches, ~May 30). Lets the current partial
  year (2026, no summer yet) be compared fairly — demand **@55 °F climbs 39.9 → 48.5 GW (2022→2026,
  +22 %)** on the YTD panel, confirming it's on-trend. (Fixes a tz-edge artifact that put a stray hour
  of the new year in the prior December.) **Follows the dashboard's Zone / Load / Fit selectors** — e.g.
  switch to Far West demand to see its **+73 % YTD growth** (2022→26 @70 °F); overlay falls back to
  whole-ERCOT (the YTD compares years, so colour = year). Each year's **R² is shown in both legends**,
  and a **per-year table** reports fit R² for *both* panels, the **actual temperature each YTD window
  had** (mean + min–max — so a warmer/colder year is distinguishable from growth), and the
  weather-normalized demand at a common reference temp (YTD median, e.g. @66 °F: **40.6 → 50.0 GW,
  2022→26**). A **cutoff slider** sets the YTD window (Jan 1 → end of Jan … May, bounded by the newest
  year) so you can watch R² and the growth read evolve as the window fills in (month-based clip, so it's
  leap-year-safe; years missing early months just drop out of the narrow windows). It also has its own
  **Resolution** selector (Hourly / Daily / Weekly / Monthly = the scatter-point aggregation) — coarser
  intervals smooth the points and tighten R² (hourly ~0.7 with intraday scatter → weekly/monthly ~0.9–1.0).
- **Per-station fits (expander)** — a 2×4 small-multiples grid, one subplot per ERCOT weather zone:
  each zone's **actual demand vs its own ERA5 temperature** with the fit curve + **R²** in the title.
  The R² makes "how weather-driven is this zone" visible at a glance — **North Central 0.89 / Coast 0.85**
  (AC metros, tight U) down to **North 0.24** and **Far West 0.00** (flat cloud — industrial load ignores
  temperature). Own Resolution selector; follows the Years selection. (`make_subplots`.)
### Docs
- **Documented the historical-scatter data sources** (`data-sources.md §9`): load = Meteologica
  *observed* demand (system id 1969 + per-zone 1970–1977); temperature = ECMWF ERA5 (Open-Meteo
  archive); net load = demand − system wind/solar. The in-app caption now states this too.
- **Battery-era documentation** (`data-sources.md §9` + `concepts.md §6`): ERCOT BESS timeline
  (~1.5 GW end-2022 → **16 GW May-2026**) and how it enters the data — **charging is load** (inflates
  `demand` from ~2023), **discharging is supply** (lowers net load / shaves the evening peak). Recommended
  boundary: **2022 = clean battery-free baseline; 2024 → materially battery-influenced**.

## [0.26.0] - 2026-06-11
### Added
- **Figure 3 — Weather-normalized load growth** on the 📈 Load vs temperature dashboard: each year's
  daily demand with the **weather removed** (held at the normal seasonal temperature), drawn across
  the calendar (one line per year). The gap between curves is **pure structural growth** — at normal
  summer weather, ERCOT demand rose **58.6 → 69.6 GW (2022→2025, +11.1 GW / +19 %)**. Method
  (`wxnorm.wn_seasonal_curves`): (1) normal temperature by week-of-year (pooled, smoothed), (2)
  per-year fit, (3) evaluate each year's fit at the normal weekly temperature. Years are **not
  extrapolated past their observed temperature range**, so a partial year (2026, Jan–May) correctly
  stops mid-curve instead of inventing a summer.
  - **Per-zone + method + interval controls.** Figure 3 has its **own Zone selector** (Whole ERCOT or
    any of the 8 zones — independent of the scatter), a **Method** toggle (**Quadratic** `value~temp`
    or **degree-day** `a + b·CDD + c·HDD`), and an **Interval** selector (Daily / Weekly / Monthly =
    the seasonal x-axis granularity, via `wn_seasonal_curves(freq=…)`). The per-zone view is revealing
    — **Far West grew +58 %** (2022→25, Permian/data-centre industrial load) vs ~+10 % for Coast/North
    Central; the two methods agree closely (system-wide +19 % poly vs +17 % dd).
- **Per-zone response gets its own Interval selector.** The sensitivity map + table now have a
  dedicated **Interval** dropdown (Hourly/Daily/Weekly/Monthly/Yearly) beside the map, **independent
  of the scatter's Resolution** — e.g. view "Per-zone response (hourly)" while the scatter stays daily.
- **Per-zone load time series (TradingView-style).** A new chart of raw observed demand over the full
  cached history (2022→2026) with a **selectable Interval** (Hourly / Daily / Weekly / Monthly = the
  bar size), a **Zones multiselect** (tags — overlay any combination of Whole ERCOT + the 8 weather
  zones, each a coloured line), and plotly **range buttons** (1w/1m/3m/6m/1y/all) + drag-to-zoom to
  navigate the window. WebGL for the dense hourly series (~36 k pts whole-ERCOT).
- **Quantile-band toggle** on the scatter: overlay the **P10–P90** spread of load at each temperature
  (+ a P50 median line), the conditional distribution pooled over the shown points
  (`wxnorm.quantile_bands`, binned quantiles).
- **Full-year history backfilled.** Added the shoulder months (Mar–May, Sep–Nov) plus 2025-12 and
  2026 Jan–May — **30 month-panels, 8/8 zones each**. 2022–2025 are now continuous Jan/Mar–Dec, so the
  load-vs-temperature **U is continuous through the mild 55–70 °F middle** (was summer/winter-only with
  a gap); the scatter went from 648 → ~1,557 daily points.
### Notes & Caveats
- Figure 3 is **whole-ERCOT demand** (the Zone selector drives the scatter, not the growth curve).
- 2022 lacks Jan–Feb (Meteologica history starts ~2022-03); 2026 is Jan–May only (current year) — its
  W/N curve stops where its data ends.

## [0.25.0] - 2026-06-11
### Added
- **Per-zone split on the 📈 Load vs temperature dashboard.** A new **Zone** selector: *Whole ERCOT*
  (default), *All zones (overlay)*, or any of the **8 ERCOT weather zones**. For a zone, the scatter
  plots **that zone's demand vs its own ERA5 temperature** (more precise than system demand vs the
  system-mean temp); overlay draws all 8 zones with a fit each so you can compare temperature
  sensitivities at a glance. Per-zone is **demand-only** (net load can't be zoned — see rationale);
  "Colour by" is disabled in overlay (colour = zone).
- **Per-zone sensitivity map, side-by-side with the scatter (1×2).** The scatter (left) and a Texas
  choropleth coloured by each zone's **cooling sensitivity (GW/°F)** (right; toggle to heating
  sensitivity or mean demand) share the same year/resolution controls, with the sortable per-zone
  table (Mean GW · Cool GW/°F · Cool R² · Heat GW/°F · Heat R²) full-width below. Same map format as
  the Live monitor's demand-by-zone panel. The AC-driven Texas Triangle (Coast 0.35, North Central
  0.34, South Central 0.17) lights up; Far West/Panhandle stay flat. `build_demand_map` generalised
  (colorbar/format/unit/height params); `hist_panel` cache added so the 8-zone sweep reads each panel
  once.
- **Per-zone history now cached.** `historical.build_panel` additionally fetches the 8 zonal
  observed-demand series (Meteologica `PowerDemand/Observation/<zone>`, ids 1970–1977) and keeps
  per-zone ERA5 temperature, writing `demand_<zone>` + `temp_<zone>` columns. `ercot_zone_temperatures`
  added; `ercot_temperature` now derives the system mean from it. All 21 cached months rebuilt.
- `backfill_history` gained a **`--force`** flag to rebuild already-cached months (needed after a
  schema change). `wxnorm.lt_scatter` gained a `temp_col` arg to drive the x-axis off any temp column.
### Design Rationale
- **Demand splits cleanly by zone; net load does not.** Meteologica publishes observed demand for all
  8 weather zones, but wind is published by *geo-region* (Coastal, West-North) and solar is
  system-only — they don't map to the demand zones, so `demand − wind − solar` can't be formed per
  zone. Net load therefore stays a whole-ERCOT quantity (same reason `zonal.py` is demand-only).
- **Pairing each zone's demand with its own temperature** surfaces real structure the system average
  hides: empirically North Central (DFW) ≈ **+0.33 GW/°F** and Coast (Houston) ≈ **+0.31** (AC-heavy,
  R²≈0.9), vs **Far West ≈ −0.05 GW/°F, R²≈0.0** — flat, because it's oil-&-gas industrial base load
  that ignores weather. That spread is *where* a heat event becomes load.
- Backward-compatible: zone columns may be NaN and don't gate rows, so the whole-ERCOT panel (and
  Dashboard 2) are unchanged. Validation: zone demands sum to within ~0.1% of system demand.
### Notes & Caveats
- Overlay's "Overall R²" is shown as "—" (n/a — zones have different baselines; per-zone R² is in the
  legend). Coarse resolutions still yield few points per zone.
- Adding zones required a one-time Meteologica re-backfill (`--force`); future new months pick the
  columns up automatically.

## [0.24.0] - 2026-06-11
### Added
- **New dashboard: 📈 Load vs temperature** (third tab). The raw historical scatter of ERCOT load
  (y) vs load-weighted temperature (x, °F), one point per chosen time bucket, with a regression
  curve. Controls: **Resolution** (Hourly / Daily / Weekly / Monthly / Yearly — each point is the
  bucket mean), **Load** (Demand / Net load), **Colour by** (Year / Month / None), **Fit**
  (Quadratic / Linear / None), and a **Years** multiselect. Per-year fit curves when colouring by
  year; legend shows each curve's R²; metric cards show point count, temp/load ranges, overall R².
- New pure helpers in `src/wxnorm.py`: `lt_scatter(df, value, resolution)` (aggregate the hourly
  panel to (temp, value) points at a time resolution) and `poly_fit(x, y, degree)` (least-squares
  polynomial regression curve + R², empty dict on degenerate input). WebGL (`Scattergl`) auto-used
  above 4 000 points so the hourly view stays smooth.
### Design Rationale
- **Quadratic by default, not linear.** Load↔temperature is a U / "hockey stick" — heating drives
  load up at the cold end, cooling at the hot end, with a trough near the 65 °F balance point. A
  straight line can only follow one arm; empirically daily quad **R²≈0.94** vs linear **0.44**.
  Linear is kept as a toggle so the failure is visible. (This is also *why* the 🔋 history dashboard
  splits into CDD/HDD arms to linearise each side.)
- **Colour-by-year is the headline mode** — it overlays a curve per year so the *upward drift* (same
  temperature → more load each year) is read directly off the chart, complementing the quantified
  `a + b·DD` drift on the 🔋 dashboard. Pooled-all-years R² (~0.83) is intentionally lower than
  per-year (~0.94) because pooling mixes in that drift.
- Reuses the existing cached history pipeline (`era_panel` / `available_months`) — no new fetch path.
### Notes & Caveats
- Cached coverage is **summer (Jun–Aug) + winter (Dec–Feb), 2022–2025**, so the scatter shows the
  cooling and heating arms with a sparse gap through the mild ~65 °F middle (no spring/fall cached).
- **Net load** flattens the curve (wind + solar decouple it from temperature) — expected, and the
  point of offering it alongside demand.
- Coarse resolutions (Monthly/Yearly) yield few points; Yearly can be unfittable (≤ degree points →
  no curve, points still shown). Local-tz bucketing can add a tiny adjacent-year edge bucket.

## [0.23.0] - 2026-06-11
### Added
- **Forecast-days × zone demand table** under the zonal demand map: every forecast day (rows, ~14)
  × each ERCOT weather zone (columns, biggest-first) + a system TOTAL, showing the daily peak/mean
  demand (GW) with a lightweight white→red heatmap (no matplotlib dependency). The whole forecast
  horizon at once, complementing the single-day map.
### Fixed
- **Open-Meteo archive connection errors on the lookback views.** `weather._fetch_points` now
  retries on transient `ConnectionError`/`Timeout` (the archive API occasionally drops the
  connection → the raw `HTTPSConnectionPool … Max retries` dump). Tuned to **2 attempts × 35 s
  timeout** (worst case ≈ 70 s, not the original 3×90 s that *hung* the page on a blip). The lookback
  path also shows a friendly "archive slow/unreachable — try again" message instead of the traceback.
  Archive fetches are inherently ~5–6 s (vs the faster forecast API); StormVista forecast views never
  touch Open-Meteo, so they stay fast.
### Removed
- **Figure ② (forecast model comparison) removed** from the Live monitor (the 9-NWP-model spaghetti).
### Changed
- **Figure ① is now hybrid:** StormVista drives the *forecast* views (High/Low/Anomaly-vs-normal, with
  a forecast-day slider); **Open-Meteo's ERA5 archive** still drives the *lookback* views (vs
  Yesterday … **vs 1 year ago**, vs 10-yr normal) — kept because the year-over-year comparison is
  valuable and needs historical data StormVista's forward feed doesn't have.
- **Temperature map (Figure ①) now uses StormVista, not Open-Meteo.** The per-county choropleth
  colours each county by its **nearest StormVista station** (grid-corrected city-extraction), with a
  **forecast-day slider** and a *View* selector (High °, Low °, or Anomaly vs the 30-yr ERA5 normal).
  Works for any US market (counties → nearest of ~660 N-America stations; 69 cover ERCOT's 254
  counties). This drops the rate-limited Open-Meteo per-county grid that kept 429-ing. New client
  helpers: `stormvista.station_meta` / `station_normals` / `region_daily_temps`. Anomalies are
  clipped to ±35 °F to drop a few stations with bad/missing normals. (Open-Meteo still powers the
  9-model **Figure ②** comparison.)

## [0.22.0] - 2026-06-11
### Fixed
- **Per-zone demand map slider now does something.** The old "Over next (days)" slider used
  `max()`/`mean()` over a *growing* window, so Peak (the default) never changed (the week's peak is
  in day 1). Replaced with a **"Forecast day ahead" slider** that maps *that day's* peak/mean demand
  by zone — so it evolves day to day as the weather changes (caption shows the date).
- **Meteologica `GetContents` throttle hardened.** Added a 5-minute process-level cache of the
  contents catalog in `meteologica_client.list_datasets`, so a cold render's multiple consumers
  (net-load registry + zonal demand) share one fetch instead of each hitting the throttle.
### Changed
- **Weather-normalized history dashboard is now demand-focused** — removed the gas-burn metric and
  its heat-rate / must-run-baseload sliders from Dashboard 2 (metric is now Demand or Net load).
  Burn stays on the 📡 Live monitor; the history view focuses on the structural temperature → demand
  relationship without the burn assumptions.
### Docs
- **`docs/figures.md` — per-figure guide.** Every figure on both dashboards (in screen order) with
  three lines each: **Shows · Implies · Read → action** (the trade signal). Covers the temperature
  map, zonal demand map, model comparison, degree days + weather→load + hourly sub-figures, net
  load, gas burn, demand decomposition, and the Dashboard-2 correlation/drift, validation backtest,
  diurnal, and difference figures. Linked from `usage.md`.

## [0.21.0] - 2026-06-10
### Features
- **Panel ③ now pairs weather *and* load.** Added a **look-ahead window** slider, and a
  **Weather → load** view: forecast degree days (StormVista) vs forecast **demand** and **net
  load** (Meteologica), each with its OLS slope (GW per degree day).
- **Weather-normalized history (Dashboard 2) rebuilt around degree days.** Figure ① is now
  *weather-normalized demand* — net-load/burn vs **CDD/HDD** (toggle) by year, replacing the raw
  °F axis; the hourly diurnal (battery fingerprint) and difference figures stay.
- Removed the US gas-weighted-HDD companion (not needed); `wxnorm.to_daily` + `response_by_cdd`
  added.
- **Absolute weather from StormVista.** `stormvista.ercot_temperature()` returns the load-weighted
  absolute ERCOT daily high/low/avg °F (from `city-extraction` station temps × the ERCOT load
  weights) — validated to reproduce StormVista's own `pw_cdd` exactly. The weather-vs-load plot
  gains an **x-axis toggle: degree days ⇄ absolute high °F** (`GW per CDD` or `GW per °F`).
  `_fetch`/`latest_run` generalized to accept any CSV header (not just `Date,…`).
- **Sub-daily / hourly visualization.** `stormvista.ercot_temperature_hourly()` pulls each ERCOT
  station's per-station `city-extraction/individual/<stn>_raw.csv` (3-hourly `tmp2m`) and
  load-weights them → an intraday ERCOT temperature series. The Live monitor adds a **sub-daily
  temperature (3 h) + hourly net-load** dual-axis chart (shows the diurnal cycle daily degree days
  flatten away). The weather-vs-load section gets its **own look-ahead slider** windowing both the
  scatter and the hourly chart.
### Design Rationale
- **Key finding the weather-vs-load view surfaced:** weather drives **demand** cleanly (~+0.87
  GW/CDD) but **net load is decoupled** (~−0.32 GW/CDD) because wind+solar swing it — so a hot day
  only means high burn if it's *also* calm/cloudy. The gap between the demand and net-load clouds
  *is* renewable generation. This makes "watch CDD **and** the renewable forecast" an explicit read.
- Degree days are trader-native units and a cleaner x-axis than raw °F for the structural
  (solar/battery) drift; daily aggregation (`to_daily`) is required since degree days are daily.
- **Correlation + drift view (Dashboard 2 ①).** Added **Demand (GW)** as a metric, an **OLS fit
  `a + b·DD` per period** (dots = binned means, dotted = fit), and a **coefficient table**:
  `r` (correlation), `baseline a`, `slope b` (units/°day), and value `@DD=15`. Empirically: demand
  vs CDD `r ≈ 0.90–0.95`; demand at a *fixed* CDD=15 climbs **53.5 → 61.8 GW (2022→2025, +15%)** —
  the structural growth signal, isolated from weather. (`a`/`b` trade off year-to-year; `@DD=15`
  is the clean monotonic read.)
- **Per-zone demand map (spatial).** New `src/zonal.py` pulls Meteologica demand forecasts for the
  8 ERCOT weather zones; a Texas **choropleth** (`build_demand_map`) fills each zone block by its
  forecast demand (GW), labelled per zone, with a Peak/Mean + horizon toggle. The weather-driven
  demand *value* per zone, spatially — sits next to the temperature map. (Verified: zone demand sums
  to ~81 GW ≈ ERCOT peak; North Central 24.8, Coast 21.5 lead.) `stormvista.station_temps_subdaily`
  generalized for arbitrary stations.
- **Validation backtest (Dashboard 2)** with a **resolution toggle (Season/Month/Week/Daily)**,
  scored **out-of-sample by leave-one-out CV** (`wxnorm.cv_resolution`) so a finer resolution can't
  win by memorising. Underpowered windows (too little weather spread to fit a slope) are flagged +
  skipped. Honest result: in-sample MAE *falls* with finer resolution (1.25→1.15→0.81 GW) but **OOS
  doesn't improve** (1.28→1.24→1.29) and the **overfit gap explodes at Week (+0.49 GW)**; **Daily
  can't fit at all** (1 point/window). Sweet spot = month/season. Also showed the drift via stale-fit
  bias (2022→2025 −9.1 GW) and a vendor cross-check (Meteologica 81 GW vs EIA-930 actual ~78 GW).
- **Weekday/weekend split + train/test sizes (Dashboard 2).** A toggle adds a calendar term
  (`demand = a + b·DD + c·weekend`), validated **out-of-sample** so it only counts if it helps:
  it does — weekends draw **~−1.7 GW** at the same weather and the term cuts OOS MAE ~0.2 GW (~16%)
  at every resolution (overfit gap stays small → real, not memorised). The panel now also states the
  **train/test split** explicitly (leave-one-out: ~N−1 days train, 1 day test, total test-days,
  #parameters). `wxnorm.cv_resolution` rewritten on numpy least-squares to support the extra feature.

## [0.20.0] - 2026-06-10
### Features
- **StormVista WDD wired in (was planned → built).** `src/stormvista.py` is now a real client,
  not a scaffold: it pulls ERCOT population-weighted (load-proxy) **degree days** from
  `https://api.stormvistawxmodels.com/model-data/[model]/[YYYYMMDD]/[cycle]z/wdd/…csv?apikey=`.
  Products: deterministic CDD/HDD forecast, **GEFS ensemble members** (→ p10/50/90), 7-day
  **actuals**, and the **10/30-yr climatology normal** (the anomaly reference). `ercot_snapshot()`
  assembles all four; run files cached under `data/stormvista/`. Smoke-tested live (gfs
  20260610 12z, 31 members, anomaly +2.4 CDD vs normal).
### Design Rationale
- **`model-data/` base prefix** was the long-missing piece — the subscriber docs only show the
  relative path tail; the prefix was recovered from the Swagger UI operation IDs at `www/api`.
- Auth is `?apikey=` query-param only (header / path-segment both rejected). Site user/password
  are needed solely to read the gated docs, not for the data API.
- Population-weighted (`pw`) is StormVista's ISO weighting and the standard electricity-load
  proxy; degree days stay a pure weather measure, so forecast−actual isolates structural drift.
### Dashboard
- **Panel ③ "ERCOT degree days"** added to the Live monitor (alongside Open-Meteo): keeps **both
  CDD and HDD** (metrics for each; a toggle charts the in-season one), with the GEFS p10–p90 band,
  30-yr normal, recent actuals, and an **anomaly vs normal** read. A companion expander shows the
  **US national gas-weighted HDD** (`gw_hdd`) for the Henry-Hub gas-demand view.
- Concepts documented: [concepts.md](docs/concepts.md) §5 (CDD/HDD vs WDD weighting — orthogonal
  choices; when to use which) and §6 (weather-normalized load; how degree days isolate solar vs
  the battery/evening-peak effect). `data-sources.md` §8 flipped planned → built.
### Notes & Caveats
- Degree-day CSVs are `Date,<region…>`; climo is keyed by `MM-DD`. ERCOT sub-regions
  (`ercotnorth/south/west`) also available.
- Code-reviewed (code-reviewer agent; `codex` unavailable for adversarial-review) and hardened:
  validate-before-cache (no poisoned error bodies), per-kind load isolation, empty-Series guards,
  ensemble resolves its own run, static climo now disk-cached, index-aligned anomaly sums.
- **Daily-run resilience:** the ensemble band now records its own run (`WddBundle.members_run`) and
  the panel flags when it lags the deterministic forecast (the ~1.5 h gap after each cycle);
  `prune_cache(max_age_days=14)` bounds `data/stormvista/` growth (called once/day from the app).

## [0.19.0] - 2026-06-10
### Docs & data
- **StormVista (SVWX) added as a planned data source.** `docs/data-sources.md` §8 documents the
  vendor (paid API `/api`; ECMWF/EPS, GFS/GEFS, GEM, ICON, ensembles, gas-weighted degree days,
  load/wind), its access/rate-limit model, and a **mapped use table** — with priority order:
  (1) gas-weighted degree days, (2) ECMWF EPS spike-probability, (3) archived runs → run-over-run
  revision. `src/stormvista.py` is a credentials-aware scaffold (graceful until subscribed);
  `.env.example` gains `STORMVISTA_API_KEY`/`USER`/`PASSWORD` slots. Trading-strategies table updated.
- Also documented **EIA-930** (§7) as the wired-in actual-gas-generation source.
- **End-to-end workflow** now spans all four sources: `docs/usage.md` gains a 5-layer
  DATA → PROCESSING → DASHBOARDS → SIGNAL → TRADE pipeline, and `docs/workflow.html` (the HTML
  one-pager) weaves StormVista through its Sources, Processing, run-over-run, and footer blocks —
  flagging where the paid feed upgrades step 1 (gas-wtd degree days), step 5 (ECMWF EPS spike-prob),
  and the run-over-run revision (archived runs).

## [0.18.0] - 2026-06-10
### Features
- **Actual gas burn wired in (EIA-930).** With an `EIA_API_KEY` in `.env`, the gas-burn chart now
  overlays **measured ERCOT gas burn** (green) for the recent past alongside the implied forecast —
  `gas burn = actual NG generation (MW) × heat rate`, **no baseload assumption**. New "Latest actual
  burn" metric. EIA-930 lag is only ~13 h; falls back to forecast-only if the key is missing.
  (`src/eia.py` validated live: ERCOT NG gen 28–43 GW, correct evening-peak diurnal.)

## [0.17.0] - 2026-06-10
### Docs & data
- **`docs/trading-strategies.md`** — documents all 8 signals (implied gas burn, run-over-run
  revision, ensemble tail/spike-probability, spark spread, weather-normalized drift,
  forecast-vs-actual, cross-zone congestion, renewable penetration), each with **input → output,
  data source, and build status**, plus a data-source comparison table.
- **Plan updated** to v1.0 in `ercot-dashboard-plan.md` (top status block): two-dashboard
  architecture, current data sources, and the highest-value roadmap; the v0.3 temperature-difference
  framing is marked superseded.
- **EIA-930 client** (`src/eia.py`) for *actual* hourly ERCOT gas generation (free key) — grounds the
  gas burn and removes the must-run-baseload assumption; `.env.example` gains `EIA_API_KEY` and
  optional StormVista slots. (StormVista is subscription-only; no credentials available.)

## [0.16.0] - 2026-06-10
### Features
- **Two dashboards** via a top toggle: **📡 Live monitor** (temperature map, forecast comparison,
  net load, gas burn, decomposition) and **🔋 Weather-normalized history** (the flexible 2022–2025
  comparison). The history dashboard is self-contained — its own heat-rate & must-run-baseload
  sliders — and the monitor is skipped (`st.stop()`) when it's active.
- **Winter coverage** backfilled — Dec/Jan/Feb for 2022-23 … 2024-25 (e.g. Dec 2022 down to 14°F,
  Storm Elliott). Summer **and** winter now selectable, so the heating-season gas-burn story is
  reachable. `available_months()` auto-populates the selectors from cached panels.
- Heat-rate & baseload sliders carry **help text** explaining the burn calc; the docs already
  define `implied gas burn` and `temperature normalization` (`docs/concepts.md`).

## [0.15.0] - 2026-06-10
### Features
- **Flexible weather-normalized comparison** — pick any **years** (2022–2025) or any **months**
  to compare, not just 2022 vs 2025. A "Compare across Years / Months" toggle drives multiselects
  populated from whatever panels are cached (`src/historical.py: available_months`).
- **Temperature view** — a per-period **box plot** of ERCOT temperature (median/quartiles/mean),
  so you see *the weather each period actually had* (what normalization removes) alongside the
  weather-normalized burn/net-load curves. Each period gets its own colour across all figures.
- Backfilled **2022–2025 summer** (Jun–Aug) panels; `③ difference` shows when exactly 2 periods.

### Findings
- At the **same ~98°F**, weather-normalized implied burn: **8.47 (2022) → 8.92 (2023) → 8.44 (2024)
  → 6.99 (2025) Bcf/d** — while the summers ran different temperatures (median 85.5→82.6°F). The
  drop only emerges *after* removing weather; 2023's bump fits demand growth before solar/batteries
  scaled.

## [0.14.0] - 2026-06-10
### Features
- **Weather-normalized gas burn — battery-era comparison (2022 vs 2025)**. New section under
  the gas-burn one, plus the data pipeline behind it:
  - `src/historical.py` — pulls ERCOT demand/wind/PV **observations** (Meteologica
    `historical_data`, now unzipped in the client) + ERA5 temperature, cleans to an hourly
    panel, computes net load, caches to Parquet (`data/history/`).
  - `src/backfill_history.py` — caches 2022 & 2025 summer (Jun–Aug) panels.
  - `src/wxnorm.py` — `response_by_temp` (weather-response curve) and `diurnal` (hour-of-day
    shape within a temperature bin).
  - App (3 clearer figures): **① Same temperature → less burn** (response curve with the
    structural gap shaded green), **② Daily shape** at a chosen temperature with **labeled
    solar (midday) / battery (evening) regions**, and **③ the weather-normalized difference**
    (2025 − 2022 per hour as a bar, evening bars purple = battery). The control is renamed
    **"Hold temperature at (°F)"** with help text explaining the same-weather comparison.
- `MeteologicaClient.get_historical_data` now **unzips** the ZIP-of-JSON response and merges
  the vintages.

### Findings (live data)
- At the **same temperature** (90–95°F, daily avg): net load 51.8→43.3 GW, implied burn
  **7.61→6.13 Bcf/d (−1.5)** — mostly **solar** (peak 9.7→29.3 GW).
- At the **evening peak** (95–100°F, sun down): burn 9.19→8.99 Bcf/d (−0.21) — smaller, because
  solar doesn't help the evening peak; that residual is the **battery** lever, which grows as
  BESS scales. The diurnal figure makes the level (solar) vs shape (battery) split visible.

### Notes & Caveats
- Meteologica ERCOT history reaches ~2022 (battery obs ~2025), so "before batteries" = 2022
  (~1–2 GW BESS), not a pristine zero. Confounded by solar + demand growth; summer-only, 3
  months/year so far (extend via `backfill_history`).

## [0.13.0] - 2026-06-10
### Features
- **Implied power-sector gas burn (ERCOT)** — the weather → power → NG bridge, under the
  net-load section. `implied burn = max(net load − must-run baseload, 0) × heat rate → Bcf/d`
  (`src/netload.py: implied_gas_burn_bcfd`). Shows: configurable **heat rate** (6–12
  MMBtu/MWh) + **must-run baseload** (0–20 GW) sliders, the burn line with the **ECMWF-ENS
  p10–p90 band**, and headline metrics — current burn, peak burn, **max net-load up-ramp**
  (GW/hr), and peak p50 burn. Verified on live data (current ≈5.1, peak ≈8.5 Bcf/d).

### Design Rationale
- Highest-value combined signal for *both* desks: net load is the core power fundamental,
  and the residual thermal it implies is mostly gas — so this one number drives power and
  NG together. Built entirely from data already pulled (no new API calls).
- It is a **signal**, not an EIA balance: heat rate + baseload are user assumptions, and
  Meteologica gives no thermal mix / outages. The *changes* (vs ensemble, later vs prior
  run) are robust even where the absolute level is approximate.

### Docs
- New **`docs/concepts.md`** glossary: net load, heat rate, implied gas burn, **spark spread**,
  **run-over-run revision** (+ the three "differences" table), the **NWP forecast methods and
  what they're based on**, the **benefits of ensemble forecasting**, and **temperature
  normalization** (climate normal / anomaly). Linked from the app footnote and README.

### Next (flagged, not yet built)
- Spark spread (needs a Meteologica DAM-price pull), run-over-run burn revision (prior-run
  pull via `/updates`), and anomaly vs Normal/last-year.

## [0.12.0] - 2026-06-09
### Features (Figure ② forecast comparison)
- **Adjustable look-ahead window** — slider 1–16 days (Open-Meteo's max horizon).
- **Historical-forecast mode** — pick a past week and view what each model *actually
  forecast* then, via Open-Meteo's **Historical Forecast API** (archived past runs, back to
  2022 — distinct from ERA5 reanalysis). `src/weather.py: historical_forecast_by_zone`.
- **All methods in the table with per-method on/off** — a multiselect of the 9 NWP models,
  default = all; toggling filters both the chart and the table.
- **Highest = red, lowest = blue** highlighting per day column in the Model×day table
  (`_hilo_col`), so the warmest/coolest method stands out at a glance.
- **Independent Market selector** on Figure ② — the trader can compare forecasts for any
  market (PJM/CAISO/SPP/MISO/USA), separate from the anomaly map's market.
- Model×day table now shows **2 decimal places**; titled **"Forecast model (scope)"**, placed
  **directly below the chart** (full width) for clarity. Default look-ahead is **3 days**.
- **Per-method ± column** (`± zones`) — for the Market-mean scope, each model's market mean
  is averaged over the market's zone cities, so its ± is the **std across those zones**
  (spatial spread), averaged over the displayed days.

## [0.11.0] - 2026-06-09
### Features
- **Per-zone forecast comparison** — Figure ② gains a **Scope** selector: "Market mean"
  (default) or any individual zone. The model spaghetti chart, GFS ensemble band, and the
  Model×horizon table all switch to the selected zone (`src/weather.py: forecast_by_zone`
  returns per-zone + market-mean frames in one pair of API calls).

### Fixes
- Figure ② crashed with *"unsupported format string passed to NoneType.__format__"*: the
  `+7d` horizon read index 168 of a 168-long (0–167) series → `None`, then formatted with
  `"{:.0f}"`. Fixed by clamping the index to the last hour and adding `na_rep="—"` so any
  missing value (e.g. HRRR past 48 h) renders as "—" instead of erroring.

## [0.10.0] - 2026-06-09
### Features
- **Split the temperature section into two figures** (the forecast model belongs with the
  forecast, not the history):
  - **① Anomaly map** — market + view + unit only. "now" is a single canonical source
    (NOAA GFS Seamless); the reference is ERA5 (≥3-day / normal). No model picker.
  - **② Forecast model comparison** — for the selected market: all 9 NWP models' next-7-day
    market-mean forecast as a **spaghetti chart + a Model×horizon table** (now…+7d), with the
    **NOAA GFS ensemble p10–p90 band** (`multi_model_forecast`, `market_ensemble_band`).

### Design Rationale
- **Why the split:** the Open-Meteo forecast API only reaches ~92 days into the past
  (confirmed), so for "vs 1 week … 1 year / normal" the *reference* value is always **ERA5
  reanalysis** — the forecast-model dropdown only ever changed the "now" half, which was
  misleading. Model selection/comparison now lives entirely in Figure ②; Figure ① is a clean
  temperature-vs-the-past anomaly.

## [0.9.0] - 2026-06-09
### Features
- **Forecast-model selector** — 9 US-covering Open-Meteo NWP models choosable in-page
  (NOAA GFS Seamless / HRRR / GFS Global / NBM, ECMWF IFS, DWD ICON, Environment Canada
  GEM, JMA, Météo-France); threaded through every fetch + cache.
- **Forecast-side ensemble ±** (toggle): NOAA GFS ensemble (31 members) via Open-Meteo's
  ensemble API → per-county forecast spread (std across members), shown as a `fcst±`
  column. (`src/weather.py: points_ensemble_std`)
- **Local persistence** (`src/storage.py`): each per-county "now" pull is appended to
  Hive-partitioned Parquet under `data/weather/` (idempotent per hour), building a
  history that outlives Open-Meteo's recent-only window. `src/ingest_weather.py` runs it
  for all markets on a schedule (cron); the app also saves opportunistically on load.

### Notes & Caveats
- Open-Meteo forecast reaches ~16 days ahead and keeps only recent past; ERA5 archive
  goes back decades but lags ~5 days. Neither retains *historical forecasts* (vintages) —
  hence the local snapshot archive, which captures "what was forecast when".
- Ensemble pulls are heavier (31 members); capped at 120 points and behind a toggle.

## [0.8.0] - 2026-06-09
### Features
- **Climatological ± (multi-year ERA5)** — new temperature view **"vs 10-yr ERA5 normal"**.
  For each county it pulls ERA5 for *today's* calendar date & hour across the last 10
  years (`src/weather.py: points_climatology`), and shows the anomaly = now − 10-yr mean.
  In this view the table's **± becomes the inter-annual std** (genuine temporal
  uncertainty: "is today anomalous, or within normal year-to-year spread?").

### Design Rationale
- One ERA5 request per past year (a 2-day window), 120 sampled points, cached 6 h; years
  that fail (transient rate limit) are skipped rather than aborting the whole view.
- Forecast "now" = NWP model output interpolated to the point — **not** a model we run.
  The model is now **pinned to `gfs_seamless`** (NOAA GFS Seamless: HRRR ~3 km ≤48 h +
  GFS ~13 km) so the source is explicit/reproducible instead of auto `best_match`
  (confirmed identical for US points).
- Historical = ECMWF **ERA5 reanalysis** via Open-Meteo's archive API (hourly, ~31 km,
  ~5-day lag).
- **New: `docs/data-sources.md`** documents every figure's exact model/dataset, the
  Open-Meteo access/cost/limits, and why it's used; the app shows a sources footnote.

## [0.7.0] - 2026-06-09
### Features
- **All markets get the per-county view** — PJM, CAISO, SPP, MISO and a new **USA national
  overview**. Large markets (PJM 985, SPP 1014, MISO 1364, USA 3109 counties) cap the
  Open-Meteo fetch at 200 sampled points and fill every county from its nearest sample
  (`src/geo.py: subsample, assign_nearest_index`) — keeps them inside the quota.
- **Vivid colours + readable text**: saturated diverging map scale (robust 92nd-pct range,
  no washed white county lines), and table cells now use a saturated background with a
  **contrasting text colour** (dark-on-light / white-on-dark) so values are never white-on-white.
- **Variance ±** column in the per-zone table: the spatial spread (std of county values
  within each zone).

### Notes & Caveats
- The ± is *spatial* (across a zone's counties). ERA5 archive (historical) is a single
  deterministic reanalysis value — it carries no built-in per-point variance. Temporal /
  forecast uncertainty would need the Open-Meteo ensemble API (forecast side) or a
  multi-year climatological std (archive side); not yet wired.
- USA / large-market choropleths render 1k–3k county polygons — correct but heavier.

## [0.6.0] - 2026-06-09
### Features
- **True per-county temperature field.** The choropleth now colours every county by
  its own temperature (254 distinct values for ERCOT, not 8), via Open-Meteo at each
  county centroid (`src/weather.py: points_now / points_at_lookback`).
- **Zone outlines on top.** Counties are dissolved into weather-zone polygons with
  **shapely** (`src/geo.py: zone_boundaries`) and drawn as outlines + labels over the
  field, so the named blocks (Far West, West, South, South Central, Coast…) stay legible.
- Per-zone table is now the **county mean** per zone (still colour-coded + signed).

### Design Rationale
- **Quota-aware fetching:** only two instants are needed, so every Open-Meteo request
  is capped to a 2–3 day window (recent = forecast, older = 2-day ERA5 archive) — cost
  is independent of how far back the lookback is. "Now" is fetched once per market+unit
  and shared across all lookback views; "past" is cached per view. 429s are caught and
  shown as a friendly "wait ~1 min" notice.
- shapely dissolve runs in ~0.05 s and is cached per market.

### Notes & Caveats
- Open-Meteo's free tier weights by locations × time-range; a per-county pull is ~254
  weighted units, so rapidly browsing many market×view combinations can still hit the
  per-minute limit (handled gracefully; successful views cache for 30 min).
- New dependency: `shapely>=2.0` (in `requirements-app.txt`).

## [0.5.0] - 2026-06-09
### Features
- **Filled zone choropleth** replaces the point map (`src/geo.py`): every county in
  the selected market is filled by its nearest weather zone, so the named blocks
  (ERCOT Far West, West, South, South Central, Coast, East, North, North Central…)
  render as coloured regions with visible county + state borders. Uses the standard
  US-counties GeoJSON (cached to `data/us_counties_fips.json`).
- **Colour-coded per-zone table** beside the map: diverging red(warmer)/blue(cooler)
  background on the Δ column, with explicit **+/−** signs on every difference.
- 4 geo tests (41 total).

### Design Rationale
- Counties are assigned to zones by nearest representative city (no shapely/geopandas
  dependency) — the plan's documented fallback to true zone polygons.
- Choropleth `zmid=0` with a symmetric range keeps 0 at the white midpoint so warmer
  vs cooler reads instantly.

## [0.4.0] - 2026-06-09
### Features
- **Local Streamlit dashboard** (`app/app.py`, run `streamlit run app/app.py`): no
  sidebar (all controls in-page), built on Plotly.
- **Temperature map (hero)** with a **market selector** (ERCOT, PJM, CAISO, SPP, MISO)
  and a **difference view**: current temperature, or the change vs yesterday / 2 days /
  1 week / 2 weeks / 1 month / 1 quarter / 1 year ago. Diverging colour (red = warmer
  now, blue = cooler). US state borders + neighbouring states shown for context.
  Source: **Open-Meteo** (`src/weather.py`) — recent history via the forecast API's
  `past_days`, one-year lookback via the ERA5 archive API.
- **Net-load section** (ERCOT): Meteologica central + ECMWF-ENS fan + demand
  decomposition, with graceful messaging while the API cools down.
- **API login rate-limit fix:** the client now caches its token to
  `data/.mtoken.json` and **reuses it across processes/reruns** instead of logging in
  every time (the login endpoint rate-limits "DoLogin"). Verified: a fresh client makes
  authenticated calls with no re-login. 3 new tests (37 total).

### Design Rationale
- **Temperature is not in Meteologica** (power-market feed only), so the map is sourced
  from Open-Meteo — flagged in the UI. One representative city per market zone.
- UTC alignment for "same moment N days ago" so the difference is clean across markets.
- Map uses `scope="usa"` at `resolution=110` (state borders, lighter render).

### Notes & Caveats
- Net-load is ERCOT-only for now; the market selector drives the temperature map.
- Temperature map uses point markers per zone (choropleth needs zone polygons — later).

## [0.3.0] - 2026-06-09
### Features
- **Endpoint reference** documented in `docs/meteologica-api.md` (auth, all endpoints,
  params, `/data` response shape, content taxonomy, account-specific notes, resolved
  net-load content IDs).
- **Net-load algorithm working locally** (`net load = demand − wind − pv`):
  - `src/registry.py` — resolves ERCOT-Total net-load content IDs by exact catalog path.
  - `src/parsing.py` — `/data` rows → tidy UTC-indexed, float-valued DataFrame (handles
    local-CPT + UTC-offset time and deterministic vs ensemble value columns).
  - `src/netload.py` — `central_net_load` (Meteologica, ~14.5 d horizon) and
    `ensemble_net_load` (ECMWF-ENS member-wise → p10/p50/p90 fan, ~5–6 d). `python -m
    src.netload` runs it live and writes `data/netload_demo.parquet`/`.csv`.
  - 34 tests (parsing + net-load math, network mocked).

### Design Rationale
- **Kept ECMWF-ENS:** it is served through the existing Meteologica account (no separate
  ECMWF account needed) and — unlike GEFS — exists for demand, wind, AND PV, enabling a
  correct member-wise net-load fan. GEFS retained as a secondary ensemble.
- **No temperature in the catalog** → Phase-1 is a net-load/generation monitor, not a
  temperature monitor (see [phase1-direction] memory).

## [0.2.0] - 2026-06-09
### Features
- Discovered the real API surface from the login-gated docs and the OpenAPI spec
  (`GET /api/v1/oas`, OpenAPI 3.1). Implemented all data endpoints in
  `src/meteologica_client.py`: `list_datasets()` (`/api/v1/contents`, ~2748 items),
  `search_contents()`, `get_content_data()`, `get_historical_data()`,
  `get_updates()`, `get_latest()`, and `keepalive()`.
- Added `python -m src.meteologica_client --probe` (live login + ERCOT catalog).
- Test suite grown to 24 (added token-injection, retry-on-invalid-token, and
  data-endpoint URL/param construction).

### Design Rationale
- **Auth correction:** the API authenticates via a `?token=<JWT>` **query parameter**
  on every request, not an `Authorization: Bearer` header (the v0.1.0 assumption was
  wrong). Confirmed because real operations returned
  `parameter "token" in query ... is required`, and an invalid token returns
  `400 {"message": "Error. Invalid token"}`. The client now injects `token` into the
  query and retries once (re-login) when a call reports an invalid token.
- The token is kept out of exception text (the URL in errors carries no query string).

### Notes & Caveats
- Forecast `data` rows arrive as a list of dicts with **string** values (e.g. ensemble
  members `ENS00..`, `Average`, `Bottom`); numeric conversion belongs in the (not yet
  built) ingest layer, not the client.

## [0.1.0] - 2026-06-09
### Features
- Implemented the Meteologica API connection (`src/meteologica_client.py`):
  real `login()` against `POST /api/v1/login` (JSON `{user, password}` → JWT +
  `expiration_date`), bearer-token session, token-expiry handling with a 60s
  skew guard, single retry-on-401 re-authentication, and an API-message-aware
  error path. Added `python -m src.meteologica_client --login` live auth check.
- Renamed the project virtual environment from `venv/` to **`dash_env/`** and
  updated `setup.sh`, `README.md`, `.gitignore`, and `src/probe_api.py`. `setup.sh`
  now prefers `python3.13` and echoes the interpreter version so everyone lands
  on the same environment.
- Added a mocked-network test suite (`tests/`, 19 tests) covering expiry parsing,
  `token_valid` boundaries, login success/error paths, and the 401-retry flow.

### Design Rationale
- The login page authenticates via a JS `fetch('/api/v1/login')` token call, not a
  plain form post; the form fields `user[token]`/`user[token_expiration]` are only
  populated *after* the token call. The client mirrors that real flow.
- Data-operation paths (`list_datasets`, `get_timeseries`) remain `NotImplementedError`
  on purpose: the API gateway returns `{"message":"no matching operation was found"}`
  for guessed paths, so the exact operation names must come from the login-gated docs.
- `load_dotenv` was moved out of import time into `Settings.from_env()` to keep module
  imports side-effect free (hermetic tests).

### Notes & Caveats
- **Security:** the real Meteologica password lives in `.env` (gitignored, and this is
  not a git repo, so it has not leaked via git). Treat the on-disk plaintext as
  sensitive; rotate if it may have been exposed.
- The token is short-lived (~hours); the client re-logs in automatically when the
  cached token is near expiry or a call returns 401.
