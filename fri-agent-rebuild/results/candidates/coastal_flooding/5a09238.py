"""Coastal flooding hazard multipliers.

Primary route: 187-gauge return-period frequency adjustment factors (extreme water levels plus
sea level rise). Fallback: NOAA high-tide-flooding projections at 110 gauges.
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
OLD_RP = {"minor": 1.0, "moderate": 22.0, "major": 100.0}


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


def nearest_station(stations: pd.DataFrame) -> pd.Series:
    counties = inputs.county_shapes()
    coastal = inputs.baseline()["CFLD_EALT"] > 0
    shapes = counties.loc[coastal[coastal].index].to_crs("EPSG:5070")
    shapes = shapes.copy()
    shapes["geometry"] = shapes.geometry.centroid
    points = inputs.points(stations).to_crs("EPSG:5070")
    joined = gpd.sjoin_nearest(shapes, points[["station", "geometry"]], how="left")
    return joined.groupby(level=0)["station"].first()


def baseline_method() -> pd.DataFrame:
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


def rp_columns(df):
    out = {}
    for c in df.columns:
        if c in ("station", "lat", "lon", "name", "state"):
            continue
        m = re.findall(r"\d+\.?\d*", str(c))
        if not m:
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        out[c] = float(m[0])
    return out


def return_period_hm() -> pd.DataFrame:
    tables = inputs.coastal_tables()
    ewl = tables["extreme_water_levels"].copy()
    slr = tables["sea_level_projections"].copy()
    if "station" not in ewl.columns:
        ewl = ewl.reset_index()
    rpc = rp_columns(ewl)
    cols = sorted(rpc, key=lambda c: rpc[c])
    rps = np.array([rpc[c] for c in cols])
    ewl = ewl.drop_duplicates("station").set_index("station")
    levels = ewl[cols].astype(float)
    levels = levels[levels.notna().sum(axis=1) >= 3]
    # sea level rise table: find value column
    if "station" not in slr.columns:
        slr = slr.reset_index()
    skip = {"station", "lat", "lon", "decade", "year"}
    pcol = [c for c in slr.columns if str(c).lower() in ("percentile", "quantile", "pct")]
    if pcol:
        pc = pcol[0]
        vals = slr[pc]
        med = vals.iloc[(vals - 50).abs().argsort()[:1]].iloc[0] if vals.max() > 1 else 0.5
        slr = slr[np.isclose(vals, med)]
    num = [c for c in slr.columns if pd.api.types.is_numeric_dtype(slr[c]) and c not in skip and c not in pcol]
    vcol = [c for c in num if re.search(r"cm|rise|rsl|slr|value|level", str(c).lower())]
    vcol = (vcol or num)[-1]
    dcol = "decade" if "decade" in slr.columns else "year"
    scol = "scenario"
    slr[scol] = slr[scol].astype(str).str.lower().str.replace(" ", "-").str.replace("_", "-")
    scen_names = {"intermediate": "intermediate", "high": "high"}
    stations_all = ewl.loc[levels.index]
    pts = stations_all[["lat", "lon"]].reset_index() if "lat" in stations_all.columns else None
    if pts is None:
        proj = tables["htf_decadal"].drop_duplicates("station")[["station", "lat", "lon"]]
        pts = proj[proj["station"].isin(levels.index)]
    nearest = nearest_station(pts[["station", "lat", "lon"]])
    logrp = np.log(rps)
    zmap = {"minor": 1.0, "moderate": 22.0, "major": 100.0}

    def level_at(row, rp):
        v = row.values.astype(float)
        ok = ~np.isnan(v)
        return np.interp(np.log(rp), logrp[ok], v[ok])

    def rp_at(row, z):
        v = row.values.astype(float)
        ok = ~np.isnan(v)
        v, lr = v[ok], logrp[ok]
        if z <= v[0]:
            return float(np.exp(lr[0]))
        if z >= v[-1]:
            slope = (lr[-1] - lr[-2]) / max(v[-1] - v[-2], 1e-6)
            return float(np.exp(lr[-1] + slope * (z - v[-1])))
        return float(np.exp(np.interp(z, v, lr)))

    weights = ANNUAL_CHANCE[list(SEVERITIES)]
    share = weights / weights.sum()
    result = {}
    for warming, scenario in SCENARIOS.items():
        for period, decade in DECADES.items():
            sub = slr[(slr[scol] == scenario) & (slr[dcol] == decade)]
            sub = sub.groupby("station")[vcol].mean()
            rise_scale = 0.01
            hm = {}
            for st in levels.index:
                if st not in sub.index or pd.isna(sub[st]):
                    continue
                rise = sub[st] * rise_scale
                row = levels.loc[st]
                total = 0.0
                for sev in SEVERITIES:
                    z = level_at(row, zmap[sev])
                    new_rp = rp_at(row, z - rise)
                    new_rp = max(new_rp, 0.1)
                    total += share[sev] * OLD_RP[sev] / new_rp
                hm[st] = total
            result[f"CFLD_{period}_{warming}_HM"] = nearest.map(pd.Series(hm))
    return pd.DataFrame(result)


def hazard_multipliers() -> pd.DataFrame:
    try:
        out = return_period_hm()
        if out.notna().sum().min() < 20 or not np.isfinite(out.values.astype(float)[~np.isnan(out.values.astype(float))]).all():
            raise ValueError("insufficient coverage")
        return out
    except Exception:
        return baseline_method()
