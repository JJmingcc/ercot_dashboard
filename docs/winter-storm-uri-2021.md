# Feb 2021 Winter Storm Uri — counterfactual demand reconstruction

> **Standalone case-study documentation.** This is the canonical write-up for the 2021 Uri panel.
> A short glossary pointer also lives in [`concepts.md` §8](concepts.md); the figure-reading guide is
> in [`figures.md`](figures.md); data provenance is in [`data-sources.md` §9](data-sources.md).
>
> **Where in the app:** an expander **directly under the Per-station fits**, in the
> **📈 Load vs temperature** dashboard.
> **Code:** [`src/uri2021.py`](../src/uri2021.py) (`build_cache` → `analyze` → `temp_curve`); rendered by
> `render_uri_panel()` / `uri_bundle()` in `app/app.py`.
> **Data:** **EIA-930** ERCOT demand (`region-data`, type `D`, respondent `ERCO`) + **ERA5** temperature
> (Open-Meteo archive). Meteologica has no pre-2022 history, so this is a dedicated EIA + ERA5 path.

---

## TL;DR

Observed ERCOT demand during the Feb 15–18, 2021 rolling blackouts is **censored data** — it is the
*curtailed served load*, not the demand customers wanted. We fit a weather→demand model on **un-curtailed**
winter hours only, then evaluate it at the storm's **actual** extreme cold to recover the **latent
demand** (what would have been drawn with no curtailment). The gap `latent − observed` during the
blackouts is the **unserved load**. A second pass at *normal* February weather gives the **no-storm**
baseline. Headlines: model **R² ≈ 0.86**; daily-mean Feb-16 latent **≈ 78 GW** (robust); hourly-peak
latent **≈ 89 GW** (short extrapolation, upper bound); **max unserved ≈ 40+ GW**; no-storm peak **≈ 49 GW**.

---

## 1. The problem — the meter lies during curtailment

During Uri, ERCOT ordered rolling blackouts and shed **~20 GW** of firm load for several days. So the
metered demand on **Feb 15–18 is curtailed served-load, not true demand.** The tell is a physical
impossibility:

| Day | ERCOT daily-mean temp | Served demand |
|---|---|---|
| Feb 13 | ≈ 27 °F | ≈ 59 GW |
| **Feb 16** | **≈ 12.7 °F** (coldest) | **≈ 45 GW** |

Demand **cannot fall as it gets colder** in a heating-driven grid — the ~14 GW *drop* into the coldest
day is load that was forcibly cut. You therefore **cannot** read true demand off the meter here; it has
to be **reconstructed** from the un-curtailed relationship.

---

## 2. The model

A weather→demand ordinary-least-squares regression (`np.linalg.lstsq`), fit on hourly data:

```
demand_t  =  a_year  +  b·HDD_t  +  c·HDD_t²  +  d·weekend_t  +  Σ_{h=1..23} (hour-of-day_h)  +  ε_t
```

with `HDD_t = max(65 − Temp_t, 0)` (heating degrees °F, base 65). The design matrix (`analyze.design` in
`src/uri2021.py`) is, per hour: `[1, HDD, HDD², weekend] + [year-dummies] + [hour-of-day dummies]`.

| Term | What it does | Why it matters |
|---|---|---|
| **`b·HDD`** | linear "colder ⇒ more heating load" slope | the first-order weather response |
| **`c·HDD²`** | lets the curve **steepen at extreme cold** | at single-digit °F, electric-resistance heat is maxed, equipment freezes, nothing turns off — a linear-only HDD term badly **under**-predicts the deep-cold tail |
| **`a_year`** | one intercept **per winter** (first winter = baseline) | **absorbs structural load growth** so several winters can be pooled without a warmer-but-newer year biasing the slope |
| **`weekend`** dummy | weekday vs weekend level shift | strips the weekly shape from the weather signal |
| **hour-of-day** dummies (hour 0 = baseline) | the diurnal profile | strips the daily shape so `b`, `c` are clean weather coefficients |

**Training window:** Dec–Feb of **four winters (2019→2023)** — `TRAIN_MONTHS` in the code: Dec/Jan/Feb of
2019-20, 2020-21, 2021-22, 2022-23.

---

## 3. The key step — training **excludes** the curtailed hours

```python
storm = (df.index >= CURTAIL_START) & (df.index < CURTAIL_END)   # Feb 15 → Feb 19, 2021
train = df[~storm]                                                # fit on UN-curtailed hours only
coef, *_ = np.linalg.lstsq(design(train.index, train["hdd"]), train["demand"], rcond=None)
```

Because the model **never sees the blackout hours**, it learns the *honest, un-curtailed* weather→demand
relationship from every other normal winter hour across four years. The curtailed prints can't pull the
fit down.

---

## 4. Reconstructing the latent (no-curtailment) load

Take the storm's **real observed temperatures** over the display window (Feb 8–21) and push them through
the fitted model:

```python
ev     = df[(df.index >= EVENT_START) & (df.index < EVENT_END)]   # Feb 8 → Feb 21, 2021
latent = design(ev.index, ev["hdd"]) @ coef                       # what the weather "called for"
```

