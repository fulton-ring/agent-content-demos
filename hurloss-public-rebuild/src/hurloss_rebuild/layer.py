"""Our hurricane hazard multipliers: FEMA's documented formula on open inputs, with a range.

- Hazard today: wind exceedance from a synthetic track catalogue (STORM present climate).
- Scenarios: Knutson et al. (2020) changes, converted per scenario by Jewson (2021), applied as
  Jewson recommends (frequency only, by storm category).
- Formula: FRI Eq. 11-12 as FEMA documents it, HM = max(1, projected / historical intensity).
- Range: the same calculation at each published Knutson percentile; the central value is the
  median.

A unit (county or tract) with no Cat 1 wind in the catalogue gets HM = 1, which is how FEMA's
own ratings treat the counties it published as 0.
"""

import numpy as np
import pandas as pd

from hurloss_rebuild import conditioning, rebuild
from hurloss_rebuild.conditioning import CENTRAL, PERCENTILES, SCENARIOS
from hurloss_rebuild.hazard import Events


def ratios_by_percentile(events: Events, point_unit: pd.Series) -> pd.DataFrame:
    """Long table: unit, scenario, percentile, unfloored intensity ratio (blank if no wind)."""
    today = rebuild.county_intensity(events, point_unit)
    frames = []
    for scenario in SCENARIOS:
        for percentile in PERCENTILES:
            scaled = conditioning.frequency_only(events, scenario, percentile)
            projected = rebuild.county_intensity(scaled, point_unit)
            frames.append(
                pd.DataFrame(
                    {
                        "unit": today.index,
                        "scenario": scenario.name,
                        "percentile": percentile,
                        "ratio": rebuild.ratio(projected, today).to_numpy(),
                    }
                )
            )
    return pd.concat(frames, ignore_index=True)


def wide(ratios: pd.DataFrame, today: pd.Series) -> pd.DataFrame:
    """One row per unit: central HM and its low/high across Knutson percentiles, per scenario."""
    hm = ratios.assign(hm=ratios["ratio"].clip(lower=1.0).fillna(1.0))
    table = pd.DataFrame(index=today.index)
    table["intensity_today"] = today
    table["no_cat1_wind"] = ~(today > 0)
    for scenario in SCENARIOS:
        part = hm[hm["scenario"] == scenario.name].pivot(
            index="unit", columns="percentile", values="hm"
        )
        table[f"{scenario.name}_HM"] = part[CENTRAL]
        table[f"{scenario.name}_HM_LOW"] = part[list(PERCENTILES)].min(axis=1)
        table[f"{scenario.name}_HM_HIGH"] = part[list(PERCENTILES)].max(axis=1)
    return table


def multipliers(events: Events, point_unit: pd.Series) -> pd.DataFrame:
    """The layer for every unit the points map to."""
    today = rebuild.county_intensity(events, point_unit)
    if not np.isfinite(today.to_numpy()).all():
        raise ValueError("non-finite intensity today")
    return wide(ratios_by_percentile(events, point_unit), today)


def combine(catalogues: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One layer from several hazard catalogues.

    Central HM is the mean of the catalogues that have Cat 1 wind at the unit; the range runs
    from the lowest to the highest value over every catalogue and Knutson percentile. Each
    catalogue's central value is kept as its own column.
    """
    if not catalogues:
        raise ValueError("no catalogues to combine")
    units = sorted(set().union(*(table.index for table in catalogues.values())))
    table = pd.DataFrame(index=pd.Index(units, name="unit"))
    covered = pd.DataFrame(
        {
            name: ~t["no_cat1_wind"].reindex(units).fillna(True).astype(bool)
            for name, t in catalogues.items()
        }
    )
    table["no_cat1_wind"] = ~covered.any(axis=1)
    table["catalogues_with_wind"] = covered.sum(axis=1)
    for scenario in SCENARIOS:
        name = scenario.name
        central = pd.DataFrame(
            {c: t[f"{name}_HM"].reindex(units).where(covered[c]) for c, t in catalogues.items()}
        )
        low = pd.DataFrame(
            {c: t[f"{name}_HM_LOW"].reindex(units).where(covered[c]) for c, t in catalogues.items()}
        )
        high = pd.DataFrame(
            {
                c: t[f"{name}_HM_HIGH"].reindex(units).where(covered[c])
                for c, t in catalogues.items()
            }
        )
        table[f"{name}_HM"] = central.mean(axis=1).fillna(1.0)
        table[f"{name}_HM_LOW"] = low.min(axis=1).fillna(1.0)
        table[f"{name}_HM_HIGH"] = high.max(axis=1).fillna(1.0)
        for catalogue in catalogues:
            table[f"{name}_HM_{catalogue.upper()}"] = central[catalogue]
    return table
