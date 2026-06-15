# Meteologica "API markets" — Endpoint Reference

Reverse-engineered from the live login page + the OpenAPI spec at
`GET /api/v1/oas` (OpenAPI 3.1, title "Meteologica API"), verified live 2026-06-09.
This is the authoritative reference for the client in `src/meteologica_client.py`.

- **Base URL:** `https://api-markets.meteologica.com` (set in `.env` as `METEOLOGICA_BASE_URL`)
- **Credentials:** `METEOLOGICA_USERNAME` / `METEOLOGICA_PASSWORD` in `.env`

## Authentication

Two steps, but the API itself only needs the token as a **query parameter** — there
is **no `Authorization` header**.

1. **Log in** (the only POST, body is JSON):
   ```
   POST /api/v1/login    {"user": "<username>", "password": "<password>"}
     -> 200 {"token": "<JWT>", "expiration_date": "2026-06-09T23:25:23Z"}   # success
     -> 200 {"message": "<error text>"}                                     # failure (still HTTP 200!)
   ```
2. **Every other call** passes `?token=<JWT>`:
   ```
   GET /api/v1/contents?token=<JWT>
   ```

### Error shapes (important)
- Wrong/empty token → `400 {"message": "Error. Invalid token"}`
- Missing token query param → `400 {"message": "parameter \"token\" in query has an error: value is required but missing"}`
- Unknown endpoint → `400 {"message": "no matching operation was found"}`
- Failed login → `200 {"message": ...}` (NOT an HTTP error code)

Tokens are short-lived (~hours). Renew with `keepalive` (returns a fresh
`{token, expiration_date}`) or just log in again. The client refreshes proactively
before expiry and retries once on "Invalid token".

## Endpoints (all GET, all require `?token=`)

| Endpoint | Path params | Query params | Returns |
|----------|-------------|--------------|---------|
| `/api/v1/contents` | — | `token` | `{"contents": [{id, content_name, path}]}` — full catalog (2748 items) |
| `/api/v1/contents/{content_id}/data` | `content_id` | `token`, `update_id?`, `show_filename?` | latest (or specified-update) data — see below |
| `/api/v1/contents/{content_id}/historical_data/{year}/{month}` | `content_id, year, month` | `token` | data for that month (for backfill) |
| `/api/v1/contents/{content_id}/updates` | `content_id` | `token`, `start_date?`, `end_date?`, `show_filename?` | `{"updates": [{issue_date, update_id}]}` |
| `/api/v1/latest` | — | `token`, `seconds?` | contents updated recently |
| `/api/v1/keepalive` | — | `token` | `{token, expiration_date}` (renew) |
| `/api/v1/oas` | — | `token` | this API's OpenAPI 3.1 spec |
| `/api/v1/login` | — | (POST, JSON body) | `{token, expiration_date}` |

Dates are ISO 8601 `YYYY-MM-DDThh:mm:ssZ`.

## `/data` response shape

```json
{
  "content_id": 1943,
  "content_name": "USA ERCOT power demand forecast Meteologica hourly",
  "unit": "MW",
  "timezone": "America/Chicago",
  "issue_date": "2026-06-10 00:19:57 UTC",
  "update_id": "202606091800_livefeed_120H",
  "data": [ { ...row... }, ... ]
}
```

Each `data` row carries the validity interval in **local (CPT) wall time** plus an
explicit UTC offset, and one or more value columns:

- **Time columns (always):**
  `From yyyy-mm-dd hh:mm`, `To yyyy-mm-dd hh:mm`,
  `UTC offset from (UTC+/-hhmm)` (e.g. `UTC-0500`), `UTC offset to (UTC+/-hhmm)`.
  → `valid_time_utc = local_from - offset` (offset of `UTC-0500` means UTC = local + 5h).
- **Value columns — deterministic models** (`Meteologica`, `ECMWF-HRES`, `GFS`, `ARPEGE`):
  a single `forecast` column.
- **Value columns — ensemble models** (`GEFS`, `ECMWF-ENS`, `ECMWF-ENSEXT`):
  `Average`, `Bottom`, `Top`, and members `ENS00..ENSnn` (GEFS = 31 members,
  ECMWF-ENS = 51). All values are **strings** — cast to float downstream.

## Content taxonomy (the `path` field)

```
NorthAmerica/USA/ERCOT/<Sector>/<Quantity>/<Kind>/<Model>/<Zone>/<Agg>/<Resolution>
e.g. NorthAmerica/USA/ERCOT/Wind/PowerGeneration/Forecast/GEFS/Total/Hourly
```

- **Sectors (ERCOT, 408 contents):** `Wind` (140), `PV` (134), `PowerDemand` (78),
  `PowerPrice` (25), `PVPotential`/`WindPotential` (28), `BatteryStorage` (3).
  **No temperature/weather variables exist** anywhere in the catalog — this is a
  power-market product, not a raw-weather product.
- **Kind:** `Forecast`, `Observation` (actuals — 40 ERCOT obs), `Normal` (climatology
  baseline — no history accumulation needed), `Reanalysis` (ECMWF-ERA5).
- **Models:** `Meteologica` (proprietary blend; longest horizon ≈ 348 h), `ECMWF-HRES`,
  `GFS`, `ARPEGE` (deterministic); `GEFS`, `ECMWF-ENS`, `ECMWF-ENSEXT` (ensemble);
  `ECMWF-ERA5` (reanalysis); `HRRR`.
- **Zones:** `Total` (whole ERCOT), wind GeoRegions (`Coastal`, `Panhandle`, `North`,
  `South`, `West`), demand forecast/weather zones (`Houston`, `North`, `West`,
  `South`, `Coast`, `East`, `FarWest`, `NorthCentral`, `SouthCentral`), PV regions.
- **Price hubs (PowerPrice Observation):** `HB_HOUSTON`, `HB_NORTH`, `HB_SOUTH`,
  `HB_WEST`, `HB_BUSAVG`, `HB_HUBAVG` (day-ahead).

## Account-specific notes (veritionfund_ISO)

- **ECMWF data is served *through* the Meteologica account** (the token returns real
  ECMWF-ENS spread), so we **keep and use ECMWF-ENS**. We would only skip ECMWF if it
  required a *separate, direct ECMWF account* — which it does not.
- **ECMWF-ENS is the primary ensemble** because it exists for all three net-load
  components (demand, wind, PV), enabling a correct member-wise net-load fan. **GEFS**
  (31 members, wind/PV only — no demand ensemble) is kept as a secondary/cross-check.
- **Meteologica** (deterministic blend) has the **longest horizon (~348 h ≈ 14.5 d)**;
  ECMWF-ENS is shorter (~120 h ≈ 5 d). Design: Meteologica central line over the full
  horizon, ECMWF-ENS p10–p90 band over the first ~5 days.

## Resolved content IDs — Phase-1 net load (ERCOT Total, Hourly)

| Role | Model | Demand | Wind | PV |
|------|-------|--------|------|----|
| Central (deterministic, ~14.5 d) | Meteologica | **1943** | **1877** | **1840** |
| Ensemble fan (~5 d, 51 members) | ECMWF-ENS | **1957** | **1910** | **1856** |
| Ensemble (secondary, wind/PV only) | GEFS | — | **1915** | **5332** |

`net_load = demand − wind − pv`. IDs are resolved by exact `path` in
`src/registry.py` (not hard-coded blindly), so they stay verifiable.
