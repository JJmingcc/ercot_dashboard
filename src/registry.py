"""Curated registry of ERCOT contents used by the net-load monitor.

Content IDs are *resolved by exact path* from the live catalog rather than
hard-coded, so they are verifiable and survive any catalog re-numbering. See
docs/meteologica-api.md for the taxonomy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .meteologica_client import MeteologicaClient

_ERCOT = "NorthAmerica/USA/ERCOT"


@dataclass(frozen=True)
class Series:
    """One net-load component: a role + the model + its exact catalog path."""
    role: str          # 'demand' | 'wind' | 'pv'
    model: str         # 'Meteologica' | 'ECMWF-ENS' | 'GEFS'
    path: str
    kind: str = "central"  # 'central' (deterministic) | 'ensemble'


# ERCOT-Total, hourly. Central = Meteologica deterministic (longest horizon);
# ensemble = ECMWF-ENS (covers all three components -> member-wise net-load fan).
NET_LOAD_SERIES: tuple[Series, ...] = (
    Series("demand", "Meteologica", f"{_ERCOT}/PowerDemand/Forecast/Meteologica/Total/Hourly"),
    Series("wind",   "Meteologica", f"{_ERCOT}/Wind/PowerGeneration/Forecast/Meteologica/Total/Hourly"),
    Series("pv",     "Meteologica", f"{_ERCOT}/PV/PowerGeneration/Forecast/Meteologica/Total/Hourly"),
    Series("demand", "ECMWF-ENS", f"{_ERCOT}/PowerDemand/Forecast/ECMWF-ENS/Total/Hourly", "ensemble"),
    Series("wind",   "ECMWF-ENS", f"{_ERCOT}/Wind/PowerGeneration/Forecast/ECMWF-ENS/Total/Hourly", "ensemble"),
    Series("pv",     "ECMWF-ENS", f"{_ERCOT}/PV/PowerGeneration/Forecast/ECMWF-ENS/Total/Hourly", "ensemble"),
)


@dataclass(frozen=True)
class ResolvedSeries:
    role: str
    model: str
    kind: str
    content_id: int
    content_name: str


class Registry:
    """Maps the declared net-load series to live content IDs."""

    def __init__(self, resolved: tuple[ResolvedSeries, ...]) -> None:
        self._resolved = resolved

    @classmethod
    def load(cls, client: Optional[MeteologicaClient] = None) -> "Registry":
        client = client or MeteologicaClient()
        by_path = {c["path"]: c for c in client.list_datasets()}
        resolved: list[ResolvedSeries] = []
        missing: list[str] = []
        for s in NET_LOAD_SERIES:
            c = by_path.get(s.path)
            if c is None:
                missing.append(s.path)
                continue
            resolved.append(
                ResolvedSeries(s.role, s.model, s.kind, c["id"], c["content_name"])
            )
        if missing:
            raise LookupError(
                "Registry could not resolve these paths in the catalog:\n  "
                + "\n  ".join(missing)
            )
        return cls(tuple(resolved))

    def get(self, role: str, kind: str) -> ResolvedSeries:
        for r in self._resolved:
            if r.role == role and r.kind == kind:
                return r
        raise KeyError(f"No series for role={role!r} kind={kind!r}")

    def central(self, role: str) -> ResolvedSeries:
        return self.get(role, "central")

    def ensemble(self, role: str) -> ResolvedSeries:
        return self.get(role, "ensemble")

    @property
    def all(self) -> tuple[ResolvedSeries, ...]:
        return self._resolved
