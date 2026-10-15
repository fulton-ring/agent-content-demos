"""Extreme heat hazard multipliers from NEX-GDDP-CMIP6 (MPI-ESM1-2-HR).

Event-day: tasmin above historical (1976-2005) 95th or 99th percentile. Variant: the heat index
filter is not applied (test of open question 2). HM = max(1, projected days / historical days).
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

PERCENTILES = {"N95": 95, "N99": 99}


def event_days(scenario: str, period: str, thresholds: np.ndarray) -> np.ndarray:
    """Count of days per cell above the tasmin threshold."""
    tasmin = inputs.daily("tasmin", scenario, period)
    return (tasmin > thresholds).sum(axis=0).astype(float)


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.county_weights()
    totals = weights @ np.nan_to_num(values)
    return totals / np.asarray(weights.sum(axis=1)).ravel()


def hazard_multipliers() -> pd.DataFrame:
    """Columns EXHT_N95_<scenario>_HM and EXHT_N99_<scenario>_HM, indexed by county FIPS."""
    _, fips = inputs.county_weights()
    history = inputs.daily("tasmin", "historical", "historical")
    result = {}
    for name, percentile in PERCENTILES.items():
        thresholds = np.nanpercentile(history, percentile, axis=0)
        past_counts = (history > thresholds).sum(axis=0).astype(float)
        past = county_mean(past_counts)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                future = county_mean(event_days(ssp, period, thresholds))
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.where(past > 0, future / past, np.nan)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
