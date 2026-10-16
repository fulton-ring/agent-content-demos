"""Coastal flooding hazard multipliers.

Primary route: 187 NOAA gauges, return-period frequency adjustment from extreme water level
curves shifted by relative sea level rise. Falls back to the HTF-decadal method on failure.
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
ANNUAL_CHANCE = pd.Series({"minor": 1.0, "moderate": 0.06, "major": 0.005})
SUB_RPS = {"minor": (1.0, 2.0), "moderate": (10.0, 20.0, 50.0), "major": (100.0,)}
MIN_RP = 0.1


def saturate(days):
    return 1.0 - np.exp(-days / 365.0)


def station_frequencies():
    tables = inputs.coastal_tables()
    projected = tables["htf_decadal"]
    base = projected[
        (projected["scenario"] == "intermediate") & (projected["decade"].isin(CURRENT_DECADES))
    ]
    current = base.pivot_table(index="station", columns="severity", values="days", aggfunc="mean")
    current = current.reindex(columns=list(SEVERITIES))
    return current, projected


def nearest_station(stations):
    counties = inputs.county_shapes()
    coastal = inputs.baseline()["CFLD_EALT"] > 0
    shapes = counties.loc[coastal[coastal].index].to_crs("EPSG:5070")
    shapes = shapes.copy()
    shapes["geometry"] = shapes.geometry.centroid
    points = inputs.points(stations).to_crs("EPSG:5070")
    joined = gpd.sjoin_nearest(shapes, points[["station", "geometry"]], how="left")
    return joined.groupby(level=0)["station"].first()


def htf_hm() -> pd.DataFrame:
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
            rows = projected[(projected["scenario"] == scenario) & (projected["decade"] == decade)]
            future_days = rows.pivot_table(index="station", columns="severity", values="days")
            future_days = future_days.reindex(index=current.index, columns=list(SEVERITIES))
            future = saturate(future_days)
            with np.errstate(divide="ignore", invalid="ignore"):
                factor = future / current.where(current > 0)
            station_hm = (factor.where(share > 0) * share).sum(axis=1, min_count=1)
            result[f"CFLD_{period}_{warming}_HM"] = nearest.map(station_hm)
    return pd.DataFrame(result)


def _return_period_table(ewl):
    meta = {"station", "id", "name", "state", "noaa_id", "stationid"}
    rp_cols = {}
    for c in ewl.columns:
        lc = str(c).lower()
        if lc in meta or "lat" in lc or "lon" in lc or "name" in lc or "state" in lc:
            continue
        if not pd.api.types.is_numeric_dtype(ewl[c]):
            continue
        m = re.search(r"\d+\.?\d*", str(c).replace("_", ".", 0))
        if not m:
            continue
        val = float(m.group(0))
        if val > 0:
            rp_cols[c] = val
    if len(rp_cols) < 4:
        raise ValueError("cannot parse return periods")
    order = sorted(rp_cols, key=lambda c: rp_cols[c])
    rps = np.array([rp_cols[c] for c in order], dtype=float)
    return order, rps


def _slr_table(slp, scenario):
    cols = {str(c).lower(): c for c in slp.columns}
    scen_col = next(c for k, c in cols.items() if "scen" in k)
    dec_col = cols.get("decade") or next(c for k, c in cols.items() if "year" in k or "decade" in k)
    d = slp.copy()
    for k, c in cols.items():
        if "percent" in k or k == "quantile":
            vals = d[c]
            if pd.api.types.is_numeric_dtype(vals):
                target = 50 if vals.max() > 1 else 0.5
                d = d[np.isclose(vals, target)]
            else:
                d = d[vals.astype(str).str.lower().str.contains("med|50")]
    d = d[d[scen_col].astype(str).str.lower().str.strip() == scenario]
    skip = {"station", dec_col, scen_col}
    cand = [
        c for c in d.columns
        if c not in skip and pd.api.types.is_numeric_dtype(d[c])
        and "lat" not in str(c).lower() and "lon" not in str(c).lower()
        and "percent" not in str(c).lower() and str(c).lower() != "quantile"
    ]
    pref = [c for c in cand if "med" in str(c).lower() or "50" in str(c).lower()]
    val_col = (pref or cand)[0]
    out = d.pivot_table(index="station", columns=dec_col, values=val_col, aggfunc="mean")
    return out, str(val_col).lower()


def ewl_hm() -> pd.DataFrame:
    tables = inputs.coastal_tables()
    ewl = tables["extreme_water_levels"].copy()
    slp = tables["sea_level_projections"].copy()
    ewl = ewl.drop_duplicates("station").set_index("station", drop=False)
    order, rps = _return_period_table(ewl)
    logrp = np.log(rps)

    # station coordinates
    if {"lat", "lon"}.issubset(ewl.columns):
        coords = ewl[["station", "lat", "lon"]]
    elif {"lat", "lon"}.issubset(slp.columns):
        coords = slp.drop_duplicates("station")[["station", "lat", "lon"]]
    else:
        coords = tables["htf_decadal"].drop_duplicates("station")[["station", "lat", "lon"]]
    weights = ANNUAL_CHANCE[list(SEVERITIES)]
    share = weights / weights.sum()

    result = {}
    per_scen = {}
    for warming, scenario in SCENARIOS.items():
        table, vname = _slr_table(slp, scenario)
        scale = 0.01 if "cm" in vname or table.abs().stack().max() > 30 else 1.0
        per_scen[warming] = table * scale

    st_hm = {}
    for warming in SCENARIOS:
        table = per_scen[warming]
        for period, decade in DECADES.items():
            col = decade if decade in table.columns else None
            if col is None:
                raise ValueError("decade missing")
            vals = {}
            for st in ewl.index:
                if st not in table.index or pd.isna(table.at[st, col]):
                    continue
                levels = ewl.loc[st, order].astype(float).values
                ok = ~np.isnan(levels)
                if ok.sum() < 4:
                    continue
                lv = np.maximum.accumulate(levels[ok])
                lr = logrp[ok]
                rise = float(table.at[st, col])
                hm = 0.0
                for sev in SEVERITIES:
                    fafs = []
                    for rp in SUB_RPS[sev]:
                        z = np.interp(np.log(rp), lr, lv)
                        new_level = z - rise
                        if new_level <= lv[0]:
                            rp_new = MIN_RP
                        else:
                            rp_new = float(np.exp(np.interp(new_level, lv, lr)))
                            rp_new = max(rp_new, MIN_RP)
                        fafs.append(rp / rp_new)
                    hm += share[sev] * float(np.mean(fafs))
                vals[st] = hm
            st_hm[f"CFLD_{period}_{warming}_HM"] = pd.Series(vals)

    stations = coords[coords["station"].isin(st_hm["CFLD_MID_LOWER_HM"].index)]
    stations = stations.dropna()
    nearest = nearest_station(stations)
    for k, s in st_hm.items():
        result[k] = nearest.map(s)
    out = pd.DataFrame(result)
    if out.notna().sum().min() < 50:
        raise ValueError("too few counties")
    return out


def hazard_multipliers() -> pd.DataFrame:
    """Columns CFLD_<period>_<warming>_HM indexed by county FIPS (coastal counties only)."""
    try:
        return ewl_hm()
    except Exception:
        return htf_hm()
