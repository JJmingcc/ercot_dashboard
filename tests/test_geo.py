"""Tests for src.geo (pure geometry helpers; no network)."""
from __future__ import annotations

from src.geo import MARKET_STATE_FIPS, _centroid, nearest_zone


def test_centroid_is_mean_of_coords() -> None:
    geom = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    lat, lon = _centroid(geom)
    assert round(lon, 2) == 0.8  # mean of x = (0+2+2+0+0)/5
    assert round(lat, 2) == 0.8  # mean of y


def test_centroid_handles_multipolygon_nesting() -> None:
    geom = {"type": "MultiPolygon",
            "coordinates": [[[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]]}
    lat, lon = _centroid(geom)
    assert lat == 4.0 and lon == 4.0  # mean of the 5 points


def test_nearest_zone_picks_closest_city() -> None:
    zones = {"West": (31.0, -100.0, "w"), "East": (40.0, -80.0, "e")}
    assert nearest_zone(31.5, -99.0, zones) == "West"
    assert nearest_zone(39.0, -81.0, zones) == "East"


def test_ercot_is_texas_only() -> None:
    assert MARKET_STATE_FIPS["ERCOT"] == {"48"}
