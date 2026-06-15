# Dashboard Flow & How to Use It

What the dashboard is, how data moves through it, and how a trader/analyst uses each piece.
Concepts: [concepts.md](concepts.md) · signals: [trading-strategies.md](trading-strategies.md) ·
data: [data-sources.md](data-sources.md) · **per-figure guide (what each implies + how to read
it): [figures.md](figures.md)**.

---

## The flow (data → signal)

```
SOURCES                          PROCESSING                         OUTPUT (2 dashboards)
Meteologica  ─ wind/solar/      ─ net load = demand−wind−solar  ─┐
   [built]      demand/price/     (central + ECMWF-ENS members)   │
               battery, by zone ─ implied burn = (net load −      │   📡 Live monitor
Open-Meteo   ─ temp forecast      baseload)×heat rate → Bcf/d      ├─► (forward-looking)
   [built]      (GFS/HRRR…) +    ─ actual burn = EIA gas×HR (no    │
               ERA5 archive        baseload assumption)            │   🔋 Weather-normalized
EIA-930      ─ ACTUAL hourly     ─ temp anomaly vs ERA5 normal;   ─┘   history (structural)
   [built]      gas generation     forecast-model & ensemble spread
StormVista   ─ gas-wtd degree   ─ weather-normalization (hold T)
  [planned]     days, ECMWF EPS, ─ run-over-run revision  [planned]
                archived runs    ─ spark spread           [planned]
```

Run it: `source dash_env/bin/activate && streamlit run app/app.py`. A **Dashboard** toggle at the
top switches the two views.

---

## The whole workflow — end to end (5 layers)

```
① DATA (ingest)            ② PROCESSING                 ③ DASHBOARDS        ④ SIGNAL → DECISION       ⑤ TRADE
Meteologica  [built] ─┐    net load            [built]  📡 Live monitor    DAILY (intraday):         NG: long/short
Open-Meteo   [built] ─┼──► implied burn        [built] ─► (forward)    ──► 1 anomaly (stress)    ──► burn vs forward
EIA-930      [built] ─┤    actual burn (EIA)   [built]                     2 model spread (conf.)    Power: long / vol
StormVista [planned] ─┘    anomaly vs ERA5     [built]  🔋 Wx-normalized    3 net load / burn         on spike risk (P90)
                          ensemble p10/50/90  [built] ─► history       ──► 4 forecast vs actual   Rel-value: spark
                          weather-norm        [built]    (structural)      5 spike risk (P90)        spread [planned]
                          run-over-run [planned]                        WEEKLY (positioning):     Positioning: seasonal
                          spark spread [planned]                           structural drift         burn-per-degree
                          gas-wtd HDD/CDD [planned, StormVista]
```

- **Daily loop** = steps 1–5 on the Live monitor (next section), driving NG & power direction + spike risk.
- **Weekly loop** = the Weather-normalized history → recalibrate seasonal expectations as the grid drifts.
- **Highest-alpha gap** = *run-over-run revision* (the trigger) — needs vintaged runs (Meteologica `/updates`
  or StormVista archives). **StormVista** also unlocks gas-weighted degree days (NG-demand language) and the
  ECMWF EPS ensemble (better spike-probability).

---

## 📡 Dashboard 1 — Live monitor (what's coming, next 1–16 days)

Read top → bottom; each panel is one link in *weather → power → gas → price*.

1. **① Temperature anomaly map** — per-county, any US ISO (ERCOT/PJM/CAISO/SPP/MISO/USA). Pick a
   view: current, or change vs yesterday … 1 year ago, or **vs the 10-yr ERA5 normal**.
   → *Is a heat/cold event building, and how anomalous/where?* (red = warmer, blue = cooler.)
2. **② Forecast model comparison** — all 9 NWP models + the GFS ensemble band, per market, with a
   look-ahead slider (1–16 d) or a historical-forecast date. The Model×day table flags the
   warmest (🔴) / coolest (🔵) method.
   → *How confident is the temperature forecast?* Tight cluster = high confidence; wide spread or a
   model jumping around = low — size positions accordingly.
3. **ERCOT net load forecast** (demand − wind − solar) with the ECMWF-ENS p10–p90 fan.
   → *The core power fundamental* — sets the marginal unit, price, and system tightness.
4. **Implied power-sector gas burn (Bcf/d)** — forecast (brown) + **actual EIA-930 (green)** +
   ensemble band + max ramp. Adjust heat rate / baseload.
   → *Power-sector gas demand.* Compare forecast to actual (calibration) and to the NG forward.
5. **Demand decomposition** — net load + wind + solar = demand (the stack).

## 🔋 Dashboard 2 — Weather-normalized history (structural, positioning)

Pick **years or months** to compare (2022–2025, summer + winter). It shows:
- **Temperature box** — the weather each period actually had (what normalization removes).
- **① Weather response** — burn/net-load vs temperature; *same temperature → the gap is structural*.
- **② Daily shape** at a held temperature — midday dip = solar; lower evening peak = batteries.
- **③ Difference** (when 2 periods) — where burn changed, hour by hour.
→ *How is the grid structurally changing?* e.g. ~1.5 Bcf/d less burn at 98°F, 2022→2025.

