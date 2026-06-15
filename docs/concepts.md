# Concepts & Glossary

Definitions for the trading and forecasting ideas the dashboard visualises. For the exact
data sources / model ids / provenance, see [data-sources.md](data-sources.md).

---

## 1. Trading concepts

### Net load
`net load = demand − wind − solar`. The load that must be met by **dispatchable**
(mostly thermal) generation. It is the core power-market fundamental: it sets the marginal
unit, the price, and how tight the system is. Everything else keys off it.

### Heat rate
How much gas it takes to make electricity: **MMBtu of gas per MWh of power**. Lower = more
efficient. Efficient combined-cycle (CCGT) ≈ 6.5–7.5; an older peaker ≈ 9–11. It is the
conversion factor between the gas market and the power market.

### Implied (power-sector) gas burn
`implied burn = max(net load − must-run baseload, 0) × heat rate → Bcf/d`.
The residual that net load leaves after renewables is met mostly by **gas** in ERCOT, so net
load is a proxy for gas demand from power. This is the **weather → power → NG bridge** — one
number that serves both desks. It is a *signal* (heat rate + baseload are assumptions, and
Meteologica gives no thermal mix/outages), not an EIA-grade balance.
- High net load / low wind → more burn → bullish NG **and** power.
- Windy / sunny → renewables displace gas → less burn → bearish both.

### Spark spread
The gross margin a gas-fired plant earns:
```
spark spread ($/MWh) = power price ($/MWh) − heat rate (MMBtu/MWh) × gas price ($/MMBtu)
```
Example: power $45, gas $3.00, heat rate 7.5 → 45 − 22.5 = **$22.5/MWh**.
- High spark → gas plants are economic and run hard (more burn); negative → they back down.
- **Market-implied heat rate** = power price ÷ gas price. If it exceeds a plant's physical
  heat rate, that plant is in the money — comparing the two tells you which units set price.
- The spread is itself a trade (long power / short gas, or vice versa) and is *the* link
  between the power and NG desks.
- Relatives: **dark spread** = coal version; **clean spark** subtracts a carbon price
  (irrelevant in ERCOT — no carbon price).

### Run-over-run revision
Forecasts are re-issued several times a day as new model cycles arrive (00Z/06Z/12Z/18Z…).
Each run is a fresh forecast for the same future hours. A revision is **how the forecast for
a given target time changed from the previous run to the latest**:
```
revision = forecast_latest_run(valid_time) − forecast_prior_run(valid_time)
```
Example: last night's run had Thursday 6pm net load at 72 GW; this morning's run has 75 GW
→ **+3 GW** (≈ +0.5 Bcf/d more burn). The forecast just got hotter/tighter.
- **The level is largely already priced; the *change* is the new information.** Seeing the
  revision before the market fully reprices is the edge. This is why **forecast vintages**
  (`issue_time` + `valid_time`) matter — Meteologica exposes them via `/updates` + `update_id`.

### The three "differences" (don't confuse them)
| Signal | Compares | Answers |
|--------|----------|---------|
| **Run-over-run revision** | latest run vs *prior run*, same target time | "did our *information* just change?" (news/trading) |
| **Anomaly vs normal** | now vs climatology | "is the weather *extreme*?" (demand stress) |
| **Forecast vs actual** | forecast vs what *happened* | "how *skillful* was the model?" |

---

## 2. Forecast methods — what they are based on

Every forecast on the dashboard comes from **Numerical Weather Prediction (NWP)**: a
physics model that solves the governing equations of the atmosphere — conservation of mass,
momentum and energy plus thermodynamics (the "primitive equations") — on a 3-D grid. It is
**initialised** from an *analysis* of the current state (built by **data assimilation** of
observations: satellites, radiosondes, surface stations, aircraft, buoys) and integrated
forward in time. Open-Meteo does not run any model itself — it serves the agencies' output,
interpolated to a point.

Models differ by **grid resolution**, **physics parameterisations** (clouds, convection,
boundary layer), **data-assimilation scheme**, **domain** (global vs regional), and
**update cadence**:

