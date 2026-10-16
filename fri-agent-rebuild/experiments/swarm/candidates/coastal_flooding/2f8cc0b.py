"""Coastal flooding hazard multipliers from return-level curves plus sea level rise (187 gauges).

FRI Technical Documentation, Section 4: each county inherits the nearest tide gauge's projected
minor/moderate/major flood frequency. Here the sub-types are return-period bands of the ITF
extreme water level table; sea level rise shifts the level, giving the projected frequency.
"""

import re

import geopandas as gpd
import numpy as np
import pandas as pd

from fri_rebuild import inputs

SEVERITIES = ("minor", "moderate", "major")
SCENARIOS = {"LOWER": "1.0", "HIGHER": "2.0"}
YEAR_COL = {"MID": "RSL2050 (cm)", "LATE": "RSL2100 (cm)"}
BANDS = {
    "minor": [1.0, 1.5, 2.0],
    "moderate": [10.0, 20.0, 30.0, 40.0, 50.0],
    "major": [100.0],
}
ANNUAL_CHANCE = pd.Series({"minor": 1.0, "moderate": 0.06, "major": 0.005})
MIN_RP = 0.1


def wrap_lon(lon):
    return ((np.asarray(lon, dtype=float) + 180.0) % 360.0) - 180.0


def return_level_curves(ewl: pd.DataFrame):
    """Return (rps, levels[n_gauges, n_rps]) with levels monotone increasing in rp."""
    cols = {}
    for c in ewl.columns:
        m = re.match(r"^([0-9.]+)yrRL", str(c))
        if m:
            cols[float(m.group(1))] = c
    rps = np.array(sorted(cols))
    levels = np.column_stack([ewl[cols[r]].to_numpy(dtype=float) for r in rps])
    return rps, levels


def frequency(rps, lev_row, z):
    """Events per year of water level z (m above MHHW) given a gauge's return level curve."""
    ok = np.isfinite(lev_row)
    r = rps[ok]
    lv = np.maximum.accumulate(lev_row[ok])
    lv = lv + np.arange(len(lv)) * 1e-9
    z = np.asarray(z, dtype=float)
    logrp = np.interp(z, lv, np.log(r))
    # extrapolate above the table using the slope of the last few points
    top = z > lv[-1]
    if top.any():
        slope = (np.log(r[-1]) - np.log(r[-6])) / (lv[-1] - lv[-6])
        logrp = np.where(top, np.log(r[-1]) + slope * (z - lv[-1]), logrp)
    rp = np.maximum(np.exp(logrp), MIN_RP)
    return 1.0 / rp


def gauge_rise(ewl: pd.DataFrame, slr: pd.DataFrame, tag: str, col: str) -> np.ndarray:
    """Median relative rise (m) at the SLR site nearest each EWL gauge."""
    sc = slr["Scenario"].astype(str).str.strip()
    rows = slr[sc.str.startswith(tag) & sc.str.upper().str.endswith("MED")]
    rows = rows[rows["Lat"].notna() & rows["Long"].notna() & rows[col].notna()]
    slat = rows["Lat"].to_numpy(dtype=float)
    slon = wrap_lon(rows["Long"])
    rise = rows[col].to_numpy(dtype=float) / 100.0
    out = np.empty(len(ewl))
    glat = ewl["Latitude"].to_numpy(dtype=float)
    glon = wrap_lon(ewl["Longitude"])
    for i in range(len(ewl)):
        d = (slat - glat[i]) ** 2 + ((slon - glon[i]) * np.cos(np.radians(glat[i]))) ** 2
        out[i] = rise[np.argmin(d)]
    return out


def nearest_station(stations: pd.DataFrame) -> pd.Series:
    counties = inputs.county_shapes()
    coastal = inputs.baseline()["CFLD_EALT"] > 0
    shapes = counties.loc[coastal[coastal].index].to_crs("EPSG:5070")
    shapes = shapes.copy()
    shapes["geometry"] = shapes.geometry.centroid
    points = inputs.points(stations).to_crs("EPSG:5070")
    joined = gpd.sjoin_nearest(shapes, points[["station", "geometry"]], how="left")
    return joined.groupby(level=0)["station"].first()


def hazard_multipliers() -> pd.DataFrame:
    tables = inputs.coastal_tables()
    ewl = tables["extreme_water_levels"].reset_index(drop=True)
    slr = tables["sea_level_projections"]
    rps, levels = return_level_curves(ewl)
    stations = pd.DataFrame(
        {
            "station": ewl["St"].astype(str).to_numpy(),
            "lat": ewl["Latitude"].to_numpy(dtype=float),
            "lon": ewl["Longitude"].to_numpy(dtype=float),
        }
    )
    nearest = nearest_station(stations)

    weights = ANNUAL_CHANCE[list(SEVERITIES)]
    share = weights / weights.sum()

    # current band frequencies: events per year at each band's return levels (year 2000)
    result = {}
    for warming, tag in SCENARIOS.items():
        for period, col in YEAR_COL.items():
            rise = gauge_rise(ewl, slr, tag, col)
            hm = np.zeros(len(ewl))
            for sev in SEVERITIES:
                old_f = np.zeros(len(ewl))
                new_f = np.zeros(len(ewl))
                for rp in BANDS[sev]:
                    zs = np.array([np.interp(np.log(rp), np.log(rps[np.isfinite(levels[i])]),
                                             levels[i][np.isfinite(levels[i])])
                                   for i in range(len(ewl))])
                    for i in range(len(ewl)):
                        old_f[i] += 1.0 / rp
                        new_f[i] += frequency(rps, levels[i], zs[i] - rise[i])
                hm += (new_f / old_f) * share[sev]
            station_hm = pd.Series(hm, index=stations["station"].to_numpy())
            result[f"CFLD_{period}_{warming}_HM"] = nearest.map(station_hm)
    return pd.DataFrame(result)
