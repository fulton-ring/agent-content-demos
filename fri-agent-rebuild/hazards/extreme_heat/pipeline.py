"""Extreme heat hazard multipliers from NEX-GDDP-CMIP6 (MPI-ESM1-2-HR).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and whose heat index
exceeds 298 K. HM = max(1, projected event-days / historical days over percentile), per county.
"""

import numpy as np
import pandas as pd
from scipy import sparse

from fri_rebuild import inputs

HEAT_INDEX_FLOOR_C = 298.0 - 273.15
PERCENTILES = {"N95": 95, "N99": 99}


def heat_index_c(temp_c: np.ndarray, humidity: np.ndarray) -> np.ndarray:
    """NWS heat index (Rothfusz regression with Steadman's simple formula below 80 F)."""
    t = temp_c * 9 / 5 + 32
    rh = np.clip(humidity, 0, 100)
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    full = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * rh
        - 0.22475541 * t * rh
        - 0.00683783 * t * t
        - 0.05481717 * rh * rh
        + 0.00122874 * t * t * rh
        + 0.00085282 * t * rh * rh
        - 0.00000199 * t * t * rh * rh
    )
    heat_index_f = np.where((simple + t) / 2 >= 80, full, simple)
    return (heat_index_f - 32) * 5 / 9


def event_days(scenario: str, period: str, thresholds: np.ndarray) -> np.ndarray:
    """Count of days per cell above the tasmin threshold and the heat index floor."""
    tasmin = inputs.daily("tasmin", scenario, period)
    hot_enough = heat_index_c(
        inputs.daily("tas", scenario, period), inputs.daily("hurs", scenario, period)
    )
    return ((tasmin > thresholds) & (hot_enough > HEAT_INDEX_FLOOR_C)).sum(axis=0).astype(float)


def area_mean(values: np.ndarray, weights: sparse.csr_matrix) -> np.ndarray:
    totals = weights @ np.nan_to_num(values)
    return totals / np.asarray(weights.sum(axis=1)).ravel()


def hazard_multipliers(areas: inputs.AreaWeights | None = None) -> pd.DataFrame:
    """Columns EXHT_N95_<scenario>_HM and EXHT_N99_<scenario>_HM.

    Indexed by county FIPS, or by the ids of `areas` when given.
    """
    weights, fips = areas or inputs.county_weights()
    history = inputs.daily("tasmin", "historical", "historical")
    result = {}
    for name, percentile in PERCENTILES.items():
        thresholds = np.nanpercentile(history, percentile, axis=0)
        # Denominator: historical days with tasmin over the percentile only.
        past_counts = (history > thresholds).sum(axis=0).astype(float)
        past = area_mean(past_counts, weights)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                future = area_mean(event_days(ssp, period, thresholds), weights)
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.where(past > 0, future / past, np.nan)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
