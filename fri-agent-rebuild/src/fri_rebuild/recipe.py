"""The recipe for FEMA's coastal flooding gauge factors that the forensic search converged on.

Shared by the coastal and Charleston notebooks; the coastal notebook explains how it was found.
Sub-types are NOAA's minor, moderate and major flood thresholds at a gauge. Each one's annual
frequency today is read off the gauge's return-level curve (2022 Sea Level Rise Technical
Report); a scenario lowers the threshold by the median relative sea level rise and reads the
curve again, capped at 10 a year. The factor is new frequency over today's.
"""

import re

import numpy as np
import pandas as pd

from fri_rebuild import data

COLUMNS = [f"CFLD_{s}_HM" for s in ("MID_LOWER", "MID_HIGHER", "LATE_LOWER", "LATE_HIGHER")]
# Column order of COLUMNS: (sea level scenario, year). 1.0 m of rise by 2100 is LOWER, 2.0 m HIGHER.
RISES = [("1.0 - MED", 2050), ("2.0 - MED", 2050), ("1.0 - MED", 2100), ("2.0 - MED", 2100)]
CAP_PER_YEAR = 10.0  # the curve's shortest return period is 0.1 year
TAIL_POINTS = 6
FORMULA = ((0.04, 0.50), (0.03, 0.80), (0.04, 1.17))  # Sweet et al. 2018: a x tide range + b


def curve(gauge: str) -> tuple[pd.Series, np.ndarray, np.ndarray]:
    """A gauge's row in the report, its return levels (m above MHHW) and return periods (years)."""
    curves = data.tide_tables()["extreme_water_levels"]
    columns = [c for c in curves.columns if re.match(r"^[\d.]+yrRL", c)]
    periods = np.array([float(c.split("yrRL")[0]) for c in columns])
    row = curves[curves["St"].astype(str) == gauge].iloc[0]
    return row, np.maximum.accumulate(row[columns].to_numpy(float)), periods


def frequency(level: float, levels: np.ndarray, periods: np.ndarray) -> float:
    """Annual exceedance frequency of `level`, log-linear in return period, capped."""
    log_rp = np.log(periods)
    if level <= levels[0]:
        slope = (log_rp[1] - log_rp[0]) / (levels[1] - levels[0])
        value = np.exp(-(log_rp[0] + slope * (level - levels[0])))
    elif level >= levels[-1]:
        slope = (log_rp[-1] - log_rp[-TAIL_POINTS]) / (levels[-1] - levels[-TAIL_POINTS])
        value = np.exp(-(log_rp[-1] + slope * (level - levels[-1])))
    else:
        value = np.exp(-np.interp(level, levels, log_rp))
    return float(min(CAP_PER_YEAR, value))


def nearest(table: pd.DataFrame, lat: float, lon: float, lat_col: str, lon_col: str) -> int:
    distance = (table[lat_col] - lat) ** 2 + ((table[lon_col] - lon) * np.cos(np.radians(lat))) ** 2
    return int(distance.idxmin())


def rises(gauge: pd.Series) -> list[float]:
    """Median relative sea level rise (m) at the gauge, in RISES order. A gauge without its own
    projection takes the nearest projection point."""
    projections = data.tide_tables()["sea_level_projections"]
    own = projections[projections["NOAA ID"] == float(gauge["St"])]
    lat, lon = (
        (own.iloc[0]["Lat"], own.iloc[0]["Long"])
        if len(own)
        else (gauge["Latitude"], gauge["Longitude"])
    )
    point = projections.loc[nearest(projections, lat, lon, "Lat", "Long")]
    rows = projections[
        (projections["Lat"] == point["Lat"]) & (projections["Long"] == point["Long"])
    ]
    by_scenario = {
        year: rows.set_index("Scenario")[f"RSL{year} (cm)"].to_dict() for _, year in RISES
    }
    return [float(by_scenario[year][scenario]) / 100 for scenario, year in RISES]


def thresholds(gauge: pd.Series, source: str = "published") -> np.ndarray:
    """NOAA minor, moderate and major thresholds (m above MHHW).

    source "published": CO-OPS thresholds, or the nearest gauge's where a gauge has none.
    "formula": NOAA's tide-range formula for every gauge. "formula_missing": published where
    they exist, the formula elsewhere.
    """
    tables = data.tide_tables()
    known = tables["flood_thresholds"].dropna()
    own = known[known["station"] == str(gauge["St"])]
    if source == "formula" or (own.empty and source == "formula_missing"):
        datums = tables["tidal_datums"]
        tide_range = float(datums.loc[datums["station"] == str(gauge["St"]), "gt_m"].iloc[0])
        return np.array([a * tide_range + b for a, b in FORMULA])
    if own.empty:
        curves = tables["extreme_water_levels"]
        candidates = curves[curves["St"].astype(str).isin(set(known["station"]))]
        index = nearest(candidates, gauge["Latitude"], gauge["Longitude"], "Latitude", "Longitude")
        own = known[known["station"] == str(candidates["St"].to_dict()[index])]
    return own.iloc[0, 1:].to_numpy(float)


def gauge_factors(gauge: str, source: str = "published") -> np.ndarray:
    """Frequency factors: rows minor, moderate, major; columns COLUMNS."""
    row, levels, periods = curve(gauge)
    shifts = rises(row)
    return np.array(
        [
            [
                frequency(z - rise, levels, periods) / frequency(z, levels, periods)
                for rise in shifts
            ]
            for z in thresholds(row, source)
        ]
    )
