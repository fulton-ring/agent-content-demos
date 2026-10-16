"""Agent 1 recipe: sub-types are NOAA's minor/moderate/major flood *thresholds*, not return periods.

For each gauge the return-level curve (0.1 to 100 yr, m above MHHW) gives the annual frequency of
exceeding a water level: log-linear in return period inside the table, extended above the 100-yr
level with the slope of the last `NSLOPE` table points, and capped at 1 / 0.1 yr = 10 per year
below the 0.1-yr level. The three sub-types are the gauge's NOAA minor, moderate and major
thresholds (flood_thresholds, m above MHHW). Sea level rise (median 1.0 m and 2.0 m scenarios for
LOWER and HIGHER, 2050 and 2100) lowers the threshold; factor = f(threshold - rise) / f(threshold).
Gauges without a direct sea level row take the nearest 1-degree grid cell; gauges without NOAA
thresholds take the median of the gauges that have them.
"""

import numpy as np

from fri_rebuild import coastal, forensics

NSLOPE = 6  # table points used to extrapolate the curve above the 100-yr level
CAP_RP = 0.1  # shortest return period in the table: frequency cap = 1 / CAP_RP per year
SCENARIOS = ("1.0 - MED", "2.0 - MED")  # LOWER, HIGHER
YEARS = (2050, 2100)

_T = coastal.tables()
_CURVES, _RISE, _TH = (
    _T["extreme_water_levels"],
    _T["sea_level_projections"],
    _T["flood_thresholds"],
)
_COLS, _PERIODS = forensics.return_periods(_CURVES)
_LOGP = np.log(_PERIODS)
_TH = _TH.set_index("station")
_NAMES = ["minor_m_above_mhhw", "moderate_m_above_mhhw", "major_m_above_mhhw"]
_TH_DEFAULT = _TH[_NAMES].median()


def _rises(gauge: str, row) -> dict:
    rises = _RISE[_RISE["NOAA ID"] == float(gauge)]
    if rises.empty:  # nearest 1-degree grid cell
        grid = _RISE.dropna(subset=["Lat", "Long"])
        sel = grid[grid["Scenario"] == SCENARIOS[0]]
        lat, lon = row["Latitude"].iloc[0], row["Longitude"].iloc[0]
        d = (sel["Lat"] - lat) ** 2 + ((sel["Long"] - lon) * np.cos(np.radians(lat))) ** 2
        k = sel.loc[d.idxmin()]
        rises = grid[(grid["Lat"] == k["Lat"]) & (grid["Long"] == k["Long"])]
    return {
        (sc, yr): rises[rises["Scenario"] == sc].iloc[0][f"RSL{yr} (cm)"] / 100
        for sc in SCENARIOS
        for yr in YEARS
    }


def _frequency(level: float, levels: np.ndarray) -> float:
    if level <= levels[0]:
        return 1 / CAP_RP
    if level >= levels[-1]:
        slope = (_LOGP[-1] - _LOGP[-NSLOPE]) / (levels[-1] - levels[-NSLOPE])
        return float(np.exp(-(_LOGP[-1] + slope * (level - levels[-1]))))
    return float(np.exp(-np.interp(level, levels, _LOGP)))


def gauge_factors(gauge: str) -> np.ndarray | None:
    row = _CURVES[_CURVES["St"].astype(str) == gauge]
    if row.empty:
        return None
    levels = np.maximum.accumulate(row[_COLS].to_numpy(float)[0])
    th = _TH.loc[gauge, _NAMES] if gauge in _TH.index else _TH_DEFAULT
    if th.isna().any():
        th = _TH_DEFAULT
    rise = _rises(gauge, row)
    out = []
    for name in _NAMES:
        t = float(th[name])
        now = _frequency(t, levels)
        out.append(
            [_frequency(t - rise[(sc, yr)], levels) / now for yr in YEARS for sc in SCENARIOS]
        )
    return np.array(out)
