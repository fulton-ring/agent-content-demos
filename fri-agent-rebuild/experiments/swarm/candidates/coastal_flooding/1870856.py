"""Coastal flooding hazard multipliers from extreme-water-level return periods and SLR.

For each of the 187 NOAA gauges, sub-type (minor 1-2yr, moderate 10-50yr, major 100yr) flood
levels are raised by relative sea level rise; the frequency adjustment factor is old return
period / new return period of the same water level. HM = sum of FAF x SubProportion.
"""

import re

import geopandas as gpd
import numpy as np
import pandas as pd

from fri_rebuild import inputs

SEVERITIES = ("minor", "moderate", "major")
BAND_RPS = {
    "minor": (1.0, 1.5, 2.0),
    "moderate": (10.0, 20.0, 30.0, 40.0, 50.0),
    "major": (100.0,),
}
SCENARIO_LABEL = {"LOWER": "1.0 - MED", "HIGHER": "2.0 - MED"}
DECADES = {"MID": 2050, "LATE": 2100}
ANNUAL_CHANCE = pd.Series({"minor": 1.0, "moderate": 0.06, "major": 0.005})


def rise_at_gauges(slr: pd.DataFrame, gauges: pd.DataFrame, label: str, year: int) -> np.ndarray:
    """Relative sea level rise (m) at the nearest SLR site for each gauge."""
    col = f"RSL{year} (cm)"
    sub = slr[slr["Scenario"].astype(str).str.strip() == label]
    sub = sub[sub["Lat"].notna() & sub["Long"].notna() & sub[col].notna()]
    lat = sub["Lat"].to_numpy(float)
    lon = sub["Long"].to_numpy(float)
    vals = sub[col].to_numpy(float) / 100.0
    out = np.zeros(len(gauges))
    for k, (glat, glon) in enumerate(zip(gauges["lat"], gauges["lon"])):
        d = (lat - glat) ** 2 + ((lon - glon) * np.cos(np.radians(glat))) ** 2
        out[k] = vals[int(np.argmin(d))]
    return out


def gauge_multipliers() -> tuple[pd.DataFrame, pd.DataFrame]:
    tables = inputs.coastal_tables()
    ewl = tables["extreme_water_levels"].reset_index(drop=True)
    slr = tables["sea_level_projections"]
    rp_cols = {}
    for c in ewl.columns:
        m = re.match(r"^(\d+(?:\.\d+)?)yrRL", str(c))
        if m:
            rp_cols[float(m.group(1))] = c
    rps = np.array(sorted(rp_cols))
    levels = ewl[[rp_cols[r] for r in rps]].to_numpy(float)
    gauges = pd.DataFrame(
        {"station": ewl["St"].to_numpy(), "lat": ewl["Latitude"].to_numpy(float),
         "lon": ewl["Longitude"].to_numpy(float)}
    )
    ok = np.zeros(len(gauges), dtype=bool)
    curves = {}
    for i in range(len(gauges)):
        valid = np.isfinite(levels[i])
        if valid.sum() < 10 or not np.isfinite(gauges.loc[i, "lat"]):
            continue
        x = np.maximum.accumulate(levels[i][valid])
        curves[i] = (x, np.log(rps[valid]), rps[valid][0])
        ok[i] = True
    result = pd.DataFrame(index=range(len(gauges)))
    for warming, label in SCENARIO_LABEL.items():
        for period, year in DECADES.items():
            rise = rise_at_gauges(slr, gauges, label, year)
            hm = np.full(len(gauges), np.nan)
            for i, (x, lrp, rp_min) in curves.items():
                num = 0.0
                for sev in SEVERITIES:
                    fafs = []
                    for r0 in BAND_RPS[sev]:
                        z = np.interp(np.log(r0), lrp, x)
                        z2 = z - rise[i]
                        if z2 <= x[0]:
                            rate = 1.0 / rp_min
                        else:
                            rate = float(np.exp(-np.interp(z2, x, lrp)))
                        fafs.append(r0 * rate)
                    num += np.mean(fafs) * ANNUAL_CHANCE[sev]
                hm[i] = num / ANNUAL_CHANCE.sum()
            result[f"CFLD_{period}_{warming}_HM"] = hm
    result.index = gauges["station"].to_numpy()
    return result[ok], gauges[ok]


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
    station_hm, gauges = gauge_multipliers()
    stations = gauges[["station", "lat", "lon"]].drop_duplicates("station")
    nearest = nearest_station(stations)
    result = {}
    for col in station_hm.columns:
        result[col] = nearest.map(station_hm[col])
    return pd.DataFrame(result)
