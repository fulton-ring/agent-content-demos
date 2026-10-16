"""Forensic checks on FEMA's published coastal flooding multipliers (answer key open).

Unlike the rest of this project, this module reads the published values directly. It asks what
structure produced them and where they disagree with FEMA's own documentation:

1. Counties published with HM = 0, and whether FEMA's own PAL ratings treat them as 0 or 1.
2. Counties published with 0 < HM < 1, which the documented formula cannot produce.
3. How often the two late-century scenarios are identical, by state.
4. Whether counties that share a tide gauge lie in a 3-dimensional subspace, as
   HM = sum over sub-types of (gauge factor x county weight) requires. Groups with all four
   scenario values distinct are compared with random groups of the same counties.
5. How well one candidate recipe for the gauge factors, built from the 2022 Sea Level Rise
   Technical Report (return-level curve, median relative sea level rise, frequencies capped at
   the curve's shortest return period), reproduces each county with non-negative weights.

Usage: python -m fri_rebuild.forensics  (writes results/forensics/*.csv)
"""

import re

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.optimize import nnls

from fri_rebuild import answer_key, coastal, geo
from fri_rebuild.paths import RESULTS_DIR

COLUMNS = [f"CFLD_{s}_HM" for s in answer_key.SCENARIOS]
SCENARIOS = {"LOWER": "1.0 - MED", "HIGHER": "2.0 - MED"}
YEARS = {"MID": 2050, "LATE": 2100}
SUB_TYPES = {"minor": [1, 2], "moderate": [10, 20, 30, 40, 50], "major": [100]}
OUT = RESULTS_DIR / "forensics"


def published() -> pd.DataFrame:
    key = answer_key.load()
    return key[key[COLUMNS].notna().any(axis=1)]


def nearest_gauges(table: pd.DataFrame) -> pd.DataFrame:
    """Nearest of the 187 report gauges (polygon distance) for each county in `table`."""
    gauges = coastal.tables()["extreme_water_levels"]
    points = geo.points(
        gauges.rename(columns={"Latitude": "lat", "Longitude": "lon"})[
            ["St", "Location", "lat", "lon"]
        ]
    ).to_crs(geo.EQUAL_AREA)
    counties = geo.counties()
    shapes = counties.loc[counties.index.isin(table.index)].to_crs(geo.EQUAL_AREA)
    joined = gpd.sjoin_nearest(
        shapes[["geometry"]], points[["St", "Location", "geometry"]], distance_col="distance_m"
    )
    return joined.groupby(level=0)[["St", "Location", "distance_m"]].first()


def zeros(table: pd.DataFrame) -> pd.DataFrame:
    """Counties published at HM = 0, with whether their PAL ratings imply HM = 0 or HM = 1."""
    thresholds = answer_key.rating_thresholds(table, "CFLD")
    rows = table[table[COLUMNS[0]] == 0]
    eal = rows["CFLD_EALT"]
    late = rows["CFLD_LATE_HIGHER_PALR"].map(answer_key.rating_name)
    return rows[["STATEABBRV", "COUNTY", "CFLD_EALT", "CFLD_EALR", "CFLD_LATE_HIGHER_PALR"]].assign(
        rating_if_hm_0=answer_key.rate(eal * 0, thresholds),
        rating_if_hm_1=answer_key.rate(eal, thresholds),
        matches_hm_1=lambda d: d["rating_if_hm_1"] == late,
    )


def below_one(table: pd.DataFrame, gauges: pd.DataFrame) -> pd.DataFrame:
    rows = table[(table[COLUMNS] > 0).all(axis=1) & (table[COLUMNS] < 1).any(axis=1)]
    return rows[["STATEABBRV", "COUNTY", "CFLD_EALT", *COLUMNS]].join(gauges)


def late_equality(table: pd.DataFrame) -> pd.DataFrame:
    rows = table[table[COLUMNS[0]] > 0]
    equal = np.isclose(rows["CFLD_LATE_LOWER_HM"], rows["CFLD_LATE_HIGHER_HM"], rtol=1e-9)
    frame = pd.DataFrame({"state": rows["STATEABBRV"], "late_equal": equal})
    summary = frame.groupby("state")["late_equal"].agg(["size", "sum"])
    summary.columns = ["counties", "late_lower_equals_higher"]
    return summary.sort_values(by="counties", ascending=False)


def rank_ratio(values: np.ndarray) -> float:
    """Fourth singular value over the first, rows scaled to unit length (0 = exactly rank 3)."""
    scaled = values / np.linalg.norm(values, axis=1, keepdims=True)
    singular = np.linalg.svd(scaled, compute_uv=False)
    return float(singular[3] / singular[0])


def subspace_test(table: pd.DataFrame, gauges: pd.DataFrame) -> pd.DataFrame:
    rows = table[table[COLUMNS[0]] > 0].join(gauges)
    distinct = rows[~np.isclose(rows["CFLD_LATE_LOWER_HM"], rows["CFLD_LATE_HIGHER_HM"])]
    rng = np.random.default_rng(0)
    pool = distinct[COLUMNS].to_numpy()
    results = []
    for location, group in distinct.groupby("Location"):
        if len(group) < 4:
            continue
        random = [
            rank_ratio(pool[rng.choice(len(pool), len(group), replace=False)]) for _ in range(2000)
        ]
        results.append(
            {
                "gauge": location,
                "counties": len(group),
                "rank_ratio": rank_ratio(group[COLUMNS].to_numpy()),
                "random_groups_median": float(np.median(random)),
                "random_groups_p01": float(np.quantile(random, 0.01)),
            }
        )
    return pd.DataFrame(results)


