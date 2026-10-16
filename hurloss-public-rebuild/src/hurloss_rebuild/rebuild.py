"""County hurricane multipliers from event sets, through FEMA's formula."""

from collections.abc import Callable

import numpy as np
import pandas as pd

from hurloss_rebuild import fri_formula
from hurloss_rebuild.conditioning import SCENARIOS, Scenario
from hurloss_rebuild.hazard import Events

Conditioner = Callable[[Events, Scenario], Events]


def county_intensity(events: Events, point_county: pd.Series) -> pd.Series:
    """Eq. 11 per county, from the mean Cat 1-5 frequencies of its points (Sec. 7.2)."""
    frequencies = fri_formula.category_frequencies(events.wind, events.frequency)
    county_frequencies = pd.DataFrame(
        {k: fri_formula.county_mean(frequencies[:, k], point_county) for k in range(5)}
    )
    return pd.Series(
        fri_formula.intensity(county_frequencies.to_numpy()), index=county_frequencies.index
    )


def ratio(projected: pd.Series, historical: pd.Series) -> pd.Series:
    """Projected over historical intensity, blank where today's is zero (before the floor)."""
    return projected.reindex(historical.index) / historical.where(historical > 0)


def conditioned_ratios(
    events: Events, point_county: pd.Series, condition: Conditioner
) -> pd.DataFrame:
    """Unfloored intensity ratio per county for each FEMA scenario."""
    today = county_intensity(events, point_county)
    return pd.DataFrame(
        {
            s.name: ratio(county_intensity(condition(events, s), point_county), today)
            for s in SCENARIOS
        }
    )


def ensemble_ratio(present: Events, futures: list[Events], point_county: pd.Series) -> pd.Series:
    """Equal-weight mean of each GCM's projected intensity over the present-climate intensity."""
    if not futures:
        raise ValueError("no future event sets")
    today = county_intensity(present, point_county)
    projected = pd.concat([county_intensity(f, point_county) for f in futures], axis=1)
    return ratio(projected.mean(axis=1), today)


def as_fema(ratios: pd.DataFrame) -> pd.DataFrame:
    """Eq. 12 as documented: max(1, ratio)."""
    return ratios.clip(lower=1.0)


def doubled(ratios: pd.DataFrame) -> pd.DataFrame:
    """max(1, 2 x ratio): the reading of FEMA's values with a stray factor of two."""
    return (2 * ratios).clip(lower=1.0)


def plus_one(ratios: pd.DataFrame) -> pd.DataFrame:
    """max(1, 1 + ratio): the reading where 'projected' already included the historical rate."""
    return (1 + ratios).clip(lower=1.0)


def drop_nonfinite(table: pd.DataFrame) -> pd.DataFrame:
    return table.replace([np.inf, -np.inf], np.nan)


def gcm_spread(
    present: Events, futures: dict[str, Events], point_county: pd.Series
) -> pd.DataFrame:
    """Per GCM and for the equal-weight ensemble: quantiles of the county intensity ratio."""
    today = county_intensity(present, point_county)
    ratios = {
        name: ratio(county_intensity(events, point_county), today)
        for name, events in futures.items()
    }
    ratios["ensemble"] = ensemble_ratio(present, list(futures.values()), point_county)
    rows = [
        {"gcm": name, "counties": int(values.notna().sum())}
        | {f"q{int(q * 100):02d}": values.quantile(q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
        for name, values in ratios.items()
    ]
    return pd.DataFrame(rows)
