"""What-if coastal flooding multipliers built on the recovered recipe. Scenarios, not findings.

FEMA's coastal multiplier is HM = sum over NOAA's minor, moderate and major thresholds of
(frequency factor x weight). The recovered recipe (fri_rebuild.coastal.recipe) gives
the factors, so each county's weights can be solved from FEMA's published HMs. For most counties
the weights sum to less than 1: part of today's coastal flood EAL gets no factor at all. NRI
v1.19.0 also counts coastal flood EAL in the 1% and 0.2% annual-chance floodplains, and our
reading is that this remainder is that floodplain share.

For counties the recipe fits within 1%, this module computes three what-if versions of the HM:
- floodplain_kept: the remainder keeps today's losses (factor 1).
- floodplain_1pct: the remainder grows like the 1% annual-chance flood level does under the
  scenario's sea level rise (frequency at the 100-year level minus the rise, over 1 per 100).
- floodplain_0_2pct: the same for the 0.2% annual-chance level (500-year, extrapolated from the
  curve's last six points), the other end of the range, since NRI does not publish how the
  floodplain share splits between the two.
None of these is FEMA's number or a forecast; they show how much the omission could matter.

The notebook notebooks/coastal_scenarios.py runs them and writes results/coastal_scenarios/.
"""

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from fri_rebuild.coastal import forensics, recipe, recipe_score
from fri_rebuild.scoring import answer_key
from fri_rebuild.sources import tide_gauges

FIT_TOLERANCE = 0.01
VARIANTS = ("published", "floodplain_kept", "floodplain_1pct", "floodplain_0_2pct")


def level_at(period: float, levels: np.ndarray, periods: np.ndarray, tail: int) -> float:
    """Water level of a return period, log-linear in return period, extrapolated past 100 years."""
    log_rp = np.log(periods)
    if period <= periods[-1]:
        return float(np.interp(np.log(period), log_rp, levels))
    slope = (levels[-1] - levels[-tail]) / (log_rp[-1] - log_rp[-tail])
    return float(levels[-1] + slope * (np.log(period) - log_rp[-1]))


def floodplain_factors(gauge: str) -> dict[str, np.ndarray]:
    """Growth of the 1% and 0.2% annual-chance flood frequencies under each scenario's rise."""
    curves = tide_gauges.tables()["extreme_water_levels"]
    row = curves[curves["St"].astype(str) == gauge].iloc[0]
    columns, periods = forensics.return_periods(curves)
    levels = np.maximum.accumulate(row[columns].to_numpy(float))
    rise = recipe.rises(row)
    factors = {}
    for name, period in (("floodplain_1pct", 100.0), ("floodplain_0_2pct", 500.0)):
        level = level_at(period, levels, periods, recipe.TAIL_POINTS)
        today = recipe.frequency(level, levels, periods)
        factors[name] = np.array(
            [
                recipe.frequency(level - rise[(scenario, year)], levels, periods) / today
                for year in recipe.YEARS
                for scenario in recipe.SCENARIOS
            ]
        )
    return factors


def county_scenarios() -> pd.DataFrame:
    counties = recipe_score.counties()
    eal = answer_key.load()["CFLD_EALT"].to_dict()
    rows = []
    for gauge, group in counties.groupby("St"):
        factors = recipe.gauge_factors(str(gauge))
        if factors is None:
            continue
        floodplain = floodplain_factors(str(gauge))
        for fips, county in group.iterrows():
            published = county[forensics.COLUMNS].to_numpy(float)
            weights, residual = nnls(factors.T, published)
            remainder = max(0.0, 1.0 - weights.sum())
            fitted = residual / np.linalg.norm(published) < FIT_TOLERANCE
            for index, column in enumerate(forensics.COLUMNS):
                rows.append(
                    {
                        "fips": fips,
                        "state": county["STATEABBRV"],
                        "county": county["COUNTY"],
                        "gauge": county["Location"],
                        "scenario": column.removeprefix("CFLD_").removesuffix("_HM"),
                        "recipe_fits_within_1pct": fitted,
                        "tidal_weight_sum": weights.sum(),
                        "floodplain_remainder": remainder,
                        "eal_v1_19": eal[fips],
                        "published": published[index],
                        "floodplain_kept": published[index] + remainder,
                        "floodplain_1pct": published[index]
                        + remainder * floodplain["floodplain_1pct"][index],
                        "floodplain_0_2pct": published[index]
                        + remainder * floodplain["floodplain_0_2pct"][index],
                    }
                )
    return pd.DataFrame(rows)


def summary(table: pd.DataFrame) -> pd.DataFrame:
    """Projected annual loss and rating changes per scenario and variant, fitted counties only."""
    key = answer_key.load()
    thresholds = answer_key.rating_thresholds(key, "CFLD")
    fitted = table[table["recipe_fits_within_1pct"]]
    rows = []
    for scenario, part in fitted.groupby("scenario", sort=False):
        eal = part["eal_v1_19"]
        published_rating = answer_key.rate(eal * part["published"].clip(lower=1), thresholds)
        for variant in VARIANTS:
            pal = eal * part[variant].clip(lower=1)
            rating = answer_key.rate(pal, thresholds)
            rows.append(
                {
                    "scenario": scenario,
                    "variant": variant,
                    "counties": len(part),
                    "projected_annual_loss_usd_m": pal.sum() / 1e6,
                    "rating_changes_vs_published": int((rating != published_rating).sum()),
                    "median_hm": part[variant].median(),
                }
            )
    return pd.DataFrame(rows)
