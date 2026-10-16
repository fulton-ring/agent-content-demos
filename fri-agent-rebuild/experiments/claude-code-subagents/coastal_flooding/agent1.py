"""Coastal flooding hazard multipliers from NOAA extreme water levels and sea level rise.

FRI Technical Documentation, Section 4: each county takes the flood-frequency change of its
nearest of 187 NOAA tide gauges. Sub-types are defined by return period (minor 1-2 yr, moderate
10-50 yr, major 100 yr). For each gauge and sub-type, today's flood level z is read from the
return-level curve; the scenario's relative sea level rise r shifts the curve, so z has the return
period of the level z - r today. FAF = old return period / new return period. HM = sum over
sub-types of FAF x SubProportion.
"""

import geopandas as gpd
import numpy as np
import pandas as pd

from fri_rebuild import inputs

SCENARIOS = {"LOWER": "1.0 - MED", "HIGHER": "2.0 - MED"}
YEARS = {"MID": 2050, "LATE": 2100}
SUBTYPES = {"minor": (1, 2), "moderate": (10, 20, 30, 40, 50), "major": (100,)}
MIN_RP = 0.1


def return_levels() -> pd.DataFrame:
    """Return levels (m above MHHW), indexed by gauge, columns = return period in years."""
    table = inputs.coastal_tables()["extreme_water_levels"].set_index("St")
    levels = table.filter(regex=r"^\d+(\.\d+)?yrRL")
    levels.columns = [float(c.split("yr")[0]) for c in levels.columns]
    return levels.dropna(how="any")


def sea_level_rise(gauges: pd.DataFrame) -> pd.DataFrame:
    """Relative rise since 2000 (m) per gauge, scenario and period (NOAA ID, else nearest site)."""
    slr = inputs.coastal_tables()["sea_level_projections"]
    slr = slr[slr["Lat"].notna() | slr["NOAA ID"].notna()]
    out = {}
    for warming, label in SCENARIOS.items():
        rows = slr[slr["Scenario"] == label].dropna(subset=["Lat"])
        by_id = rows[rows["NOAA ID"].notna()].drop_duplicates("NOAA ID").set_index("NOAA ID")
        sites = rows.reset_index(drop=True)
        for period, year in YEARS.items():
            rise = (sites[f"RSL{year} (cm)"]) / 100.0
            values = {}
            for gauge, row in gauges.iterrows():
                if float(gauge) in by_id.index:
                    site = by_id.loc[float(gauge)]
                    values[gauge] = (site[f"RSL{year} (cm)"]) / 100
                else:
                    d = (sites["Lat"] - row["Latitude"]) ** 2 + (
                        (sites["Long"] - row["Longitude"]) * np.cos(np.radians(row["Latitude"]))
                    ) ** 2
                    values[gauge] = rise.iloc[int(d.values.argmin())]
            out[f"{period}_{warming}"] = pd.Series(values)
    return pd.DataFrame(out)


def new_return_period(levels: np.ndarray, rps: np.ndarray, z: float) -> float:
    """Return period whose level is z (log-linear interpolation, capped at the table's range)."""
    if z <= levels[0]:
        return rps[0]
    if z >= levels[-1]:
        slope = (np.log(rps[-1]) - np.log(rps[-6])) / (levels[-1] - levels[-6])
        return float(np.exp(np.log(rps[-1]) + slope * (z - levels[-1])))
    return float(np.exp(np.interp(z, levels, np.log(rps))))


def gauge_hm() -> pd.DataFrame:
    levels = return_levels()
    meta = inputs.coastal_tables()["extreme_water_levels"].set_index("St").loc[levels.index]
    rise = sea_level_rise(meta[["Latitude", "Longitude"]])
    rps = np.array(levels.columns, dtype=float)
    freq = pd.Series({k: np.mean(1 / np.array(v, dtype=float)) for k, v in SUBTYPES.items()})
    share = freq / freq.sum()
    result = {}
    for col in rise.columns:
        hm = {}
        for gauge in levels.index:
            curve = np.maximum.accumulate(levels.loc[gauge].values)
            total = 0.0
            for sub, periods in SUBTYPES.items():
                old = np.array(periods, dtype=float)
                z = np.interp(np.log(old), np.log(rps), curve)
                new = np.array([new_return_period(curve, rps, zi - rise.loc[gauge, col]) for zi in z])
                faf = (1 / new).sum() / (1 / old).sum()
                total += faf * share[sub]
            hm[gauge] = total
        result[f"CFLD_{col.split('_')[0]}_{col.split('_')[1]}_HM"] = pd.Series(hm)
    return pd.DataFrame(result), meta


def nearest_gauge(gauges: pd.DataFrame) -> pd.Series:
    counties = inputs.county_shapes()
    coastal = inputs.baseline()["CFLD_EALT"] > 0
    shapes = counties.loc[coastal[coastal].index].to_crs("EPSG:5070")
    stations = gauges.reset_index().rename(columns={"St": "station", "Latitude": "lat", "Longitude": "lon"})
    points = inputs.points(stations).to_crs("EPSG:5070")
    joined = gpd.sjoin_nearest(shapes, points[["station", "geometry"]], how="left")
    return joined.groupby(level=0)["station"].first()


def hazard_multipliers() -> pd.DataFrame:
    """Columns CFLD_<period>_<warming>_HM indexed by county FIPS (coastal counties only)."""
    station_hm, meta = gauge_hm()
    nearest = nearest_gauge(meta[["Latitude", "Longitude"]])
    return pd.DataFrame({c: nearest.map(station_hm[c]) for c in station_hm.columns})
