# Trading Strategies / Signals

Every signal the dashboard produces (or is planned to), each with its **input → output**,
**where the data comes from**, and **build status**. Concepts (net load, heat rate, spark
spread, run-over-run, ensembles, temperature normalization) are defined in
[concepts.md](concepts.md); exact data provenance in [data-sources.md](data-sources.md).

**The core chain everything hangs off:**
`temperature → demand + wind + solar → net load → gas burn → NG & power price.`

| # | Signal | Output | Data | Status |
|---|--------|--------|------|--------|
| 1 | Implied gas burn (level) | Bcf/d | Meteologica fcst (+EIA actual) | **built** (proxy) |
| 2 | Run-over-run revision | Δ Bcf/d vs prior run | Meteologica `/updates` | planned |
| 3 | Ensemble tail / spike prob | P10–P90, P(tight) | Meteologica ECMWF-ENS | **partial** (band built) |
| 4 | Spark spread | $/MWh, implied heat rate | Meteologica price + gas price | planned |
| 5 | Weather-normalized drift | structural Δ burn at fixed T | Meteologica hist + ERA5 | **built** (own dashboard) |
| 6 | Forecast vs actual (skill) | bias / error | Meteologica obs / EIA | planned |
| 7 | Cross-zone / congestion | zonal spread | Meteologica wind by GeoRegion | planned |
| 8 | Renewable penetration | %, neg-price flag | Meteologica wind+solar+demand | planned |

---

## 1. Implied gas burn — fundamental level
- **Idea:** net load's residual after must-run is met mostly by gas → power-sector gas demand.
- **Input:** demand, wind, solar forecast (MW); heat rate + must-run baseload (assumptions) — *or*
  actual gas generation (EIA, removes the assumption).
- **Output:** implied gas burn time series (Bcf/d) + current / peak / max-ramp, with the ECMWF-ENS
  p10–p90 band.
- **Data:** Meteologica ERCOT `PowerDemand/Wind/PV Forecast` (central ids 1943/1877/1840; ENS
  1957/1910/1856). Actual: **EIA-930** `fuel-type-data` respondent `ERCO`, fuel `NG` (`src/eia.py`).
- **Status:** **built** (`src/netload.py: implied_gas_burn_bcfd`, Live-monitor dashboard). EIA-grounded
  version pending an `EIA_API_KEY`.
- **Trade:** compare to the NG forward / consensus power-burn. Forecast burn > market ⇒ long NG &
  power; windy/sunny ⇒ burn falls ⇒ bearish.

## 2. Run-over-run revision — the news/alpha signal
- **Idea:** the *level* is priced; the *change between consecutive model runs* is new information.
- **Input:** latest run + prior run of net load / burn for the same `valid_time`s.
- **Output:** revision per valid_time (Δ GW / Δ Bcf/d) + headline "this run added +X".
- **Data:** Meteologica `GET /contents/{id}/updates` (lists `update_id`s) + `/data?update_id=` to pull
  the prior run; diff vs the latest. Vintaged (`issue_time` + `valid_time`).
- **Status:** **planned** (endpoints confirmed, not yet built).
- **Trade:** upward revision ⇒ bullish, act before the market reprices. **Highest alpha-per-effort.**

## 3. Ensemble tail / spike probability
- **Idea:** scarcity pricing is convex — the upper tail of net load is where power (and peaker burn)
  pays. Quantify it, don't point-estimate it.
- **Input:** ECMWF-ENS members of demand/wind/solar → member-wise net load.
- **Output:** p10/p50/p90 band (built) and **P(net load > scarcity threshold)** (planned).
- **Data:** Meteologica ECMWF-ENS (1957/1910/1856); GEFS as backup.
- **Status:** **partial** — the p10–p90 net-load & gas-burn band is live; the exceedance-probability
  metric is not yet.
- **Trade:** wide/high P90 ⇒ long power / long volatility (spike optionality).

## 4. Spark spread — generation margin & cross-market relative value
- **Idea:** gas-plant margin = power price − heat rate × gas price; the market-implied heat rate tells
  you which units are economic.
