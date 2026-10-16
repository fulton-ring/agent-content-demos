"""Score a candidate recipe for FEMA's coastal flooding gauge factors (forensic, answer key open).

A recipe is a Python file defining

    gauge_factors(gauge: str) -> numpy array (3, 4) or None

for one of the 187 gauges in the 2022 report's extreme water level table (`gauge` is its NOAA
station id as a string). Rows are the minor, moderate and major sub-types; columns are
CFLD_MID_LOWER, CFLD_MID_HIGHER, CFLD_LATE_LOWER, CFLD_LATE_HIGHER. Return None when the recipe
has no data for the gauge. It may use `fri_rebuild.inputs.coastal_tables()`.

Each county takes its nearest gauge (polygon distance, as FEMA describes). The scorer fits the
county's three weights (non-negative) to its four published multipliers and reports:
- four_distinct_median: median relative residual over counties whose four values all differ.
  These are the only counties that test a recipe; the main metric, lower is better.
- four_distinct_exact: how many of them are reproduced to within 0.1%.
- three_value_median: the same for counties whose two late values are equal (a fit there is
  exact whenever the weights come out non-negative, so this only tests feasibility).
- late_pattern: share of counties where the recipe agrees with the data on whether the two
  late-century values are equal.
- coverage: counties whose gauge the recipe returned factors for.

Usage: python -m fri_rebuild.recipe_score <recipe.py>
"""

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from fri_rebuild import forensics
from fri_rebuild.experiment import load_pipeline
from fri_rebuild.paths import cache_path


def counties() -> pd.DataFrame:
    target = cache_path("forensics", "coastal_counties.parquet")
    if not target.exists():
        table = forensics.published()
        table = table[table[forensics.COLUMNS[0]] > 0]
        joined = table[["STATEABBRV", "COUNTY", *forensics.COLUMNS]].join(
            forensics.nearest_gauges(table)
        )
        joined["St"] = joined["St"].astype(str)
        joined.to_parquet(target)
    return pd.read_parquet(target)


def score(recipe_path: Path) -> tuple[dict[str, float], pd.DataFrame]:
    recipe = load_pipeline(recipe_path)
    table = counties()
    rows = []
    for gauge, group in table.groupby("St"):
        factors = recipe.gauge_factors(str(gauge))
        if factors is None:
            continue
        factors = np.asarray(factors, dtype=float)
        if factors.shape != (3, 4) or not np.isfinite(factors).all():
            raise ValueError(f"gauge {gauge}: factors must be a finite 3 x 4 array")
        recipe_late_equal = bool(np.allclose(factors[:, 2], factors[:, 3], rtol=1e-9))
        for fips, county in group.iterrows():
            values = county[forensics.COLUMNS].to_numpy(float)
            weights, residual = nnls(factors.T, values)
            data_late_equal = bool(np.isclose(values[2], values[3], rtol=1e-9))
            rows.append(
                {
                    "fips": fips,
                    "state": county["STATEABBRV"],
                    "county": county["COUNTY"],
                    "gauge": county["Location"],
                    "four_distinct": not data_late_equal,
                    "late_pattern_agrees": data_late_equal == recipe_late_equal,
                    "relative_residual": residual / np.linalg.norm(values),
                    "weight_sum": weights.sum(),
                }
            )
    detail = pd.DataFrame(rows)
    four = detail[detail["four_distinct"]]
    three = detail[~detail["four_distinct"]]
    summary = {
        "four_distinct_median": float(four["relative_residual"].median()),
        "four_distinct_exact": int((four["relative_residual"] < 1e-3).sum()),
        "four_distinct_counties": len(four),
        "three_value_median": float(three["relative_residual"].median()),
        "late_pattern": float(detail["late_pattern_agrees"].mean()),
        "coverage": len(detail),
        "counties_total": len(table),
    }
    return summary, detail


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("recipe", type=Path)
    args = parser.parse_args()
    started = time.time()
    summary, detail = score(args.recipe)
    print("---")
    for name, value in summary.items():
        print(f"{name}: {value:.6f}" if isinstance(value, float) else f"{name}: {value}")
    print(f"seconds: {time.time() - started:.1f}")
    worst = detail[detail["four_distinct"]].sort_values("relative_residual", ascending=False)
    with pd.option_context("display.width", 200):
        print("four-distinct counties, worst first:")
        print(worst.head(12).round(4).to_string(index=False))
        by_gauge = detail.groupby("gauge")["relative_residual"].median().sort_values()
        print("median residual by gauge, worst 10:")
        print(by_gauge.tail(10).round(4).to_string())


if __name__ == "__main__":
    main()
