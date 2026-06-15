# ERCOT Weather-Driven Fundamentals Monitor

**Type:** Internal / web-facing dashboard
**Goal:** Visualize weather changes and key regional shifts in the ERCOT market using Meteologica data, then progressively expand into full market fundamentals.
**Positioning:** Not a plain "weather dashboard" but a **weather-driven fundamentals monitor** — weather is the leading indicator; the real value is in how it propagates into net load and price.

---

## 1. Data source (Meteologica)

Meteologica provides a **weather-driven forecasting product suite**:

- NWP weather variables (temperature, wind speed, irradiance, etc.)
- Renewable generation forecasts (wind / solar)
- Load / demand forecasts
- Forecast horizon ~14 days, typically pushed as scheduled files (CSV/JSON via SFTP or API) per model run

Core job: surface the chain **weather → system state → market outcome**.

---

## 2. Architecture (macro pipeline)

```
Sources → Ingestion/Orchestration → Storage → Transform/Features → Serve API → Dashboard + Alerting
```

| Layer | Responsibility | Current choice | Future extension |
|-------|----------------|----------------|------------------|
| Ingestion | Pull Meteologica per NWP run, land raw | cron / Prefect + Python | Airflow / Dagster / Snowpipe |
| Storage | Store raw + curated, retain vintages | **Local Parquet + DuckDB** | **Snowflake** |
| Transform | Clean, derive features | **dbt-duckdb** | **dbt-snowflake** (models unchanged) |
| Serve | Expose query interface | FastAPI / direct DuckDB | FastAPI / Snowflake connection |
| Viz + Alerting | Visualization + threshold alerts | Grafana / Streamlit | React + Mapbox (productized) |

**Key design point — forecast vintage:** every record must carry `issue_time` (as-of) + `valid_time`. Weather forecasts get revised; without the vintage dimension you cannot backtest and you introduce lookahead bias.

---

## 3. Data storage strategy

> Core principle: **make the storage layer portable.** Run locally now, migrate smoothly to Snowflake later, **without rewriting transform logic.**

### 3.1 Canonical format: Parquet

All raw landing is written as **Parquet** (columnar, compressed, self-describing schema):

- Now: write to local filesystem, Hive-style partitioned by `issue_date`
- Later: the same Parquet serves directly as a Snowflake **external stage**, loaded via `COPY INTO` / Snowpipe — near-zero migration cost

```
data/
  raw/
    meteologica/
      weather/   issue_date=2026-06-09/ run=12/ *.parquet
      renewable/ issue_date=2026-06-09/ run=12/ *.parquet
      load/      issue_date=2026-06-09/ run=12/ *.parquet
```

### 3.2 Engine selection

**Current (local deployment): DuckDB**

- Columnar analytical engine, reads/writes Parquet natively, single-file, zero infra
- Full SQL, usable directly as a dbt target
- Runs the whole flow on one machine — ideal for the MVP

**Future extension: Snowflake**

Capabilities gained after migration:

- **Separation of storage and compute**, warehouses auto-scale on demand, suspend when idle to save cost
- **Time Travel**: data audit / rollback (complements explicit vintage modeling)
- **Zero-copy clone**: clone the entire database in seconds for backtests / dev with no extra storage
- **Streams + Tasks**: incremental pipelines, partially replacing external orchestration
- **Snowpipe**: continuous auto-load from an S3 stage
- **VARIANT** type: store Meteologica's raw JSON payloads directly, no upfront flattening of semi-structured data
- **Secure Data Sharing**: share data with traders / external teams later without copying
- **Marketplace**: subscribe to external weather / power / gas datasets directly

### 3.3 Portability mechanism: dbt

The key to migration is **decoupling the transform layer from the engine**:

- Use `dbt-duckdb` now, swap to `dbt-snowflake` later
- **dbt models (SQL) stay identical** — only the `profiles.yml` target changes
- The medallion layers (bronze / silver / gold) behave the same on both engines

### 3.4 Schema design (medallion + vintage)

**Bronze (raw, append-only):**

- `raw_meteologica_weather` — `issue_time, valid_time, location_id, variable, value, ingested_at, source_file`
- `raw_meteologica_renewable`
- `raw_meteologica_load`

**Silver (staged / cleaned):**

- `stg_weather` — unit normalization, timezone unified to Central Prevailing Time (watch DST), station → zone mapping, vintage keys retained

**Gold (marts):**

- `dim_location` — city / airport metadata (lat/lon, zone, population weight)
- `fct_weather_forecast` — `(issue_time, valid_time, location_id, variable) → value`
- `fct_forecast_delta` — run-over-run changes (the "key changes")
- `agg_metro_temp` — population-weighted temperature / CDD / HDD by metro
- (Phase 2+) `fct_load`, `fct_renewable_gen`, `fct_price`, `fct_congestion` …

**Partitioning / clustering:**

- DuckDB / Parquet: partition by `issue_date`
- Snowflake: set a cluster key on `valid_time` or `issue_time`; micro-partitions handle the rest

