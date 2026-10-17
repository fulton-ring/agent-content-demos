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
CURRENT_DECADES = (2030,)
# Annual-chance weights: minor 50-100% (upper end, 1-year flood), moderate 2-10% (midpoint),
# major: midpoint of the 0-1% band.
ANNUAL_CHANCE = pd.Series({"minor": 1.0, "moderate": 0.06, "major": 0.005})


def saturate(days: pd.DataFrame) -> pd.DataFrame:
    """Convert flood days per year to a saturating annual frequency (probability-like)."""
    return 1.0 - np.exp(-days / 365.0)


def station_frequencies() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Current (2030 decade) and projected flood days per year."""
    tables = inputs.coastal_tables()
    projected = tables["htf_decadal"]
    base = projected[
        (projected["scenario"] == "intermediate") & (projected["decade"].isin(CURRENT_DECADES))
    ]
    current = base.pivot_table(index="station", columns="severity", values="days", aggfunc="mean")
    current = current.reindex(columns=list(SEVERITIES))
    return current, projected


def nearest_station(stations: pd.DataFrame) -> pd.Series:
    """Nearest station (by distance from the county centroid) for each coastal county."""
    counties = inputs.county_shapes()
    coastal = inputs.baseline()["CFLD_EALT"] > 0
    shapes = counties.loc[coastal[coastal].index].to_crs("EPSG:5070")
    shapes = shapes.copy()
    shapes["geometry"] = shapes.geometry.centroid
    points = inputs.points(stations).to_crs("EPSG:5070")
    joined = gpd.sjoin_nearest(shapes, points[["station", "geometry"]], how="left")
    return joined.groupby(level=0)["station"].first()


def hazard_multipliers() -> pd.DataFrame:
    """Columns CFLD_<period>_<warming>_HM indexed by county FIPS (coastal counties only)."""
    current_days, projected = station_frequencies()
    stations = projected.drop_duplicates("station")[["station", "lat", "lon"]]
    stations = stations[stations["station"].isin(current_days.index)]
    nearest = nearest_station(stations)
    current = saturate(current_days)[list(SEVERITIES)]
    weights = (current > 0).astype(float).mul(ANNUAL_CHANCE[list(SEVERITIES)], axis=1)
    total = weights.sum(axis=1)
    share = weights.div(total.where(total > 0), axis=0)
    result = {}
    for warming, scenario in SCENARIOS.items():
        for period, decade in DECADES.items():
            window = [decade - 10, decade, decade + 10]
            rows = projected[
                (projected["scenario"] == scenario) & (projected["decade"].isin(window))
            ]
            future_days = rows.pivot_table(
                index="station", columns="severity", values="days", aggfunc="mean"
            )
            future_days = future_days.reindex(index=current.index, columns=list(SEVERITIES))
            future = saturate(future_days)
            with np.errstate(divide="ignore", invalid="ignore"):
                factor = future / current.where(current > 0)
            station_hm = (factor.where(share > 0) * share).sum(axis=1, min_count=1)
            result[f"CFLD_{period}_{warming}_HM"] = nearest.map(station_hm)
    return pd.DataFrame(result)
