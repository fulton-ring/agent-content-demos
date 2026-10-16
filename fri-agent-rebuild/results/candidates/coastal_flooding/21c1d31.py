"""Coastal flooding hazard multipliers from NOAA high-tide-flooding projections.

FRI Technical Documentation, Section 4: each county takes the projected minor, moderate and
major high-tide-flooding frequencies of its nearest tide gauge. For each sub-type, the frequency
adjustment factor is projected / current frequency, and the county HM is the sum over sub-types
of that factor times the sub-type's share of the county's coastal flooding EAL.
"""

import geopandas as gpd
import numpy as np
import pandas as pd

from fri_rebuild import inputs

SEVERITIES = ("minor", "moderate", "major")
SCENARIOS = {"LOWER": "intermediate", "HIGHER": "high"}
DECADES = {"MID": 2050, "LATE": 2100}
CURRENT_DECADE = 2020


def station_frequencies() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Current (2020 decade of projections) and projected flood days per year."""
    tables = inputs.coastal_tables()
    projected = tables["htf_decadal"]
    base = projected[projected["decade"] == CURRENT_DECADE]
    # average over scenarios (2020 values should be nearly identical across scenarios)
    current = base.pivot_table(index="station", columns="severity", values="days", aggfunc="mean")
    current = current.reindex(columns=list(SEVERITIES))
    return current, projected


def nearest_station(stations: pd.DataFrame) -> pd.Series:
    """Nearest station (by distance from the county polygon) for each coastal county."""
    counties = inputs.county_shapes()
    coastal = inputs.baseline()["CFLD_EALT"] > 0
    shapes = counties.loc[coastal[coastal].index].to_crs("EPSG:5070")
    points = inputs.points(stations).to_crs("EPSG:5070")
    joined = gpd.sjoin_nearest(shapes, points[["station", "geometry"]], how="left")
    return joined.groupby(level=0)["station"].first()


def hazard_multipliers() -> pd.DataFrame:
    """Columns CFLD_<period>_<warming>_HM indexed by county FIPS (coastal counties only)."""
    current, projected = station_frequencies()
    stations = projected.drop_duplicates("station")[["station", "lat", "lon"]]
    stations = stations[stations["station"].isin(current.index)]
    nearest = nearest_station(stations)
    total = current.sum(axis=1)
    share = current.div(total.where(total > 0), axis=0)
    result = {}
    for warming, scenario in SCENARIOS.items():
        for period, decade in DECADES.items():
            rows = projected[(projected["scenario"] == scenario) & (projected["decade"] == decade)]
            future = rows.pivot_table(index="station", columns="severity", values="days")
            future = future.reindex(index=current.index, columns=list(SEVERITIES))
            with np.errstate(divide="ignore", invalid="ignore"):
                factor = future / current
            factor = factor.replace([np.inf, -np.inf], np.nan)
            station_hm = (factor.where(share > 0) * share).sum(axis=1, min_count=1)
            result[f"CFLD_{period}_{warming}_HM"] = nearest.map(station_hm)
    return pd.DataFrame(result)
