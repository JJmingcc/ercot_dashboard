"""EIA-930 hourly generation by fuel for ERCOT — *actual* gas generation.

Grounds the implied gas burn in measured data instead of the net-load − baseload proxy:
the must-run baseload isn't in Meteologica, but EIA publishes ERCOT (respondent 'ERCO')
hourly net generation by fuel — including natural gas (NG) — back to ~2018-07, for free.

Setup: register for a free key at https://www.eia.gov/opendata/register.php and put
    EIA_API_KEY=...   in .env
Then `gas burn (Bcf/d) = NG generation (MW) × heat_rate × 24 / 1.037e6` (no baseload guess).

NOTE: untested until a key is supplied (the endpoint/facets are verified; only the key is
missing). EIA v2 returns rows {period, respondent, fueltype, value, value-units}.
"""
from __future__ import annotations

import os

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import PROJECT_ROOT

EIA_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
# EIA fuel-type codes (subset): NG=natural gas, COL=coal, NUC=nuclear, WAT=hydro,
# SUN=solar, WND=wind, OTH=other. ERCOT balancing-authority respondent = 'ERCO'.
FUELS = {"NG": "natural gas", "COL": "coal", "NUC": "nuclear", "WAT": "hydro",
         "SUN": "solar", "WND": "wind", "OTH": "other"}


def _api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        raise RuntimeError(
            "EIA_API_KEY not set. Register (free) at https://www.eia.gov/opendata/register.php "
            "and add EIA_API_KEY=... to .env."
        )
    return key


def fuel_generation(start: str, end: str, fueltype: str = "NG",
                    respondent: str = "ERCO") -> pd.Series:
    """Hourly net generation (MW) for one fuel, UTC-indexed. `start`/`end` = 'YYYY-MM-DDTHH'."""
    key = _api_key()
    rows: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(EIA_URL, params={
            "api_key": key, "frequency": "hourly", "data[0]": "value",
            "facets[respondent][]": respondent, "facets[fueltype][]": fueltype,
            "start": start, "end": end, "length": 5000, "offset": offset,
        }, timeout=90)
        resp.raise_for_status()
        data = resp.json().get("response", {}).get("data", [])
        rows += data
        if len(data) < 5000:
            break
        offset += 5000
    if not rows:
        return pd.Series(dtype="float64", name=fueltype)
    df = pd.DataFrame(rows)
    idx = pd.DatetimeIndex(pd.to_datetime(df["period"], utc=True), name="valid_time")
    return pd.Series(pd.to_numeric(df["value"], errors="coerce").values, index=idx,
                     name=fueltype).sort_index()


def ercot_gas_generation(start: str, end: str) -> pd.Series:
    """Convenience: hourly ERCOT natural-gas generation (MW)."""
    return fuel_generation(start, end, fueltype="NG", respondent="ERCO")
