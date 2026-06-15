"""Net-load algorithm for ERCOT: net load = demand - wind - pv.

Two outputs:
  * central net load  — from the Meteologica deterministic blend (long horizon)
  * ensemble net load — member-wise from ECMWF-ENS (demand_k - wind_k - pv_k),
    summarised as p10/p50/p90 (the fan).

Pure functions operate on parsed frames (see parsing.py); `compute_live()` wires
them to the API for a local end-to-end run.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .meteologica_client import MeteologicaClient
from .parsing import ParsedData, central_column, member_columns, parse_data
from .registry import Registry


# Natural gas HHV: ~1037 Btu/cf -> MMBtu per Bcf. Used to convert burn rate to Bcf/d.
MMBTU_PER_BCF = 1.037e6


def implied_gas_burn_bcfd(net_load_mw, baseload_mw: float, heat_rate: float = 7.5):
    """Instantaneous power-sector gas-burn rate (Bcf/d) implied by net load.

    thermal = max(net_load - must-run baseload, 0); burn = thermal[MW] * heat_rate
    [MMBtu/MWh] = MMBtu/h, scaled to Bcf/d. Takes a Series/DataFrame (index preserved).
    A signal (heat rate + baseload are assumptions), not an EIA-grade balance.
    """
    thermal = (net_load_mw - baseload_mw).clip(lower=0)
    return thermal * heat_rate * 24.0 / MMBTU_PER_BCF


def central_net_load(demand: pd.DataFrame, wind: pd.DataFrame, pv: pd.DataFrame) -> pd.Series:
    """Deterministic net load, aligned on the common UTC timestamps (inner join)."""
    d = demand[central_column(demand)]
    w = wind[central_column(wind)]
    p = pv[central_column(pv)]
    idx = d.index.intersection(w.index).intersection(p.index)
    net = d.loc[idx] - w.loc[idx] - p.loc[idx]
    return net.rename("net_load").sort_index()


def ensemble_net_load(demand: pd.DataFrame, wind: pd.DataFrame, pv: pd.DataFrame) -> pd.DataFrame:
    """Member-wise net load -> p10/p50/p90 fan.

    Uses only the ensemble members common to all three components, on their common
    timestamps. Each member k: net_k = demand_k - wind_k - pv_k.
    """
    members = sorted(
        set(member_columns(demand)) & set(member_columns(wind)) & set(member_columns(pv))
    )
    if not members:
        raise ValueError("No common ensemble members across demand/wind/pv.")
    idx = demand.index.intersection(wind.index).intersection(pv.index)
    net = (
        demand.loc[idx, members] - wind.loc[idx, members] - pv.loc[idx, members]
    ).sort_index()
    out = pd.DataFrame(
        {
            "p10": net.quantile(0.10, axis=1),
            "p50": net.quantile(0.50, axis=1),
            "p90": net.quantile(0.90, axis=1),
            "n_members": len(members),
        }
    )
    return out


def compute_live(client: Optional[MeteologicaClient] = None) -> pd.DataFrame:
    """Pull the latest data and return a combined net-load frame (local end-to-end run).

    Columns: net_load_central, p10, p50, p90 (NaN beyond the ECMWF-ENS horizon).
    """
    client = client or MeteologicaClient()
    reg = Registry.load(client)

    def pull(series) -> ParsedData:
        return parse_data(client.get_content_data(series.content_id))

    demand_c = pull(reg.central("demand")).frame
    wind_c = pull(reg.central("wind")).frame
    pv_c = pull(reg.central("pv")).frame
    central = central_net_load(demand_c, wind_c, pv_c)

    demand_e = pull(reg.ensemble("demand")).frame
    wind_e = pull(reg.ensemble("wind")).frame
    pv_e = pull(reg.ensemble("pv")).frame
    fan = ensemble_net_load(demand_e, wind_e, pv_e)

    combined = pd.concat(
        [central.rename("net_load_central"), fan[["p10", "p50", "p90"]]],
        axis=1, sort=False,
    ).sort_index()
    return combined


def compute_dashboard_frame(
    client: Optional[MeteologicaClient] = None,
) -> tuple[pd.DataFrame, dict]:
    """Assemble everything the dashboard needs in one UTC-indexed frame.

    Columns: demand, wind, pv, renewables, net_load (all Meteologica central),
    and p10/p50/p90 (ECMWF-ENS net-load fan, NaN beyond its horizon).
    Returns (frame, meta) where meta carries unit/issue_time/update_id.
    """
    client = client or MeteologicaClient()
    reg = Registry.load(client)

    def pull(series) -> ParsedData:
        return parse_data(client.get_content_data(series.content_id))

    dC, wC, pC = pull(reg.central("demand")), pull(reg.central("wind")), pull(reg.central("pv"))
    frame = pd.concat(
        [
            dC.frame[central_column(dC.frame)].rename("demand"),
            wC.frame[central_column(wC.frame)].rename("wind"),
            pC.frame[central_column(pC.frame)].rename("pv"),
        ],
        axis=1, sort=False,
    )
    frame["renewables"] = frame["wind"] + frame["pv"]
    frame["net_load"] = frame["demand"] - frame["renewables"]

    dE, wE, pE = (
        pull(reg.ensemble("demand")).frame,
        pull(reg.ensemble("wind")).frame,
        pull(reg.ensemble("pv")).frame,
    )
    fan = ensemble_net_load(dE, wE, pE)
    frame = pd.concat([frame, fan[["p10", "p50", "p90"]]], axis=1, sort=False).sort_index()

    meta = {
        "unit": dC.unit,
        "timezone": dC.timezone,
        "issue_time": dC.issue_time,
        "update_id": dC.update_id,
    }
    return frame, meta


def _summarise(df: pd.DataFrame) -> None:
    central = df["net_load_central"].dropna()
    peak_t = central.idxmax()
    print(f"Horizon: {df.index.min()}  ->  {df.index.max()}  ({len(df)} hourly steps)")
    print(f"Central net load: min={central.min():,.0f}  max={central.max():,.0f} MW (unit: MW)")
    print(f"Peak central net load: {central.max():,.0f} MW at {peak_t} (UTC)")
    band = df.dropna(subset=["p50"])
    if not band.empty:
        bt = band["p50"].idxmax()
        row = band.loc[bt]
        print(
            f"Ensemble fan covers {band.index.min()} -> {band.index.max()} "
            f"({len(band)} steps).\n"
            f"  Peak p50 net load: {row['p50']:,.0f} MW at {bt} "
            f"(p10={row['p10']:,.0f}, p90={row['p90']:,.0f}; "
            f"band width {row['p90'] - row['p10']:,.0f} MW)"
        )


if __name__ == "__main__":
    import pathlib

    result = compute_live()
    _summarise(result)
    out_dir = pathlib.Path("data")
    out_dir.mkdir(exist_ok=True)
    result.to_parquet(out_dir / "netload_demo.parquet")
    result.to_csv(out_dir / "netload_demo.csv")
    print(f"\nSaved -> {out_dir/'netload_demo.parquet'} and .csv")
