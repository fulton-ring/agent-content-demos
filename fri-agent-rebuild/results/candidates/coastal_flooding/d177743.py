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
# Default annual-chance weights: minor 50-100% (upper end, 1-year flood), moderate 2-10%
# (midpoint), major: midpoint of the 0-1% band.
ANNUAL_CHANCE = pd.Series({"minor": 1.0, "moderate": 0.06, "major": 0.005})
# Documented return-period bands (years) used to bound each gauge's threshold return period.
RP_BANDS = {"minor": (1.0, 2.0), "moderate": (10.0, 50.0)}


def saturate(days):
    """Convert flood days per year to a saturating annual frequency (probability-like)."""
    return 1.0 - np.exp(-days / 365.0)


def gauge_weights() -> pd.DataFrame:
    """Per-gauge annual-chance weights from flood-threshold return periods (EWL curves)."""
    tables = inputs.coastal_tables()
    ewl = tables["extreme_water_levels"]
    thr = tables["flood_thresholds"].copy()
    thr["station"] = thr["station"].astype(str)
    thr = thr.set_index("station")
    level_cols = {}
    for col in ewl.columns:
        m = re.match(r"^(\d+(?:\.\d+)?)yrRL", str(col))
        if m:
            level_cols[col] = float(m.group(1))
    cols = sorted(level_cols, key=lambda c: level_cols[c])
    rps = np.array([level_cols[c] for c in cols])
    logrp = np.log(rps)
    out = {}
    for _, row in ewl.iterrows():
        sid = str(row["St"])
        if sid not in thr.index:
            continue
        levels = row[cols].to_numpy(dtype=float)
        ok = ~np.isnan(levels)
        if ok.sum() < 3:
            continue
        lv = np.maximum.accumulate(levels[ok])
        lr = logrp[ok]
        weights = {}
        for sev in ("minor", "moderate"):
            z = thr.loc[sid, f"{sev}_m_above_mhhw"]
            if np.isnan(z):
                continue
            rp = float(np.exp(np.interp(z, lv, lr)))
            lo, hi = RP_BANDS[sev]
            rp = min(max(rp, lo), hi)
            weights[sev] = 1.0 / rp
        out[sid] = weights
    return pd.DataFrame.from_dict(out, orient="index")


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
    # Per-gauge weights (bounded to documented bands); defaults where a gauge has no EWL entry.
    gw = gauge_weights()
    w = pd.DataFrame(
        {sev: ANNUAL_CHANCE[sev] for sev in SEVERITIES}, index=current.index, dtype=float
    )
    for sev in ("minor", "moderate"):
        if sev in gw.columns:
            mapped = pd.Series(current.index.astype(str), index=current.index).map(gw[sev])
            w[sev] = mapped.fillna(ANNUAL_CHANCE[sev])
    weights = (current > 0).astype(float) * w[list(SEVERITIES)]
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