### 3.5 Migration path (local → Snowflake)

| Dimension | Now | Migration action |
|-----------|-----|------------------|
| Raw format | Local Parquet | Upload to S3 → create external stage (format unchanged) |
| Loading | DuckDB reads Parquet | `COPY INTO` / Snowpipe |
| Transform | dbt-duckdb | Switch profile to dbt-snowflake, models untouched |
| Orchestration | cron / Prefect | Prefect / Airflow or Snowflake Tasks |
| Credentials | Local `.env` / secrets | Secrets Manager / Snowflake integration |

### 3.6 Cost / ops notes

- Snowflake bills on **compute (warehouse seconds) + storage**; don't let the dashboard hit Snowflake compute on every refresh — put a layer of **materialized aggregates** or a serving cache (DuckDB / Redis) in front
- Set **auto-suspend / auto-resume**, start with a small (XS) warehouse
- On both local and Snowflake, keep raw Parquet as the single source of truth so you can always replay / backfill

---

## 4. Infrastructure

| Component | Current | Extension |
|-----------|---------|-----------|
| Object storage | Local disk | S3 / GCS |
| Database | DuckDB | Snowflake |
| Runtime | VM / container | Cloud Run / Fargate |
| Credentials | `.env` + secrets | Secrets Manager |
| Scheduling | cron | Prefect / Airflow / Snowflake Tasks |
| IaC | — | Terraform |
| CI/CD | GitHub Actions | GitHub Actions |
| Data quality | dbt tests | dbt tests / Great Expectations |

> MVP: one VM + cron + DuckDB + Grafana is enough to get running — don't over-engineer.

---

## 5. Skillset (by priority)

1. **Data engineering** — orchestration, SQL, warehouse modeling, dbt
2. **Energy-market domain** — knowing what is signal
3. **Meteorology basics** — NWP / ensembles / forecast skill; translating variables into load and renewables
4. **Backend** — Python / FastAPI / data integration
5. **Data viz / geospatial**
6. **DevOps** — Terraform, containers, CI/CD, secrets
7. ML / forecasting (later; TimeXer foundation already in place)

---

## 6. Fundamentals beyond weather (ERCOT)

Weather is the most upstream driver, feeding both the **supply** and **demand** sides.

### Demand side
- **Load / net load**: temperature-driven, plus economic activity and Texas-specific crypto mining / large flexible loads. Focus on `net load = load − wind − solar` and its ramp (duck curve).

### Supply side
- **Renewable generation**: wind (West / Panhandle / Coastal zones behave very differently), solar (West Texas, growing fast)
- **Thermal fleet & outages**: gas (CCGT / peakers), coal, nuclear available capacity; planned + forced outages (ERCOT public)
- **Battery / BESS**: fastest-growing segment, materially reshapes net load and ancillary services

### Fuel
- **Natural gas prices**: gas is the marginal fuel → directly sets power price. Watch **Henry Hub, Waha (West Texas), Houston Ship Channel**. The gas–power correlation is central.

### Grid / market structure
- **Transmission congestion / nodal LMP**: nodal market (4000+ nodes); track the **basis** between trading hubs (North / South / West / Houston) and load zones
- **Scarcity / ORDC**: the Operating Reserve Demand Curve price adder drives the tail
- **Ancillary services**: RegUp / RegDown, RRS, ECRS, Non-Spin
- **Reserve margin / PRC**: an islanded interconnection (almost no imports) → inherently high volatility

### Exogenous tail (highest-value alerting scenarios)
- Extreme weather (e.g. Winter Storm Uri), Gulf hurricanes, heat waves

> Data sources: ERCOT MIS / API (or resellers like GridStatus.io / Yes Energy); gas via a commercial feed.

---

## 7. Granularity

- **Airport level is perfect for load / temperature**: stations like IAH / DFW / AUS / SAT have reliable ASOS data; population-weighted temperature is the industry-standard approach
- **Renewables can't use airports**: wind needs site / zonal granularity, solar needs West Texas irradiance — defer to Phase 2

---

## 8. Phased roadmap

| Phase | Scope | Storage |
|-------|-------|---------|
| **1 — MVP** | Ingest Meteologica → store with vintages → show temperature / wind / solar by metro, highlight run-over-run changes + simple alerting | Local Parquet + DuckDB |
| **2 — Fundamentals** | Add load, fuel mix, renewable actual/forecast, DAM/RTM prices; weather × load × price overlay | Local / evaluate Snowflake migration |
| **3 — Microstructure** | Add gas, congestion/basis, ORDC, ancillary; build net-load and forecast-delta → price relationships | **Snowflake** |
| **4 — Predictive** | Wire in forecasting models (TimeXer, etc.), backtesting, what-if | Snowflake + zero-copy clone for backtests |

> From v1, design the schema around weather-driven fundamentals + the medallion model, with Parquet as the canonical format, so the local → Snowflake migration needs no refactoring.
