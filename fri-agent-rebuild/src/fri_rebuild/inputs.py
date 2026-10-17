"""Read-only inputs for hazard pipelines: climate arrays, county weights and the NRI baseline.

Pipelines see climate data only for grid cells that overlap a CONUS county, as float32 arrays
shaped (time, cell). Cell order matches the columns of `county_weights()`.
"""

from functools import cache

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import sparse

from fri_rebuild.paths import cache_path
from fri_rebuild.scoring import answer_key
from fri_rebuild.sources import geo, nex

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


# Intersection areas (km^2) of areas (rows) with the cells pipelines see (columns), and area ids.
AreaWeights = tuple[sparse.csr_matrix, pd.Index]


@cache
def county_weights() -> AreaWeights:
    """Intersection area (km^2) of each CONUS county (rows) with each cell (columns).

    The tract downscaling reruns a pipeline with `tract_weights` passed in place of these.
    """
    weights, fips = _box_weights()
    return weights[:, cell_index()].tocsr(), fips


def tract_weights(state_fips: str) -> AreaWeights:
    """Like `county_weights`, for the 2020 census tracts of one state."""
    lat, lon = grid()
    shapes = geo.tracts(state_fips)
    weights, ids = geo.area_weights(shapes, lat, lon, f"tracts_{state_fips}")
    return weights[:, cell_index()].tocsr(), ids


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
    from fri_rebuild.sources import fwi as fwi_source

    cells = cell_index()
    rows = []
    for year in period_years(scenario, period):
        path = fwi_source.year_path(ensemble, scenario, year)
        if path.exists():
            rows.append(np.load(path)[variable].reshape(-1)[cells])
    return np.stack(rows)


def county_fuel_shares() -> pd.DataFrame:
    """Share of LANDFIRE LF2022 FBFM40 fuel-model groups in each county (500 m sampling)."""
    from fri_rebuild.sources import landfire

    _, fips = county_weights()
    return landfire.fuel_shares(geo.counties().loc[fips], "counties")


def loca2_histogram(scenario: str, period: str) -> tuple[np.ndarray, np.ndarray]:
    """Daily tasmin histograms from LOCA2 (MPI-ESM1-2-HR, 1/16 degree) for one 30-year period.

    Returns (edges, counts). `edges` are bin edges in deg C (first and last are -inf/inf, bins
    are 0.1 deg C wide from -10 to 40). `counts` has shape (bins + 1, cells): one row per bin plus
    a last row counting days with no data. scenario is 'historical', 'ssp245' or 'ssp585';
    period is 'historical', 'MID' or 'LATE'.
    """
    from fri_rebuild.sources import loca2

    return loca2.EDGES, np.load(loca2.histogram_path(scenario, period))


def loca2_county_weights() -> tuple[sparse.csr_matrix, pd.Index]:
    """County x cell intersection areas (km^2) for the LOCA2 cells in `loca2_histogram`."""
    from fri_rebuild.sources import loca2

    _, weights, fips = loca2.county_weights()
    return weights, fips


def coastal_tables() -> dict[str, pd.DataFrame]:
    """NOAA tide-gauge tables for coastal flooding (sources: fri_rebuild.sources.tide_gauges).

    Keys: htf_decadal (projected flood days/year by station, decade 2020-2100, severity and 2022
    scenario: low, intLow, intermediate, intHigh, high), htf_observed (observed flood days per
    meteorological year and severity), extreme_water_levels (187 gauges: return levels in m above
    MHHW for 0.1-100 year return periods, adjusted to 2000), sea_level_projections (relative sea
    level rise in cm by scenario and decade, per gauge and 1-degree grid) and flood_thresholds
    (NOAA minor/moderate/major thresholds in m above MHHW).
    """
    from fri_rebuild.sources import tide_gauges

    return tide_gauges.tables()


def county_shapes() -> gpd.GeoDataFrame:
    """CONUS county polygons (a GeoDataFrame, EPSG:4269) indexed by FIPS."""
    _, fips = county_weights()
    return geo.counties().loc[fips]


def points(table: pd.DataFrame, lon: str = "lon", lat: str = "lat") -> gpd.GeoDataFrame:
    """Turn a table with lon/lat columns into a point GeoDataFrame (EPSG:4326)."""
    return geo.points(table, lon, lat)
