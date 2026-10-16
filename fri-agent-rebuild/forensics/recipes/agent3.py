"""agent3 recipe: NOAA flood thresholds x extreme water level curve x sea level rise.

Sub-type current frequency = annual exceedance frequency of the NOAA minor/moderate/major
threshold (m above MHHW) read from the gauge's return-level curve (log-linear beyond the table).
Future frequency = same at (threshold - median relative SLR), capped at CAP events/year.
SLR taken from the nearest projection grid cell to the gauge (by lat/lon).
"""

import numpy as np

from fri_rebuild import coastal, forensics

SCEN = ["1.0 - MED", "2.0 - MED"]  # LOWER, HIGHER scenario labels
CAP = 10.0  # events per year (0.1-year return period, shortest in the table)
USE_ID = True  # use the NOAA-ID matched projection when the gauge has one
EXN = 6
SHIFT = 0.0  # metres added to the threshold for the current frequency
SHIFT_FUT = 0.06  # metres: EMPIRICAL global offset (rise effectively 6 cm smaller); meaning unknown, fitted to FEMA values
STEP = None  # None, floor, ceil, near: read the return period off a table row instead of interpolating
CLAMP_TOP = False
FILL = "nearest"  # None, "median" or "nearest": gauges without NOAA thresholds get the median threshold across gauges
INTERP = "logrp"  # interpolation between table points: logrp, rp, freq
LOW_EXTRAP = True  # extrapolate log-linearly below the 0.1-year level, then cap
OFFSETS = ()
RISE_SCALE = 1.0  # multiplier on the rise
Y_MID = 2050  # year of the mid-century projection
Y_LATE = 2100
ADD_MID = 0.0  # cm added to the 2050 rise
ADD_LATE = 0.0  # cm added to the 2100 rise
BASE = None
_cache = {}


def _setup():
    if _cache:
        return _cache
    t = coastal.tables()
    _cache["t"] = t
    _cache["cols"], _cache["per"] = forensics.return_periods(t["extreme_water_levels"])
    return _cache


def _rises(row, t):
    s = t["sea_level_projections"]
    lat, lon = row.Latitude, row.Longitude
    if USE_ID:
        m = s[s["NOAA ID"] == float(row.St)]
        if not m.empty:
            lat, lon = m.iloc[0].Lat, m.iloc[0].Long
    c = np.cos(np.radians(lat))
    d = (s.Lat - lat) ** 2 + np.minimum(((s.Long - lon) * c) ** 2, ((s.Long - lon - 360) * c) ** 2)
    i = d.idxmin()
    r = s[(s.Lat == s.loc[i, "Lat"]) & (s.Long == s.loc[i, "Long"])].set_index("Scenario")
    out = []
    for sc in SCEN:
        pass
    vals = {}
    for sc in SCEN:
        for y in (2050, 2100):
            yy = Y_MID if y == 2050 else Y_LATE
            xs = np.arange(2020, 2151, 10)
            ys = [r.loc[sc, f"RSL{x} (cm)"] for x in xs]
            v = float(np.interp(yy, xs, ys)) / 100
            if OFFSETS:
                v += sum(r.loc[sc, c] for c in OFFSETS) / 100
            v += (ADD_MID if y == 2050 else ADD_LATE) / 100
            if BASE:
                v -= r.loc[sc, BASE] / 100
            vals[(sc, y)] = v * RISE_SCALE
    return vals


def freq(z, lv, per):
    if STEP:
        if z <= lv[0] and STEP != "ceil":
            return CAP
        if z >= lv[-1]:
            if CLAMP_TOP:
                return 1 / per[-1]
        else:
            if STEP == "floor":
                j = np.searchsorted(lv, z, side="right") - 1
            elif STEP == "ceil":
                j = np.searchsorted(lv, z, side="left")
            else:
                j = int(np.argmin(np.abs(lv - z)))
            return min(CAP, 1 / per[max(j, 0)])
    if z <= lv[0]:
        if not LOW_EXTRAP:
            return CAP
        sl = (np.log(per[1]) - np.log(per[0])) / (lv[1] - lv[0])
        return min(CAP, float(np.exp(-(np.log(per[0]) + sl * (z - lv[0])))))
    if z >= lv[-1]:
        sl = (np.log(per[-1]) - np.log(per[-EXN])) / (lv[-1] - lv[-EXN])
        return min(CAP, float(np.exp(-(np.log(per[-1]) + sl * (z - lv[-1])))))
    if INTERP == "logrp":
        return min(CAP, float(np.exp(-np.interp(z, lv, np.log(per)))))
    if INTERP == "rp":
        return min(CAP, float(1 / np.interp(z, lv, per)))
    return min(CAP, float(np.interp(z, lv, 1 / per)))


def gauge_factors(gauge):
    c = _setup()
    t, cols, per = c["t"], c["cols"], c["per"]
    e = t["extreme_water_levels"]
    row = e[e.St.astype(str) == gauge]
    th = t["flood_thresholds"]
    th = th[th.station.astype(str) == gauge]
    if row.empty or th.empty:
        return None
    T = th.iloc[0, 1:].to_numpy(float)
    if np.isnan(T).any():
        if not FILL:
            return None
        allT = t["flood_thresholds"].iloc[:, 1:].to_numpy(float)
        if FILL == "median":
            T = np.nanmedian(allT, axis=0)
        else:  # nearest gauge (by lat/lon) that has NOAA thresholds
            have = t["flood_thresholds"].dropna()
            ids = set(have.station.astype(str))
            e2 = e[e.St.astype(str).isin(ids)]
            c = np.cos(np.radians(row.iloc[0].Latitude))
            d = (e2.Latitude - row.iloc[0].Latitude) ** 2 + ((e2.Longitude - row.iloc[0].Longitude) * c) ** 2
            nid = str(e2.loc[d.idxmin(), "St"])
            T = have[have.station.astype(str) == nid].iloc[0, 1:].to_numpy(float)
    row = row.iloc[0]
    lv = np.maximum.accumulate(row[cols].to_numpy(float))
    r = _rises(row, t)
    out = []
    for z in T:
        p0 = freq(z + SHIFT, lv, per)
        z = z + SHIFT_FUT
        out.append(
            [
                freq(z - r[(SCEN[0], 2050)], lv, per) / p0,
                freq(z - r[(SCEN[1], 2050)], lv, per) / p0,
                freq(z - r[(SCEN[0], 2100)], lv, per) / p0,
                freq(z - r[(SCEN[1], 2100)], lv, per) / p0,
            ]
        )
    return np.array(out)