| Model | Agency | Type / resolution | Notes |
|-------|--------|-------------------|-------|
| **GFS** | NOAA/NCEP | Global ~13 km, 4×/day, to 16 d | US workhorse global model |
| **HRRR** | NOAA | CONUS, **~3 km convection-allowing**, hourly, ≤48 h | best short-range / storms |
| **NBM** | NOAA | Statistical **blend** of many models | calibrated guidance |
| **ECMWF IFS** | ECMWF (Europe) | Global ~9–25 km, 2×/day, to ~15 d | generally the most skilful global model |
| **ICON** | DWD (Germany) | Global/regional ~13 km | |
| **GEM** | Environment Canada | Global Environmental Multiscale | |
| **ARPEGE/AROME** | Météo-France | Global / regional | |
| **JMA GSM** | Japan Met. Agency | Global | |
| **ERA5** (history) | ECMWF / Copernicus | **Reanalysis** ~31 km hourly | model re-run over the past with data assimilation = "best estimate of the past" |

Because each model makes different choices, they **disagree** — often by several °F. That
disagreement is itself a (model-) uncertainty signal, which is why the dashboard shows all
of them together.

---

## 3. Ensemble forecasting — what it is and why it helps

A single ("deterministic") forecast gives one number and hides its own uncertainty. An
**ensemble** runs the model **many times** (members) with slightly perturbed initial
conditions and/or physics, producing a *spread* of plausible outcomes — e.g. NOAA GEFS (31
members), ECMWF ENS (51), DWD ICON (40), Canadian GEM (21).

**Benefits:**
1. **Quantifies uncertainty.** The spread *is* the forecast confidence — tight = confident,
   wide = uncertain. A deterministic run can't tell you this.
2. **Probabilistic forecasts.** You get P10/P50/P90 and "P(net load > threshold)", which feed
   risk limits and option-style payoffs directly.
3. **Captures the tail.** Scarcity/price-spike payoffs are convex — the money is in the
   extreme (P90) member, and only an ensemble surfaces it.
4. **Better central estimate.** The ensemble mean often beats any single member (random
   errors cancel), especially at longer lead times.
5. **Verifiable calibration.** You can check it's honest — do ~10% of observations really
   fall below P10?

On the dashboard: ensemble members give the **net-load / gas-burn p10–p90 band** and let us
talk about *probability* of a tight system, not just a point estimate.

---

## 4. Temperature normalization (climate normal & anomaly)

"Normalising" temperature means expressing it **relative to a climatological normal**
instead of as an absolute value.

