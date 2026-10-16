"""The coastal flooding recipe the forensic search converged on (two agents, independently).

Sub-types are NOAA's minor, moderate and major flood thresholds at each gauge (m above MHHW),
not the 1-2, 10-50 and 100 year floods FEMA's documentation names. For each threshold, today's
annual frequency of exceedance is read off the gauge's return-level curve from the 2022 Sea Level
Rise Technical Report. Each scenario lowers the threshold by the median relative sea level rise
(1.0 m scenario for LOWER, 2.0 m for HIGHER; 2050 and 2100) and reads the new frequency off the
same curve. Frequencies are capped at 10 a year (the curve's shortest return period, 0.1 year),
which is why both late-century scenarios coincide where the thresholds sink below the curve.
The factor is new frequency / today's frequency.

Gauges without their own sea level row take the nearest projection point; gauges without NOAA
thresholds take the nearest gauge that has them. Nothing here reads FEMA's published values.
"""

import numpy as np
import pandas as pd

from fri_rebuild import coastal, forensics

SCENARIOS = ("1.0 - MED", "2.0 - MED")
YEARS = (2050, 2100)
CAP_PER_YEAR = 10.0
TAIL_POINTS = 6
# Where each gauge's minor/moderate/major thresholds come from:
# "published": CO-OPS thresholds, or the nearest gauge's when a gauge has none.
# "formula": NOAA's derived thresholds from the tide range (Sweet et al. 2018) for every gauge.
# "formula_missing": published thresholds where they exist, the formula elsewhere.
THRESHOLD_SOURCE = "published"
FORMULA = ((0.04, 0.50), (0.03, 0.80), (0.04, 1.17))  # (x GT, + metres) above MHHW


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
    scale = np.cos(np.radians(lat))
    distance = (table[lat_col] - lat) ** 2 + ((table[lon_col] - lon) * scale) ** 2
    return int(distance.idxmin())


def rises(gauge: pd.Series) -> dict[tuple[str, int], float]:
    """Median relative sea level rise (m) by scenario and year at the gauge."""
    projections = coastal.tables()["sea_level_projections"]
    own = projections[projections["NOAA ID"] == float(gauge["St"])]
    lat, lon = (
        (own.iloc[0]["Lat"], own.iloc[0]["Long"])
        if not own.empty
        else (gauge["Latitude"], gauge["Longitude"])
    )
    point = projections.loc[nearest(projections, lat, lon, "Lat", "Long")]
    rows = projections[
        (projections["Lat"] == point["Lat"]) & (projections["Long"] == point["Long"])
    ].set_index("Scenario")
    by_year = {year: rows[f"RSL{year} (cm)"].to_dict() for year in YEARS}
    return {
        (scenario, year): float(by_year[year][scenario]) / 100
        for scenario in SCENARIOS
        for year in YEARS
    }


def formula_thresholds(gauge: pd.Series) -> np.ndarray:
    datums = coastal.tables()["tidal_datums"]
    gt = float(datums.loc[datums["station"] == str(gauge["St"]), "gt_m"].iloc[0])
    return np.array([slope * gt + intercept for slope, intercept in FORMULA])


def thresholds(gauge: pd.Series) -> np.ndarray:
    """NOAA minor, moderate and major thresholds (m above MHHW) for one gauge."""
    if THRESHOLD_SOURCE == "formula":
        return formula_thresholds(gauge)
    tables = coastal.tables()
    known = tables["flood_thresholds"].dropna()
    own = known[known["station"].astype(str) == str(gauge["St"])]
    if own.empty and THRESHOLD_SOURCE == "formula_missing":
        return formula_thresholds(gauge)
    if own.empty:
        curves = tables["extreme_water_levels"]
        candidates = curves[curves["St"].astype(str).isin(set(known["station"].astype(str)))]
        neighbour = str(
            candidates.loc[
                nearest(candidates, gauge["Latitude"], gauge["Longitude"], "Latitude", "Longitude"),
                "St",
            ]
        )
        own = known[known["station"].astype(str) == neighbour]
    return own.iloc[0, 1:].to_numpy(float)


def gauge_factors(gauge: str) -> np.ndarray | None:
    curves = coastal.tables()["extreme_water_levels"]
    match = curves[curves["St"].astype(str) == gauge]
    if match.empty:
        return None
    row = match.iloc[0]
    columns, periods = forensics.return_periods(curves)
    levels = np.maximum.accumulate(row[columns].to_numpy(float))
    rise = rises(row)
    factors = []
    for threshold in thresholds(row):
        today = frequency(threshold, levels, periods)
        factors.append(
            [
                frequency(threshold - rise[(scenario, year)], levels, periods) / today
                for year in YEARS
                for scenario in SCENARIOS
            ]
        )
    return np.array(factors)
