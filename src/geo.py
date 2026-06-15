"""County geometry helpers for the temperature choropleth.

Uses the standard US-counties GeoJSON (FIPS ids). Each county is assigned to the
nearest market zone, so the map fills the zone "blocks" (e.g. ERCOT Far West,
West, South, South Central, Coast …) with visible county/zone borders — a finer,
block-aware view than point markers. Geometry is approximate (nearest-zone-city),
which the dashboard plan explicitly allows as the fallback to true zone polygons.
"""
from __future__ import annotations

import json
import pathlib

import requests

COUNTIES_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
_CACHE = pathlib.Path(__file__).resolve().parent.parent / "data" / "us_counties_fips.json"

# State FIPS prefixes that (approximately) make up each market's footprint.
MARKET_STATE_FIPS: dict[str, set[str]] = {
    "ERCOT": {"48"},                                   # Texas
    "CAISO": {"06"},                                   # California
    "PJM": {"10", "11", "17", "18", "21", "24", "26", "34", "37", "39", "42", "47", "51", "54"},
    "SPP": {"05", "20", "22", "29", "30", "31", "35", "38", "40", "46", "48", "56"},
    "MISO": {"05", "17", "18", "19", "21", "22", "26", "27", "28", "29", "38", "46", "48", "55"},
    # Continental US (excludes AK '02' and HI '15').
    "USA": {"01", "04", "05", "06", "08", "09", "10", "11", "12", "13", "16", "17", "18",
            "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31",
            "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "44", "45",
            "46", "47", "48", "49", "50", "51", "53", "54", "55", "56"},
}


def load_counties() -> dict:
    """US counties GeoJSON (cached to disk after first download)."""
    if _CACHE.exists():
        return json.loads(_CACHE.read_text())
    resp = requests.get(COUNTIES_URL, timeout=60)
    resp.raise_for_status()
    geojson = resp.json()
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(geojson))
    return geojson


def _centroid(geometry: dict) -> tuple[float, float]:
    """Rough (lat, lon) centroid = mean of a geometry's coordinates."""
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords) -> None:
        if coords and isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
        else:
            for c in coords:
                walk(c)

    walk(geometry["coordinates"])
    return (sum(ys) / len(ys), sum(xs) / len(xs))


def market_counties(market: str, counties: dict) -> list[tuple[str, float, float]]:
    """[(fips, lat, lon)] for every county in the market's states."""
    states = MARKET_STATE_FIPS.get(market, set())
    out = []
    for feat in counties["features"]:
        fips = feat["id"]
        if fips[:2] in states:
            lat, lon = _centroid(feat["geometry"])
            out.append((fips, lat, lon))
    return out


def nearest_zone(lat: float, lon: float, zones: dict[str, tuple[float, float, str]]) -> str:
    """Name of the zone whose representative city is nearest (planar distance)."""
    best, best_d = "", float("inf")
    for zone, (zlat, zlon, _) in zones.items():
        d = (lat - zlat) ** 2 + (lon - zlon) ** 2
        if d < best_d:
            best, best_d = zone, d
    return best


def subsample(recs: list, max_n: int) -> list:
    """Evenly thin a list of (fips, lat, lon) records to at most `max_n` items.

    Keeps the Open-Meteo request small/affordable for large markets; every county is
    still coloured (via assign_nearest_index), just sharing values from sampled points.
    """
    if len(recs) <= max_n:
        return recs
    step = len(recs) / max_n
    return [recs[int(i * step)] for i in range(max_n)]


def assign_nearest_index(targets: list, samples: list) -> list[int]:
    """For each target (fips, lat, lon), the index of the nearest sample point."""
    pts = [(s[1], s[2]) for s in samples]
    out: list[int] = []
    for _, tlat, tlon in targets:
        bi, bd = 0, float("inf")
        for i, (slat, slon) in enumerate(pts):
            d = (tlat - slat) ** 2 + (tlon - slon) ** 2
            if d < bd:
                bd, bi = d, i
        out.append(bi)
    return out


def zone_boundaries(market: str, counties: dict,
                    zones: dict[str, tuple[float, float, str]]) -> tuple[list, list]:
    """Dissolve the market's counties into zone polygons and return their outline.

    Returns (lats, lons) polyline coordinates with `None` separators between rings,
    ready to draw as a single Scattergeo line trace over the per-county choropleth.
    """
    from shapely.geometry import shape
    from shapely.ops import unary_union

    groups: dict[str, list] = {}
    states = MARKET_STATE_FIPS.get(market, set())
    for feat in counties["features"]:
        if feat["id"][:2] not in states:
            continue
        lat, lon = _centroid(feat["geometry"])
        groups.setdefault(nearest_zone(lat, lon, zones), []).append(shape(feat["geometry"]))

    lats: list = []
    lons: list = []
    for geoms in groups.values():
        merged = unary_union(geoms)
        polys = merged.geoms if merged.geom_type == "MultiPolygon" else [merged]
        for poly in polys:
            xs, ys = poly.exterior.xy
            lons += list(xs) + [None]
            lats += list(ys) + [None]
    return lats, lons