- A **climate normal** is the long-term average of the variable over a reference period
  (classically a 30-year window, e.g. NOAA 1991–2020; the dashboard uses a **10-year ERA5
  mean** for *today's* calendar date and hour).
- The **anomaly** = actual (or forecast) temperature − normal. "**+5 °F above normal**" is far
  more informative than "88 °F", because it tells you how *unusual* the weather is — which is
  what drives a demand surprise — independent of season or location.
- **Why normalise:** 88 °F means very different things in January vs July, or Houston vs
  Minneapolis. Subtracting the local, seasonal normal makes anomalies **comparable across
  time and place** and isolates the departure-from-typical *signal* that moves load and price.
- The **± (inter-annual std)** is the normal year-to-year spread of that date, so you can tell
  whether today's anomaly is genuinely extreme (e.g. > 2σ) or within normal variability.

On the dashboard: the **"vs 10-yr ERA5 normal"** view shows `anomaly = now − 10-yr mean`,
coloured red (warmer) / blue (cooler), with `±` = the inter-annual standard deviation.

---

## 5. Degree days (CDD/HDD) and weighted degree days (WDD)

A **degree day** collapses a day's temperature into one *demand-relevant* number, measured from
a **65 °F** comfort base:

```
CDD = max(T̄ − 65, 0)   cooling degree days  → AC / summer power demand
HDD = max(65 − T̄, 0)   heating degree days  → heating (gas + electric) / winter demand
```

(`T̄` = the day's mean temperature.) A 78 °F day = 13 CDD, 0 HDD; a 40 °F day = 0 CDD, 25 HDD.
Degree days are the standard energy-demand "language": demand scales roughly linearly with them.

### WDD vs CDD/HDD — two orthogonal choices, not alternatives

**WDD = *Weighted* Degree Days.** The "W" is the **aggregation method** (how you combine many
locations into one regional number), **not** a third type of degree day. So you always pick
**one weighting × one type**:

| The "W" — weighting (HOW, across space) | The type (WHICH) |
|---|---|
| `pw` population/**load**-weighted → electricity-demand proxy | **CDD** cooling |
| `gw` **gas**-weighted → direct gas-heating-demand proxy | **HDD** heating |
| `ew` energy-weighted | |

e.g. `pw_cdd` = population-weighted cooling degree days (what the ERCOT panel uses); `gw_hdd` =
gas-weighted heating degree days (the Henry-Hub gas-demand driver).

### When to use which

- **Weighting:** at a *market* level (ERCOT, an ISO, the US) essentially **always use a weighted
  (WDD) series** — an unweighted/single-station degree day is only for a *specific city*. Choose
  the weighting by which demand you're proxying: `pw`→power, `gw`→direct gas.
- **Type:** by **season / channel** — **CDD** in summer (cooling → electric → power burn),
  **HDD** in winter (heating → *both* direct gas and electric). Keep both year-round; the
  in-season one dominates.
- **Don't blend them.** A combined `TDD = CDD + HDD` is fine only as a coarse headline; never as
  a single burn regressor — cooling and heating have different coefficients and serve different
  fuels (cooling is all-electric; heating is electric **and** direct gas).

| Goal | Series |
|---|---|
| ERCOT summer power burn | `pw_cdd` (ERCOT) |
| ERCOT winter power burn | `pw_hdd` (ERCOT) |
| US residential/commercial gas demand (Henry Hub) | `gw_hdd` (national / EIA region) |

> **Weighting ≠ normalization.** Weighting is a *spatial average* (collapse the map into one
> number); normalization (§6) is a *temporal* operation that removes the weather entirely.
> Degree days do the weighting; they are still a *pure weather* signal.

On the dashboard: the **③ ERCOT degree days** panel shows load-weighted `pw_cdd`/`pw_hdd`
(forecast + GEFS p10–p90 band + 30-yr normal + actuals), and a companion expander shows the
US national **gas-weighted HDD** (`gw_hdd`) for the Henry-Hub gas-demand view. Source detail:
StormVista WDD ([data-sources.md](data-sources.md) §8).

---

## 6. Weather-normalized load (and isolating the battery effect)

The correct term is **weather-normalized load** (or weather-normalized burn/demand) — **not**
"load-normalized weather". The grammar settles it:

> **"X-normalized Y"** = *"Y, with X's effect held constant / removed."*
> So **weather-normalized load** = LOAD with the WEATHER removed. (You normalize the *load*; the
> weather is what you hold constant. "Load-normalized weather" is meaningless — load doesn't
> drive weather.)

**Why:** raw load/burn in 2022 vs 2025 mixes two things — *was the weather different* or *did the
grid change structurally* (solar, batteries, demand growth)? Normalization separates them by
putting every period on **equal weather footing**.

**Method (what the 🔋 Weather-normalized history dashboard does):**
1. **Within each period**, fit the relationship `burn = f(temperature)` (or `f(CDD)`) — that
   period's *response curve*.
2. **Across periods**, read every curve at the **same reference** (a fixed temperature, or fixed
   CDD). The shared reference is what makes them comparable — e.g. *"at 98 °F (or CDD = 20),
   2022 burned X, 2025 burns X − 1.5 Bcf/d."* That residual Δ is **pure structure**.

The reference can be a **fixed temperature** (what we use) or a **normal-weather year**
(climatology); either way it must be the *same* for every period. Normalizing "within one year
alone" gives nothing to compare against.

### How this isolates batteries (vs solar)

Degree days are a **daily total** → they capture the *energy* of demand-weather but **not the
intraday shape**. That matters because solar and batteries act on different parts of the day:

| Structural driver | Fingerprint | How to see it |
|---|---|---|
| **Solar** | less gas in the **midday** / lower daily total | **burn-per-degree-day** (β) falling year-over-year |
| **Batteries** | **evening-peak** shaved, troughs filled, ~same daily total | **diurnal shape at a held temperature** (evening peak lower) |

So: `burn ≈ α + β·CDD`, and **β (burn per cooling degree day) falls** as the grid de-carbonizes —
that's mostly **solar** + efficiency + demand growth. The **battery** signal is specifically the
**evening-peak reduction at a held degree-day/temperature**, which a daily total smooths over —
you need the diurnal (hour-of-day) view to see it. The degree-day series is the clean weather
axis for both; pairing it with *actual* burn/net-load is what exposes the structural drift.

### The battery era — when does it start contaminating the load?

The historical window (2022 →) spans ERCOT's battery boom, so **which years you compare matters**:

| Period | ERCOT BESS | weather→load is… |
|---|---|---|
| **2022 & earlier** | ~1–1.5 GW (negligible) | **clean baseline** — load ≈ weather + growth, no battery |
| **2023** | ~3.5–5 GW | transition |
| **2024 →** | 7 GW → **16 GW (May-2026)** | materially battery-influenced |

**Battery charging is load** (it *adds* to `demand`, mostly midday/overnight); **discharging is supply**
(it *lowers net load* in the evening, not demand). So a weather-normalized **demand** comparison across
2022 → 2026 mixes three things — real growth, **+ battery charging load**, and (in net load / the
diurnal shape) **− evening discharge**. Use **2022 as the ~battery-free reference**; from 2024 on, read
the drift as growth *plus* battery operation, not pure weather. Full timeline + data treatment:
[data-sources.md §9](data-sources.md).

(See the three "differences" in §1 — *anomaly vs normal* is "is the weather extreme?",
whereas *weather-normalization* is "with the weather removed, how has the grid changed?")

---

## 7. Using the weather→demand fit for prediction

§6 fits `demand = a + b·CDD` per period to *diagnose* structural drift. The **same fitted line
is a forecasting model** — this section is how to turn the 🔋 history dashboard's two figures
(**① correlation & drift** and **🎯 validation backtest**) into a forward demand prediction.

### What each figure gives you

- **① correlation & drift → the model's parameters.** Its coefficient table prints, per period,
  **a** (baseline GW, weather-independent), **b** (GW per cooling degree-day), **r** (how tightly
  weather explains demand), and **@DD=15** (demand at fixed weather). `a` and `b` *are* the
  predictive equation — nothing more is needed to forecast.
- **🎯 validation → whether to trust it, and how.** It re-fits that equation **out-of-sample**
  (leave-one-out CV) and reports **OOS MAE** (your error bar), **OOS bias** (systematic
  over/under-prediction), and which **resolution** generalizes. It is the QA stamp on ①.

### The prediction recipe

```
predicted_demand (GW) = a + b · CDD_forecast   (+ c · weekend, if 🎯 says it earns its place)
```

1. Read **a, b** off the **latest** row of ①'s coefficient table (e.g. a ≈ 48 GW,
   b ≈ 0.9 GW/CDD → @DD=15 ≈ 61.5 — illustrative; use the live table).
2. Take a **forecast CDD** straight from the **③ ERCOT degree days** panel — it already gives
   tomorrow's load-weighted CDD plus a GEFS p10–p90 band.
3. Plug in: CDD = 15 → demand ≈ 48 + 0.9·15 = **61.5 GW**.
4. Attach the error bar from 🎯: OOS MAE ≈ 1 GW ⇒ **61.5 ± ~1 GW (±1.5 %)**. Run the CDD band's
   p10/p90 through the same line to get a **demand fan**, not just a point.

Then chain it forward exactly like the Live monitor: demand → (− wind − solar) → **net load**
(§1) → × heat rate → **gas burn** (§1) → price.

### Three rules the validation enforces

1. **Use the most recent period's coefficients — never a pooled all-years fit.** Because of
   drift (@DD=15 climbed 53.5 → 61.8 GW, 2022→25), an old fit under-predicts today. The
   **negative OOS bias** in the backtest *is* that staleness: "a stale model reads low, so anchor
   on the latest slope/baseline."
2. **Fit the slope on coarse data (season/month).** In-sample error keeps falling as the
   resolution gets finer (looks better!) but OOS doesn't — the overfit gap explodes at **Week**,
   and **Daily can't fit** at all. Predict with season/month `b`; don't re-estimate it weekly.
3. **Only add the weekend term if it survives OOS** (it does, ~−1.7 GW). The calendar term earns
   its place out-of-sample or it's dropped — discipline that keeps the forecast honest rather
   than curve-fit.

### What you can do with it

| Use | How |
|---|---|
| **Forward demand forecast** | Latest `a,b` + ③'s forecast CDD → demand (+ OOS-MAE band). |
| **Cross-check Meteologica** | Your `a+b·CDD` demand vs the vendor's zone-summed demand. A gap = a trade signal **or** a data flag. |
| **Scenario / heatwave stress** | Push CDD to e.g. 25 → predicted demand → net load → burn. See how tight it gets *before* it happens. |
| **Position sizing** | OOS MAE is the error bar on all of the above. Size to it; widen it when forced onto a coarse/old fit. |

### The honest limit — it predicts *demand*, not *net load*

`a + b·CDD` predicts **total demand** (weather + the period's structural level). It does **not**
predict **net load**, because net load is *decoupled* from weather — wind and solar swing it
independently (this is exactly what the **③·a Weather → load** scatter shows: demand has a clean
positive slope, net load is near-flat).

> CDD → **demand** (this model, r ≈ 0.9, tight). Then **demand − wind − solar = net load** needs
> a *separate* renewable forecast layered on. You cannot shortcut straight from CDD to net load
> or burn.

That is why the model is trustworthy for the *demand* leg, and why renewables remain a separate
input in the chain.

### Status on the dashboard

Today the 🔋 history dashboard **shows and validates** the fit (diagnostics) but does not yet
**apply** the validated historical `a,b` to the forward StormVista CDD to print an own-model
demand forecast next to Meteologica's. That apply-step is the missing link that converts ① + 🎯
from analysis into a live prediction + vendor cross-check.

---

## 8. Feb 2021 Winter Storm Uri — counterfactual demand reconstruction

> **Full standalone write-up:** [`docs/winter-storm-uri-2021.md`](winter-storm-uri-2021.md) — the
> canonical, detailed documentation (model, design matrix, validation, caveats, trader playbook,
> code pointers). This section is a short conceptual summary.

**Where:** an expander **directly under the Per-station fits**, in the **📈 Load vs temperature**
dashboard. **Code:** `src/uri2021.py` · **Data:** EIA-930 demand + ERA5 temperature (see
`docs/data-sources.md §9`).

**The problem.** During Uri, ERCOT shed **~20 GW** of load (rolling blackouts), so metered demand on
Feb 15–18 is **curtailed served-load, not true demand** — on the coldest day (Feb 16, ≈12.7 °F)
observed demand *fell below* milder days, which is impossible without load shed. True demand has to be
**reconstructed**.

**The model.** A weather→demand OLS regression fit on **un-curtailed** winter hours only:

```
demand_t  =  a_year  +  b·HDD_t  +  c·HDD_t²  +  d·weekend_t  +  Σ_h (hour-of-day_h)  +  ε_t
```

`HDD = max(65 − T, 0)`; **`HDD²`** captures the steepening at extreme cold; **per-year intercepts**
absorb load growth; **weekend + hour-of-day** dummies strip the daily/weekly shape. Fit on Dec–Feb of
four winters (2019→2023), **excluding the blackout window** so curtailed hours never pollute the fit.

**The reconstruction.** Push the storm's **actual** temperatures through the fitted model to get
**latent demand** (what would have been drawn with no curtailment); the gap `latent − observed` during
the blackouts is the **unserved load**. A second pass at *normal* February weather gives the
**no-storm** baseline. Honesty: a leverage-based ±band widens where the deepest cold extrapolates.
Headlines — R² ≈ 0.86; daily-mean Feb-16 latent ≈ 78 GW (robust); hourly-peak ≈ 89 GW (upper bound);
max unserved ≈ 40+ GW; no-storm peak ≈ 49 GW.

See [`docs/winter-storm-uri-2021.md`](winter-storm-uri-2021.md) for the design-matrix detail,
validation, caveats, and the trader analog playbook.
