"""Coastal flooding hazard multipliers from NOAA extreme water level curves + sea level rise.

FRI Technical Documentation, Section 4: each county takes the projected minor, moderate and
major flooding frequencies of its nearest tide gauge (187 gauges). Sub-types are defined by
return period (minor 1-2 yr, moderate 10-50 yr, major 100 yr). For each gauge and sub-type the
frequency adjustment factor is the exceedance rate of today's flood level after raising mean sea
level by the scenario's relative rise, divided by today's rate. HM = sum SubFAF x SubProportion.
"""

import re

import geopandas as gpd
import numpy as np
import pandas as pd

from fri_rebuild import inputs

SEVERITIES = ("minor", "moderate", "major")
SCENARIOS = {"LOWER": 1.0, "HIGHER": 2.0}  # GMSL by 2100 in metres (Intermediate, High)
YEARS = {"MID": 2050, "LATE": 2100}
RETURN_PERIODS = {
    "minor": [1.0, 1.5, 2.0],
    "moderate": [10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0],
    "major": [100.0],
}
ANNUAL_CHANCE = {"minor": 1.0, "moderate": 0.06, "major": 0.005}
MAX_RATE = 10.0  # events per year (table's shortest return period is 0.1 yr)


def return_level_curves() -> dict:
    """Per gauge: (return periods, levels in m above MHHW) from the extreme water level table."""
    ewl = inputs.coastal_tables()["extreme_water_levels"]
    cols = {}
    for c in ewl.columns:
        m = re.match(r"^([0-9.]+)yrRL", str(c))
        if m:
            cols[c] = float(m.group(1))
    ordered = sorted(cols, key=lambda c: cols[c])
    rps = np.array([cols[c] for c in ordered])
    curves = {}
    for _, row in ewl.iterrows():
        lv = row[ordered].to_numpy(dtype=float)
        ok = np.isfinite(lv)
        if ok.sum() < 5:
            continue
        lv = np.maximum.accumulate(lv[ok])
        curves[int(row["St"])] = (rps[ok], lv, float(row["Latitude"]), float(row["Longitude"]))
    return curves


def log_rate(level, rps, lv):
    """Log annual exceedance rate at a level; capped at MAX_RATE, extrapolated above the table."""
    lr = -np.log(rps)
    if level <= lv[0]:
        return np.log(MAX_RATE)
    if level <= lv[-1]:
        return min(np.interp(level, lv, lr), np.log(MAX_RATE))
    i = max(len(lv) - 2, 0)
    j = np.searchsorted(rps, 50.0)
    j = min(j, len(lv) - 2)
    i = j
    dl = max(lv[-1] - lv[i], 1e-6)
    slope = (lr[-1] - lr[i]) / dl
    return lr[-1] + slope * (level - lv[-1])


def parse_scenarios(slr: pd.DataFrame) -> pd.DataFrame:
    pat = re.compile(r"^\s*([0-9.]+)\s*-\s*([A-Za-z]+)")
    meters, kinds = [], []
    for s in slr["Scenario"].astype(str):
        m = pat.match(s)
        meters.append(float(m.group(1)) if m else np.nan)
        kinds.append(m.group(2).upper() if m else "")
    out = slr.copy()
    out["gmsl_m"] = meters
    out["kind"] = kinds
    return out


def station_rises(curves: dict) -> dict:
    """Relative sea level rise (m) per gauge, scenario and period (median projections)."""
    slr = parse_scenarios(inputs.coastal_tables()["sea_level_projections"])
    slr = slr[slr["NOAA ID"].notna() & slr["Lat"].notna() & slr["Long"].notna()]
    slr = slr[slr["kind"] == "MED"]
    rises = {}
    for warming, gm in SCENARIOS.items():
        sub = slr[np.isclose(slr["gmsl_m"], gm)]
        ids = sub["NOAA ID"].astype(float).astype(int).to_numpy()
        lat = sub["Lat"].to_numpy(dtype=float)
        lon = sub["Long"].to_numpy(dtype=float)
        for st, (_, _, la, lo) in curves.items():
            hit = np.where(ids == st)[0]
            if len(hit):
                k = hit[0]
            else:
                d = (lat - la) ** 2 + ((lon - lo) * np.cos(np.radians(la))) ** 2
                k = int(np.argmin(d))
            for period, year in YEARS.items():
                rises[(st, warming, period)] = float(sub.iloc[k][f"RSL{year}"]) / 100.0
    return rises


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
    """Columns CFLD_<period>_<warming>_HM indexed by county FIPS (coastal counties only)."""
    curves = return_level_curves()
    rises = station_rises(curves)
    stations = pd.DataFrame(
        [{"station": st, "lat": v[2], "lon": v[3]} for st, v in curves.items()]
    )
    nearest = nearest_station(stations)
    total = sum(ANNUAL_CHANCE.values())
    share = {s: ANNUAL_CHANCE[s] / total for s in SEVERITIES}
    result = {}
    for warming in SCENARIOS:
        for period in YEARS:
            hm = {}
            for st, (rps, lv, _, _) in curves.items():
                rise = rises[(st, warming, period)]
                total_hm = 0.0
                for sev in SEVERITIES:
                    fafs = []
                    for rp in RETURN_PERIODS[sev]:
                        z = float(np.interp(rp, rps, lv))
                        old = -np.log(rp)
                        new = log_rate(z - rise, rps, lv)
                        fafs.append(np.exp(new - old))
                    total_hm += share[sev] * float(np.mean(fafs))
                hm[st] = total_hm
            result[f"CFLD_{period}_{warming}_HM"] = nearest.map(pd.Series(hm))
    return pd.DataFrame(result)
