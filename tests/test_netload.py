"""Tests for the net-load algorithm (no network)."""
from __future__ import annotations

import pandas as pd

from src.netload import MMBTU_PER_BCF, central_net_load, ensemble_net_load, implied_gas_burn_bcfd


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-06-10 00:00", periods=n, freq="h", tz="UTC", name="valid_time")


def test_central_net_load_subtracts_components() -> None:
    idx = _idx(3)
    demand = pd.DataFrame({"forecast": [70000, 72000, 75000]}, index=idx)
    wind = pd.DataFrame({"forecast": [10000, 12000, 8000]}, index=idx)
    pv = pd.DataFrame({"forecast": [5000, 9000, 0]}, index=idx)
    net = central_net_load(demand, wind, pv)
    assert net.tolist() == [55000, 51000, 67000]
    assert net.name == "net_load"


def test_central_net_load_aligns_on_common_index() -> None:
    demand = pd.DataFrame({"forecast": [70000, 72000, 75000]}, index=_idx(3))
    wind = pd.DataFrame({"forecast": [10000, 12000]}, index=_idx(2))  # shorter horizon
    pv = pd.DataFrame({"forecast": [5000, 9000]}, index=_idx(2))
    net = central_net_load(demand, wind, pv)
    assert len(net) == 2  # inner join -> only overlapping steps


def test_ensemble_net_load_member_wise_quantiles() -> None:
    idx = _idx(1)
    # 3 members; net_k = demand_k - wind_k - pv_k
    demand = pd.DataFrame({"ENS00": [70000], "ENS01": [70000], "ENS02": [70000]}, index=idx)
    wind = pd.DataFrame({"ENS00": [10000], "ENS01": [12000], "ENS02": [8000]}, index=idx)
    pv = pd.DataFrame({"ENS00": [5000], "ENS01": [5000], "ENS02": [5000]}, index=idx)
    fan = ensemble_net_load(demand, wind, pv)
    # member net loads: 55000, 53000, 57000 -> p50 = 55000
    assert fan["p50"].iloc[0] == 55000
    assert fan["p10"].iloc[0] < fan["p50"].iloc[0] < fan["p90"].iloc[0]
    assert fan["n_members"].iloc[0] == 3


def test_implied_gas_burn_formula_and_clip() -> None:
    nl = pd.Series([50000.0, 5000.0], index=_idx(2))
    burn = implied_gas_burn_bcfd(nl, baseload_mw=8000.0, heat_rate=7.5)
    # thermal = 42000 MW -> 42000 * 7.5 * 24 / MMBTU_PER_BCF
    assert abs(burn.iloc[0] - (42000.0 * 7.5 * 24.0 / MMBTU_PER_BCF)) < 1e-9
    assert burn.iloc[1] == 0.0  # net load below baseload -> clipped to 0
    assert list(burn.index) == list(nl.index)  # index preserved


def test_ensemble_uses_only_common_members() -> None:
    idx = _idx(1)
    demand = pd.DataFrame({"ENS00": [70000], "ENS01": [70000]}, index=idx)
    wind = pd.DataFrame({"ENS00": [10000], "ENS01": [12000], "ENS02": [8000]}, index=idx)
    pv = pd.DataFrame({"ENS00": [5000], "ENS01": [5000]}, index=idx)
    fan = ensemble_net_load(demand, wind, pv)
    assert fan["n_members"].iloc[0] == 2  # ENS02 dropped (not in demand/pv)
