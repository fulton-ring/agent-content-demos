"""Today's modelled hurricane hazard against NRI v1.20, before any climate conditioning.

If today's county hazard is wrong, no conditioning can fix the multipliers, so this check
separates the hazard model from the conditioning. NRI's hurricane EAL comes from Hazus
probabilistic runs, so we compare it with an expected annual damage ratio from our wind fields
(Emanuel 2011 damage curve, US calibration, via CLIMADA) times NRI's own exposure.
"""

import numpy as np
import pandas as pd

from hurloss_rebuild import fri_formula
from hurloss_rebuild.hazard import Events

TROPICAL_STORM_MS = 17.49
# Emanuel (2011) with CLIMADA's US parameters (ImpfTropCyclone.from_emanuel_usa). Importing
# climada.entity needs the GDAL bindings this project leaves out, so the two lines are here.
EMANUEL_THRESHOLD_MS = 25.7
EMANUEL_HALF_DAMAGE_MS = 74.7


def emanuel_damage(wind: np.ndarray) -> np.ndarray:
    """Mean damage ratio for 1-minute sustained wind (m/s)."""
    scaled = np.clip(wind - EMANUEL_THRESHOLD_MS, 0, None) / (
        EMANUEL_HALF_DAMAGE_MS - EMANUEL_THRESHOLD_MS
    )
    return scaled**3 / (1 + scaled**3)


def damage_ratio(events: Events) -> np.ndarray:
    """Expected annual damage ratio at each point: sum over events of rate x damage(wind)."""
    wind = events.wind.copy().astype(float)
    wind.data = emanuel_damage(wind.data)
    return np.asarray(wind.T @ events.frequency).ravel()


def storm_rate(events: Events) -> np.ndarray:
    """Annual rate of at least tropical-storm wind at each point."""
    reached = (events.wind >= TROPICAL_STORM_MS).astype(float)
    return np.asarray(reached.T @ events.frequency).ravel()


def county_table(events: Events, point_county: pd.Series, nri: pd.DataFrame) -> pd.DataFrame:
    """Per county: our intensity, damage ratio, modelled EAL and storm rate, next to NRI's."""
    frequencies = fri_formula.category_frequencies(events.wind, events.frequency)
    ours = pd.DataFrame(
        {
            "intensity": fri_formula.county_mean(fri_formula.intensity(frequencies), point_county),
            "damage_ratio": fri_formula.county_mean(damage_ratio(events), point_county),
            "storm_rate": fri_formula.county_mean(storm_rate(events), point_county),
        }
    )
    table = ours.join(nri[["HRCN_EALT", "HRCN_EXPT", "HRCN_AFREQ"]], how="left")
    table["modelled_eal"] = table["damage_ratio"] * table["HRCN_EXPT"]
    table["nri_loss_ratio"] = table["HRCN_EALT"] / table["HRCN_EXPT"]
    return table


def agreement(table: pd.DataFrame) -> pd.DataFrame:
    """Rank and scale agreement of our hazard with NRI, on counties where both are positive."""
    pairs = (
        ("modelled_eal", "HRCN_EALT"),
        ("damage_ratio", "nri_loss_ratio"),
        ("intensity", "nri_loss_ratio"),
        ("storm_rate", "HRCN_AFREQ"),
    )
    rows = []
    for ours, theirs in pairs:
        both = table[[ours, theirs]].dropna()
        both = both[(both[ours] > 0) & (both[theirs] > 0)]
        logs = both.transform(np.log)
        log_ratio = logs[ours] - logs[theirs]
        rows.append(
            {
                "ours": ours,
                "nri": theirs,
                "counties": len(both),
                "spearman": both[ours].corr(both[theirs], method="spearman"),
                "pearson_log": logs[ours].corr(logs[theirs]),
                "median_ratio": float(np.exp(log_ratio.median())),
                "log_mae_after_median_scaling": float(
                    (log_ratio - log_ratio.median()).abs().mean()
                ),
            }
        )
    return pd.DataFrame(rows)