def return_periods(levels: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    pattern = re.compile(r"^([\d.]+)yrRL")
    matches = [(c, pattern.match(c)) for c in levels.columns]
    found = [(c, m) for c, m in matches if m is not None]
    return [c for c, _ in found], np.array([float(m.group(1)) for _, m in found])


def exceedance_frequency(level: float, levels: np.ndarray, periods: np.ndarray, cap: bool) -> float:
    """Events per year above `level` from a return-level curve; log-linear beyond the table."""
    log_rp = np.log(periods)
    if level <= levels[0]:
        if cap:
            return 1 / periods[0]
        slope = (log_rp[1] - log_rp[0]) / (levels[1] - levels[0])
        return float(np.exp(-(log_rp[0] + slope * (level - levels[0]))))
    if level >= levels[-1]:
        slope = (log_rp[-1] - log_rp[-6]) / (levels[-1] - levels[-6])
        return float(np.exp(-(log_rp[-1] + slope * (level - levels[-1]))))
    return float(np.exp(-np.interp(level, levels, log_rp)))


def report_factors(gauge: str, cap: bool) -> np.ndarray | None:
    """3 x 4 sub-type factors for one gauge: projected / current frequency of today's levels."""
    tables = coastal.tables()
    curves, rise_table = tables["extreme_water_levels"], tables["sea_level_projections"]
    columns, periods = return_periods(curves)
    row = curves[curves["St"].astype(str) == gauge]
    rises = rise_table[rise_table["NOAA ID"] == float(gauge)]
    if row.empty or rises.empty:
        return None
    levels = np.maximum.accumulate(row[columns].to_numpy(float)[0])
    factors = []
    for return_list in SUB_TYPES.values():
        today = [np.interp(np.log(rp), np.log(periods), levels) for rp in return_list]
        current = np.mean([1 / rp for rp in return_list])
        vector = []
        for period, year in YEARS.items():
            for warming, scenario in SCENARIOS.items():
                rise = rises[rises["Scenario"] == scenario].iloc[0][f"RSL{year} (cm)"] / 100
                future = np.mean(
                    [exceedance_frequency(z - rise, levels, periods, cap) for z in today]
                )
                vector.append((f"CFLD_{period}_{warming}_HM", future / current))
        factors.append([dict(vector)[c] for c in COLUMNS])
    return np.array(factors)


def recipe_fit(table: pd.DataFrame, gauges: pd.DataFrame) -> pd.DataFrame:
    """Fit each county's weights (non-negative) to report-based gauge factors.

    Only counties whose four published values are all distinct test a recipe: with the late
    scenarios equal, three weights always fit three numbers exactly whenever they are non-negative.
    """
    rows = table[table[COLUMNS[0]] > 0].join(gauges)
    results = []
    for gauge, group in rows.groupby("St"):
        factors = report_factors(str(gauge), cap=True)
        if factors is None:
            continue
        for fips, county in group.iterrows():
            values = county[COLUMNS].to_numpy(float)
            weights, residual = nnls(factors.T, values)
            results.append(
                {
                    "fips": fips,
                    "state": county["STATEABBRV"],
                    "county": county["COUNTY"],
                    "gauge": county["Location"],
                    "four_distinct": not np.isclose(values[2], values[3]),
                    "relative_residual": residual / np.linalg.norm(values),
                    "weight_sum": weights.sum(),
                    "w_minor": weights[0],
                    "w_moderate": weights[1],
                    "w_major": weights[2],
                }
            )
    return pd.DataFrame(results)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    table = published()
    gauges = nearest_gauges(table)
    outputs = {
        "coastal_zero_hm.csv": zeros(table),
        "coastal_hm_below_one.csv": below_one(table, gauges),
        "coastal_late_equality_by_state.csv": late_equality(table),
        "coastal_gauge_rank_test.csv": subspace_test(table, gauges),
        "coastal_recipe_fit.csv": recipe_fit(table, gauges),
    }
    for name, frame in outputs.items():
        frame.to_csv(OUT / name)
    zero = outputs["coastal_zero_hm.csv"]
    print(
        f"HM = 0: {len(zero)} counties; PAL ratings match HM = 1 for {zero['matches_hm_1'].sum()}"
    )
    print(f"0 < HM < 1: {len(outputs['coastal_hm_below_one.csv'])} counties")
    equal = outputs["coastal_late_equality_by_state.csv"]
    print(
        f"late lower == late higher: {equal['late_lower_equals_higher'].sum()} of "
        f"{equal['counties'].sum()} counties"
    )
    with pd.option_context("display.width", 200):
        print(outputs["coastal_gauge_rank_test.csv"].round(4).to_string(index=False))
        fit = outputs["coastal_recipe_fit.csv"]
        print(
            fit.groupby("four_distinct")["relative_residual"]
            .describe(percentiles=[0.1, 0.5, 0.9])
            .round(4)
            .to_string()
        )


if __name__ == "__main__":
    main()
