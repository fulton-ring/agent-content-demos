"""Read-only inputs for hazard pipelines: climate arrays, county weights and the NRI baseline.

Pipelines see climate data only for grid cells that overlap a CONUS county, as float32 arrays
shaped (time, cell). Cell order matches the columns of `county_weights()`.
"""

from functools import cache

import numpy as np
import pandas as pd
from scipy import sparse

from fri_rebuild import answer_key, geo, nex
from fri_rebuild.paths import cache_path

PERIODS = {"historical": (1976, 2005), "MID": (2036, 2065), "LATE": (2070, 2099)}
SSP = {"LOWER": "ssp245", "HIGHER": "ssp585"}


@cache
def grid() -> tuple[np.ndarray, np.ndarray]:
    """Latitude and longitude (degrees east, 0-360) of the NEX box."""
    data = np.load(nex.grid_path())
    return data["lat"], data["lon"]


@cache
def _box_weights() -> tuple[sparse.csr_matrix, pd.Index]:
    key = answer_key.conus(answer_key.load())
    counties = geo.counties()
    lat, lon = grid()
    return geo.area_weights(counties.loc[key.index], lat, lon, "counties")


@cache
def cell_index() -> np.ndarray:
    """Indices (into the flattened NEX box) of cells that overlap a county."""
    weights, _ = _box_weights()
    return np.flatnonzero(np.asarray(weights.sum(axis=0)).ravel() > 0)


@cache
def cell_coordinates() -> pd.DataFrame:
    """Latitude and longitude (-180..180) of each cell pipelines see."""
    lat, lon = grid()
    grid_lat, grid_lon = np.meshgrid(lat, np.where(lon > 180, lon - 360, lon), indexing="ij")
    cells = cell_index()
    return pd.DataFrame({"lat": grid_lat.ravel()[cells], "lon": grid_lon.ravel()[cells]})


_area_override: list[tuple[sparse.csr_matrix, pd.Index]] = []


def county_weights() -> tuple[sparse.csr_matrix, pd.Index]:
    """Intersection area (km^2) of each CONUS county (rows) with each cell (columns).

    Pipelines must aggregate cells to areas only through this function: the tract downscaling
    reruns the same pipeline with tract weights in place of county weights.
    """
    if _area_override:
        return _area_override[-1]
    return _conus_county_weights()


@cache
def _conus_county_weights() -> tuple[sparse.csr_matrix, pd.Index]:
    weights, fips = _box_weights()
    return weights[:, cell_index()].tocsr(), fips


def use_tracts(state_fips: str) -> None:
    """Make `county_weights()` return the 2020 tracts of one state instead of counties."""
    lat, lon = grid()
    shapes = geo.tracts(state_fips)
    weights, ids = geo.area_weights(shapes, lat, lon, f"tracts_{state_fips}")
    _area_override.append((weights[:, cell_index()].tocsr(), ids))


def period_years(scenario: str, period: str) -> range:
    first, last = PERIODS[period]
    if (scenario == "historical") != (period == "historical"):
        raise ValueError(f"{period} is not a {scenario} period")
    return range(first, last + 1)


def daily(variable: str, scenario: str, period: str) -> np.ndarray:
    """Daily values (tasmin/tas in deg C, hurs in %) for one 30-year period, shape (days, cells).

    scenario is 'historical', 'ssp245' or 'ssp585'; period is 'historical', 'MID' or 'LATE'.
    """
    target = cache_path("inputs", "daily", f"{variable}_{scenario}_{period}.npy")
    if not target.exists():
        cells = cell_index()
        years = [
            np.load(nex.daily_path(variable, scenario, year)).reshape(-1, nex_cells())[:, cells]
            for year in period_years(scenario, period)
        ]
        np.save(target, np.concatenate(years))
    values = np.load(target).astype(np.float32)
    values[values == nex.MISSING] = np.nan
    return values / nex.SCALE


def daily_dates(scenario: str, period: str) -> pd.DatetimeIndex:
    """Calendar dates matching the rows of `daily` (NEX keeps leap days)."""
    years = period_years(scenario, period)
    return pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31", freq="D")


def monthly(variable: str, scenario: str) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """Monthly means (tas deg C, pr mm/day) from 1950 to 2100, shape (months, cells).

    For ssp245/ssp585 the historical run (1950-2014) is joined to the scenario run (2015-2100).
    """
    target = cache_path("inputs", "monthly", f"{variable}_{scenario}.npy")
    years = [*nex.MONTHLY_YEARS["historical"]]
    if scenario != "historical":
        years += [*nex.MONTHLY_YEARS[scenario]]
    if not target.exists():
        cells = cell_index()
        stacks = []
        for year in years:
            run = "historical" if year <= 2014 else scenario
            stacks.append(np.load(nex.monthly_path(variable, run, year)).reshape(12, -1)[:, cells])
        np.save(target, np.concatenate(stacks).astype(np.float32))
    months = pd.date_range(f"{years[0]}-01-01", periods=12 * len(years), freq="MS")
    return np.load(target), months


def nex_cells() -> int:
    lat, lon = grid()
    return len(lat) * len(lon)


def baseline() -> pd.DataFrame:
    """NRI baseline for CONUS counties as published in the master datasheet (EAL by hazard)."""
    key = answer_key.conus(answer_key.load())
    columns = [c for c in key.columns if c.endswith(("_EALT", "_EALR"))]
    return key[["STATEABBRV", "COUNTY", *columns]]


def fwi(scenario: str, period: str, variable: str = "FWI", ensemble: str = "MME50") -> np.ndarray:
    """Yearly Fire Weather Index statistics (NEX-GDDP-CMIP6 FWI, multi-model ensemble), shape
    (years available, cells). Years missing on NASA's portal are left out.

    variable: FWI (annual mean), FWI_P25/P50/P75/P95, FWI_N15/N30/N45 (days above 15/30/45),
    FWI_NP95, FWI_Nmid, FFMC, DMC, DC, ISI, BUI. ensemble: MME25, MME50 or MME75.
    """
    from fri_rebuild import fwi as fwi_source

    cells = cell_index()
    rows = []
    for year in period_years(scenario, period):
        path = fwi_source.year_path(ensemble, scenario, year)
        if path.exists():
            rows.append(np.load(path)[variable].reshape(-1)[cells])
    return np.stack(rows)


def county_fuel_shares() -> pd.DataFrame:
    """Share of LANDFIRE LF2022 FBFM40 fuel-model groups in each county (500 m sampling)."""
    from fri_rebuild import landfire

    _, fips = county_weights()
    return landfire.fuel_shares(geo.counties().loc[fips], "counties")
