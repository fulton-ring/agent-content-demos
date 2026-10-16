"""Coastal flooding hazard multipliers from NOAA high-tide-flooding projections.

FRI Technical Documentation, Section 4: each county takes the projected minor, moderate and
major high-tide-flooding frequencies of its nearest tide gauge. For each sub-type, the frequency
adjustment factor is projected / current frequency, and the county HM is the sum over sub-types
of that factor times the sub-type's share of the county's coastal flooding EAL.
"""

import re

import geopandas as gpd
import numpy as np
import pandas as pd

from fri_rebuild import inputs

SEVERITIES = ("minor", "moderate", "major")
SCENARIOS = {"LOWER": "intermediate", "HIGHER": "high"}
DECADES = {"MID": 2050, "LATE": 2100}
CURRENT_DECADES = (2030,)
# Fixed annual-chance weights, used only where a gauge has no extreme-water-level curve.
ANNUAL_CHANCE = pd.Series({"minor": 1.0, "moderate": 0.06, "major": 0.005})


def saturate(days):
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


def curve_annual_chance() -> pd.DataFrame:
    """Per-gauge annual chance of exceeding the minor/moderate/major thresholds today.

    Uses the extreme water level return-level curve (m above MHHW) and the flood thresholds.
    """
    tables = inputs.coastal_tables()
    ewl = tables["extreme_water_levels"]
    thr = tables["flood_thresholds"].copy()
    rl_cols = []
    rps = []
    for col in ewl.columns:
        m = re.match(r"^\s*([0-9.]+)yrRL", str(col))
        if m:
            rl_cols.append(col)
            rps.append(float(m.group(1)))
    order = np.argsort(rps)
    rl_cols = [rl_cols[i] for i in order]
    log_rp = np.log(np.array(rps)[order])
    levels = ewl[rl_cols].to_numpy(dtype=float)
    ids = ewl["St"].astype(int).astype(str).to_numpy()
    thr["station"] = thr["station"].astype(str)
    thr = thr.set_index("station")
    out = {}
    for k, sid in enumerate(ids):
        if sid not in thr.index:
            continue
        row = levels[k]
        ok = np.isfinite(row)
        if ok.sum() < 3:
            continue
        lv = np.maximum.accumulate(row[ok])
        lr = log_rp[ok]
        vals = {}
        for sev in SEVERITIES:
            z = thr.loc[sid, f"{sev}_m_above_mhhw"]
            if not np.isfinite(z):
                vals[sev] = np.nan
                continue
            rate = np.exp(-np.interp(z, lv, lr))
            vals[sev] = 1.0 - np.exp(-rate)
        out[sid] = vals
    return pd.DataFrame.from_dict(out, orient="index").reindex(columns=list(SEVERITIES))


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
    chance = curve_annual_chance().reindex(current.index.astype(str))
    chance.index = current.index
    fixed = pd.DataFrame(
        np.tile(ANNUAL_CHANCE[list(SEVERITIES)].to_numpy(), (len(current), 1)),
        index=current.index,
        columns=list(SEVERITIES),
    )
    chance = chance.where(chance.notna() & (chance > 0), fixed)
    weights = (current > 0).astype(float) * chance
    total = weights.sum(axis=1)
    share = weights.div(total.where(total > 0), axis=0)
    result = {}
    for warming, scenario in SCENARIOS.items():
        for period, decade in DECADES.items():
            rows = projected[(projected["scenario"] == scenario) & (projected["decade"] == decade)]
            future_days = rows.pivot_table(index="station", columns="severity", values="days")
            future_days = future_days.reindex(index=current.index, columns=list(SEVERITIES))
            future = saturate(future_days)
            with np.errstate(divide="ignore", invalid="ignore"):
                factor = future / current.where(current > 0)
            station_hm = (factor.where(share > 0) * share).sum(axis=1, min_count=1)
            result[f"CFLD_{period}_{warming}_HM"] = nearest.map(station_hm)
    return pd.DataFrame(result)
