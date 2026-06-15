# ERCOT Weather-Driven Fundamentals Monitor

Dashboard for the ERCOT market using Meteologica forecast data. See
`ercot-dashboard-plan.md` for the design and roadmap.

## Quick start (one click)

```bash
./run.sh                            # set up (once) AND launch the dashboard → http://localhost:8501
```

`run.sh` is idempotent: it creates the `dash_env/` virtualenv if missing, installs the **app**
dependencies (`requirements-app.txt` = base + Streamlit/Plotly/Shapely), bootstraps `.env` from
`.env.example` on first run, then starts Streamlit. Use `PORT=8600 ./run.sh` for a different port.
Fill in your real credentials in `.env` (Streamlit auto-reloads on save) — see **Credentials** below.

## Setup (manual / dev)

```bash
./setup.sh                          # creates dash_env/ and installs the base requirements
source dash_env/bin/activate        # always work inside dash_env
pip install -r requirements-app.txt # add the dashboard deps (Streamlit/Plotly/Shapely)
python -m src.meteologica_client    # smoke-test that credentials load (no network)
python -m src.meteologica_client --login   # live auth check against the API
streamlit run app/app.py            # run the dashboard manually
```

The project environment is **`dash_env/`** (a local venv). Use that one
consistently — do not rely on conda `base` or a generic `venv/`.

## Credentials

Secrets live in `.env` (gitignored). Template is `.env.example`:

```
METEOLOGICA_USERNAME=...
METEOLOGICA_PASSWORD=...
METEOLOGICA_BASE_URL=https://api-markets.meteologica.com
```

`src/config.py` loads these via `python-dotenv`; nothing is hard-coded.

## Documentation

- `docs/workflow.html` — **printable one-pager** of the daily trading workflow (open in a browser).
- `docs/usage.md` — **dashboard flow & how to use it** (the two dashboards, the trading workflow).
- `docs/trading-strategies.md` — **every signal** with its input → output, data source, and build
  status (gas burn, run-over-run revision, ensemble tail, spark spread, weather-normalized drift, …).
- `docs/concepts.md` — **glossary**: net load, heat rate, implied gas burn, **spark spread**,
  **run-over-run revision**, the NWP **forecast methods** and what they're based on, the
  **benefits of ensemble forecasting**, and **temperature normalization** (climate normal/anomaly).
- `docs/data-sources.md` — exact model ids / datasets / API access & limits (provenance).
- `docs/meteologica-api.md` — Meteologica API endpoints, auth, response shapes.

## Layout

```
.env                 # real secrets (gitignored)
.env.example         # template
requirements.txt
setup.sh             # create dash_env + install deps
dash_env/            # project virtual environment (gitignored)
src/
  config.py          # loads credentials from .env
  meteologica_client.py  # API client: login + all data endpoints implemented
  probe_api.py       # one-shot probe to discover API auth/endpoints
```

## Auth flow (confirmed against `/api/v1/oas`)

Log in once, then pass the token as a **query parameter** on every call (this API
does *not* use an Authorization header):

```
POST /api/v1/login        {"user": "...", "password": "..."}
  -> {"token": "<JWT>", "expiration_date": "2026-06-09T23:25:23Z"}

GET  /api/v1/contents?token=<JWT>          # and every other endpoint
  -> 400 {"message": "Error. Invalid token"}   # when the token is expired/invalid
```

The machine-readable spec itself is `GET /api/v1/oas?token=<JWT>` (OpenAPI 3.1).

## Endpoints (all GET, all require `?token=`)

| Method | Purpose |
|--------|---------|
| `list_datasets()` | `/api/v1/contents` — catalog (~2748 items: `id`, `content_name`, `path`) |
| `search_contents(q)` | client-side filter of the catalog by name/path |
| `get_content_data(id)` | `/api/v1/contents/{id}/data` — latest forecast (`data` rows + `unit`, `timezone`, `issue_date`, `update_id`) |
| `get_historical_data(id, year, month)` | `/api/v1/contents/{id}/historical_data/{year}/{month}` |
| `get_updates(id, start_date=, end_date=)` | `/api/v1/contents/{id}/updates` |
| `get_latest(seconds=)` | `/api/v1/latest` — recently-updated contents |
| `keepalive()` | `/api/v1/keepalive` — renew the token |

Example:

```python
from src.meteologica_client import MeteologicaClient

c = MeteologicaClient()
ercot = c.search_contents("ERCOT")          # 408 ERCOT contents
ts = c.get_content_data(ercot[0]["id"])     # latest forecast for the first one
print(ts["unit"], ts["timezone"], len(ts["data"]))
```

## Tests

```bash
source dash_env/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q          # 24 tests, network fully mocked
```