`latent_t` answers: *given this much cold, and what un-curtailed grids of the last four winters actually
drew, how much load does this weather demand?* That is the **demand that would have been served if nothing
were cut**. The headline quantity is the gap during the blackouts:

```
unserved load_t  =  latent_t  −  observed_t        (over the curtailment window)
```

→ peak **latent ≈ 89 GW** vs **≈ 69 GW** served ⇒ up to **≈ 40+ GW** unserved at the worst hour.

### The no-storm counterfactual

Same machinery, different input: evaluate the model at **normal February weather** — the climatological
mean temperature by month-day-hour across the training winters — instead of the storm's cold:

```python
no_storm = design(ev.index, HDD(normal_feb_temp)) @ coef          # "if the cold snap never happened"
```

→ ordinary-February peak **≈ 49 GW**. The vertical distance between `no_storm` and `latent` is the pure
weather shock; the distance between `latent` and `observed` is the curtailment.

---

## 5. Honesty about uncertainty — a leverage prediction interval

The storm's coldest **hours** (≈ 4.9 °F) sit *below* the coldest **training** hour (≈ 13.6 °F), so the
peak latent is a **short extrapolation**. We surface that with the textbook prediction interval whose
**leverage** term grows for points far from the training cloud:

```
leverage_i = xᵢ (XᵀX)⁻¹ xᵢᵀ
se_pred_i  = resid_std · √(1 + leverage_i)
band_i     = 2 · se_pred_i            # ≈ 95%
```

The band **widens exactly where we extrapolate** (the coldest hours) and is tight in the well-sampled
middle — so the chart never hides where the estimate is softest.

---

## 6. Validation & what the numbers came out to

- Hourly fit **R² ≈ 0.86**; residual ≈ **±2–3 GW** in the normal range.
- **Daily-mean** latent, Feb 16 ≈ **78 GW** — the **robust, better-supported headline** (sits at the edge
  of the training cloud, ≈ interpolation).
- **Hourly-peak** latent ≈ **89 GW** — a short `HDD²`-driven extrapolation, *above* the published
  **~76–82 GW** Uri consensus; **treat as an upper bound** and lean on the daily-mean.
- **Max unserved load** ≈ **40+ GW** at the worst hour — consistent with the ~20 GW firm-load-shed
  headline **plus** demand that never showed up.
- **No-storm peak** ≈ **49 GW**.

---

## 7. Caveats

- It reconstructs **demand** — not net load, not scarcity price.
- The **`HDD²` tail** is the single biggest lever on the peak; quote the **daily-mean**, treat the hourly
  peak as an upper bound.
- **ERA5 zone-mean** temperature smooths local extremes — the real felt cold (and demand spikes) were
  sharper than the smoothed input.
- The deepest-cold latent is an extrapolation, not interpolation — the widening band is not decoration.
- Only **EIA-930** reaches back to 2021; this is a dedicated EIA + ERA5 path, separate from the main
  Meteologica pipeline used elsewhere in the app.

---

## 8. What a trader can do with it — analog playbook

Built to be **re-used the next time a polar outbreak is in the forecast**, not just to explain 2021:

1. **Analog demand off the curve.** The panel's second chart is a **demand↔temperature curve** from
   un-curtailed winters, extended into Uri-class cold. For the next forecast deep-freeze, read **expected
   ERCOT demand straight off this curve** at the forecast temperature — a fast, model-light peak estimate.
2. **Size scarcity to *latent*, not served, demand.** Reserve-shortfall / outage risk scales with the
   demand customers *want*, not the truncated served number. Latent is the correct denominator for "how
   short could the grid be."
3. **Unserved load × offer cap = scarcity rent.** Unserved-GW during the cut × the offer cap (ERCOT was
   **\$9,000/MWh** in 2021, **\$5,000** now) bounds the scarcity-rent / settlement exposure of a repeat —
   directly relevant to length, hedges, and ORDC/congestion bets.
4. **Stress-test positions.** Use latent demand (not the curtailed history) as the cold-case load input
   when stress-testing a gas/power book against a repeat — the meter understates the true stress.
5. **Real-time latent nowcast.** If curtailment recurs, the same fitted model turns live temperature into
   a real-time **latent-demand estimate** while the meter is held down by load shed — an edge over anyone
   reading the curtailed print.

> **One-line framing for the desk:** *Observed 2021 demand is censored data. This panel un-censors it —
> giving the true weather-driven demand, the unserved gap, and a reusable demand-vs-temperature curve to
> price the next Uri before it lands.*

---

## 9. Implementation pointers

| Piece | Location |
|---|---|
| Model fit + counterfactuals | `analyze(panel)` in `src/uri2021.py` |
| Cache build (EIA + ERA5 pull) | `build_cache()` → `data/uri2021/panel.parquet`; run `python -m src.uri2021` (one-time) |
| Analog demand–temp curve | `temp_curve(panel, degree=2)` in `src/uri2021.py` |
| Dashboard render | `render_uri_panel()` / `uri_bundle()` in `app/app.py` |
| Key constants | `TRAIN_MONTHS`, `EVENT_START/END` (Feb 8–21), `CURTAIL_START/END` (Feb 15–19), `BASE_F = 65` |
