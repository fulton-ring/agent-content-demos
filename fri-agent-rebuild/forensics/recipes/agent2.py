"""Agent 2: sea-level-input variants of the baseline (knobs read from env for sweeping)."""

import os

import numpy as np

from fri_rebuild import coastal, forensics

OPT = {k: os.environ.get(k, d) for k, d in dict(
    LOW="1.0 - MED", HIGH="2.0 - MED", BASE="0", FALL="none", CAP="1").items()}
SUB_TYPES = forensics.SUB_TYPES
YEARS = forensics.YEARS


def _rise_rows(tables, gauge, lat, lon):
    rt = tables["sea_level_projections"]
    own = rt[rt["NOAA ID"] == float(gauge)]
    if not own.empty:
        return own
    mode = OPT["FALL"]
    if mode == "none":
        return None
    if mode == "nearest_noaa":
        pool = rt[rt["NOAA ID"].notna() & (rt["NOAA ID"] > 0)]
    elif mode == "grid":
        pool = rt[rt["Lat"].notna()]
    else:  # any
        pool = rt[rt["Lat"].notna() | (rt["NOAA ID"] > 0)]
    plat = pool["Lat"].fillna(0).to_numpy()
    plon = pool["Long"].fillna(0).to_numpy()
    if mode == "nearest_noaa":
        ws = tables.setdefault("_ws", None)
        e = tables["extreme_water_levels"]
        m = e.set_index(e["St"].astype(int))
        ids = pool["NOAA ID"].astype(int).to_numpy()
        ok = np.array([i in m.index for i in ids])
        plat = np.where(ok, [m["Latitude"].get(i, np.nan) for i in ids], np.nan)
        plon = np.where(ok, [m["Longitude"].get(i, np.nan) for i in ids], np.nan)
    d = (plat - lat) ** 2 + ((plon - lon) * np.cos(np.radians(lat))) ** 2
    d = np.where(np.isnan(d), np.inf, d)
    best = pool.iloc[int(np.argmin(d))]
    if mode == "grid":
        return pool[pool["RSL GridNum"] == best["RSL GridNum"]]
    return pool[pool["NOAA ID"] == best["NOAA ID"]]


def gauge_factors(gauge):
    tables = coastal.tables()
    curves = tables["extreme_water_levels"]
    columns, periods = forensics.return_periods(curves)
    row = curves[curves["St"].astype(str) == gauge]
    if row.empty:
        return None
    rises = _rise_rows(tables, gauge, float(row["Latitude"].iloc[0]), float(row["Longitude"].iloc[0]))
    if rises is None or rises.empty:
        return None
    levels = np.maximum.accumulate(row[columns].to_numpy(float)[0])
    base = OPT["BASE"]
    out = []
    for return_list in SUB_TYPES.values():
        today = [np.interp(np.log(rp), np.log(periods), levels) for rp in return_list]
        current = np.mean([1 / rp for rp in return_list])
        vec = []
        for year in YEARS.values():
            for scen in (OPT["LOW"], OPT["HIGH"]):
                r = rises[rises["Scenario"] == scen].iloc[0]
                rise = r[f"RSL{year} (cm)"]
                if base == "2005":
                    rise = rise - r["RSL2020 (cm)"] * 0 + r["Offset 2000 to 2005 (cm)"]
                elif base == "2020":
                    rise = rise - r["RSL2020 (cm)"]
                rise /= 100
                fut = np.mean([forensics.exceedance_frequency(z - rise, levels, periods, OPT["CAP"] == "1") for z in today])
                vec.append(fut / current)
        out.append(vec)
    return np.array(out)
