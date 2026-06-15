"""Per-zone ERCOT demand — the spatial view.

Meteologica publishes demand forecasts for the 8 ERCOT weather zones (Coast, East, Far West,
North, North Central, South Central, Southern, West). Demand is weather-driven (their models do
the temperature→demand correlation internally), so this gives a per-zone demand *value* we can
put on a map. Zone names here match `weather.MARKETS["ERCOT"]["zones"]` so the choropleth lines up.

(Net load stays a system quantity — renewables are dispatched grid-wide — so this is demand-only.)
"""
from __future__ import annotations

import pandas as pd

from .meteologica_client import MeteologicaClient
from .parsing import central_column, parse_data

# Display zone name (from weather.MARKETS) -> Meteologica path segment.
ZONE_SEGMENT = {
    "Coast": "Coast", "East": "East", "Far West": "FarWest", "North": "North",
    "North Central": "NorthCentral", "South Central": "SouthCentral",
    "Southern": "Southern", "West": "West",
}
_DEMAND_PATH = "NorthAmerica/USA/ERCOT/PowerDemand/Forecast/Meteologica/{seg}/Total/Hourly"


def zone_demand_forecast(client: MeteologicaClient | None = None) -> pd.DataFrame:
    """Hourly demand forecast (MW) for the 8 ERCOT weather zones — columns = display zone names,
    UTC-indexed. Resolves content ids by exact path (survives catalog re-numbering)."""
    client = client or MeteologicaClient()
    by_path = {c["path"]: c for c in client.list_datasets()}
    out: dict[str, pd.Series] = {}
    for disp, seg in ZONE_SEGMENT.items():
        c = by_path.get(_DEMAND_PATH.format(seg=seg))
        if c is None:
            continue
        parsed = parse_data(client.get_content_data(c["id"]))
        out[disp] = parsed.frame[central_column(parsed.frame)]
    return pd.DataFrame(out)