---

## Daily workflow — step by step (each tied to a built panel + its data)

Run the **📡 Live monitor**, market = ERCOT, top to bottom. `[built]` = on the dashboard today.

**Step 1 — Is a weather event building? (demand stress)**
- **Panel:** ① Temperature anomaly map `[built]`. Set *Temperature view = "vs 10-yr ERA5 normal"*.
- **Data:** Open-Meteo — *now* = NOAA **GFS Seamless** (HRRR+GFS); *normal* = **ERA5** 10-yr mean for
  today's date/hour; per **Texas county** (254), aggregated to the 8 ERCOT weather zones.
- **Check:** large per-county anomaly, esp. in the load-heavy zones — **Coast (Houston)**,
  **North Central (DFW)**, **South Central (Austin/SA)**. The per-zone table gives the ± spread.
- **Signal → action:** summer **+ anomaly** (heat) in those zones ⇒ AC demand surge ⇒ flag for burn;
  winter **− anomaly** (cold) ⇒ heating + electric-heat surge (and gas freeze-off risk).

**Step 2 — How confident is the forecast?**
- **Panel:** ② Forecast model comparison `[built]`. Scope = Market mean; look at the spaghetti chart,
  the **Model×day table** (🔴 hottest / 🔵 coolest method), and the **GFS ensemble p10–p90 band**.
- **Data:** Open-Meteo — **9 NWP models** (`gfs_seamless, gfs_hrrr, gfs_global, ncep_nbm_conus,
  ecmwf_ifs025, icon_seamless, gem_seamless, jma_seamless, meteofrance_seamless`) + **GFS ensemble**
  (`gfs025`, 31 members). Look-ahead 1–16 d; or *Historical forecast* mode to see how prior runs did.
- **Check:** the "inter-model spread now→+7d" caption.
- **Signal → action:** spread ≲ 2–3°F ⇒ high conviction, size up. Spread ≳ 5°F or a model flip-flopping
  ⇒ low conviction, hedge or wait.

**Step 3 — How much load must gas/thermal serve?**
- **Panel:** ERCOT net load forecast `[built]` — net load + ECMWF-ENS p10–p90 fan; metric cards (peak
  net load + time, peak renewables).
- **Data:** Meteologica ERCOT — **PowerDemand** (central `1943`, ECMWF-ENS `1957`), **Wind** (`1877` /
  `1910`), **PV** (`1840` / `1856`); `net load = demand − wind − solar`.
- **Check:** peak net load and the **evening ramp** (when solar falls off); band width = uncertainty.
- **Signal → action:** high peak net load + steep evening ramp ⇒ tight system ⇒ ancillary/peak-price risk.

**Step 4 — Power-sector gas demand, forecast vs actual.**
- **Panel:** Implied gas burn `[built]` — **brown** = implied forecast burn, **green** = actual EIA-930
  burn (recent), ECMWF-ENS band, "Latest actual burn" + "Max up-ramp" metrics.
- **Data:** forecast = (net load − baseload) × heat rate → Bcf/d (Meteologica). Actual =
  **EIA-930** `fuel-type-data`, respondent `ERCO`, fuel `NG` × heat rate (no baseload assumption, ~13 h lag).
- **Check:** forecast peak burn vs the **NG forward / consensus power-burn**; is **green vs brown**
  biased over the last week?
- **Signal → action:** forecast burn **> market** ⇒ long NG **and** power; **< market** ⇒ short.
  Green persistently above brown ⇒ your proxy is low (raise baseload/heat-rate or trust EIA).

**Step 5 — Spike / tail risk.**
- **Panel:** the net-load fan (step 3) + gas-burn band (step 4) `[built]`.
- **Data:** ECMWF-ENS members (member-wise net load → p10/p50/p90).
- **Check:** how high/wide is **P90** relative to p50.
- **Signal → action:** high, wide P90 ⇒ price-spike risk ⇒ long power / long volatility (convex payoff).

**Weekly / seasonal (positioning):** 🔋 *Weather-normalized history* `[built]` — confirm burn-per-degree
keeps falling (solar+batteries), so don't carry a structurally-too-long NG bias for the same weather.

### Not yet built (so don't expect them on the screen)
- **Run-over-run revision** (the highest-alpha signal — trade the *change* between model runs).
- **Spark spread** (closes the loop to the price you trade — needs a gas-price input).
- **Forecast-vs-actual skill score**, full **EIA fuel mix** (real baseload), EIA history to 2018.
See [trading-strategies.md](trading-strategies.md) for each one's input/output/data/status.

---

## One-line cheat-sheet

> *Map = is it hot/anomalous? · Models = how sure? · Net load/burn = how much gas demand? ·
> Actual vs forecast = is the model right? · Ensemble = spike risk? · History = is the grid drifting?*