- **Input:** DAM power price ($/MWh); gas price ($/MMBtu); heat rate.
- **Output:** spark spread ($/MWh) + implied heat rate (power÷gas).
- **Data:** Meteologica `PowerPrice` DAM by hub (1995 HB_HOUSTON, 1997 HB_NORTH, 1999 HB_SOUTH,
  2000 HB_WEST, 1998 HB_HUBAVG). Gas price = external (Henry Hub / Waha) or a user input.
- **Status:** **planned** (need a price pull + a gas-price input).
- **Trade:** high spark ⇒ gas economic, runs hard; trade power-vs-gas relative value.

## 5. Weather-normalized structural drift — seasonal positioning
- **Idea:** hold temperature constant across years to strip out weather; the residual is the
  structural change (solar + batteries + demand growth) — i.e. burn-per-degree is *falling*.
- **Input:** historical demand/wind/solar observations + ERA5 temperature; heat rate + baseload.
- **Output:** weather-response curve by period, diurnal shape, and the Δ at a fixed temperature
  (e.g. "−1.5 Bcf/d at 98°F, 2022→2025"); midday=solar, evening peak=battery.
- **Data:** Meteologica `historical_data` observations (1969/1929/1865, ~2022→now) + ERA5
  (Open-Meteo archive). EIA-930 would extend to ~2018.
- **Status:** **built** — its own *Weather-normalized history* dashboard (`src/historical.py`,
  `src/wxnorm.py`).
- **Trade:** lower your seasonal burn expectation for the same weather as the grid changes — keeps the
  fundamental model from being structurally too bullish NG.

## 6. Forecast vs actual — model skill / calibration
- **Idea:** measure how well the forecast burn/net-load matched reality → trust & sizing.
- **Input:** forecast (Meteologica) vs actual (Meteologica observations or EIA gas generation).
- **Output:** error, bias, skill score by lead time.
- **Data:** Meteologica observations (1969/1929/1865) and/or EIA-930.
- **Status:** **planned.**
- **Trade:** size positions by demonstrated skill; de-weight a model when its recent bias is large.

## 7. Cross-zone wind / congestion proxy
- **Idea:** wind sits in West/Panhandle, load in Houston/North — a zonal mismatch leads transmission
  congestion and hub basis.
- **Input:** wind by GeoRegion (Coastal/Panhandle/North/South/West) vs load zones.
- **Output:** zonal generation-vs-load spread → congestion/basis indicator.
- **Data:** Meteologica wind forecasts by GeoRegion (e.g. 5212 Coastal, 5213 Panhandle, …).
- **Status:** **planned.**
- **Trade:** hub basis (North / South / West / Houston) when the spatial spread is extreme.

## 8. Renewable penetration / curtailment / negative-price risk
- **Idea:** (wind + solar) / demand — high penetration ⇒ oversupply ⇒ curtailment / negative prices.
- **Input:** wind + solar + demand.
- **Output:** penetration %, a negative-price-risk flag.
- **Data:** Meteologica wind/solar/demand.
- **Status:** **planned.**
- **Trade:** negative-price risk ⇒ short off-peak power; high penetration days reduce gas burn.

---

## Data sources at a glance

| Source | Provides | Access / cost | Used for |
|--------|----------|---------------|----------|
| **Meteologica "API markets"** | ERCOT wind/solar/demand/price/battery forecasts + observations + ERA5 reanalysis, by zone, ensembles, vintaged | account (have); per-minute login throttle (token cached) | net load, burn, ensembles, history, revisions, price |
| **Open-Meteo** | temperature forecast (GFS/HRRR…), ERA5 archive, ensembles | free, no key, CC-BY (per-min quota) | temperature map, ERA5 normalization |
| **EIA-930** | actual hourly ERCOT generation by fuel (NG, coal, nuclear…), back to ~2018 | free **API key** (eia.gov/opendata) | actual gas burn, fuel mix, forecast-vs-actual |
| **StormVista (SVWX)** | ECMWF/EPS, GFS/GEFS, GEM, ICON + ensembles + **gas-weighted degree days** + load/wind | **paid subscription** (API `/api`) — *no credentials yet*; `src/stormvista.py` scaffold | (planned) degree-day demand panel, ECMWF EPS spike-prob, **archived runs → run-over-run revision** |
