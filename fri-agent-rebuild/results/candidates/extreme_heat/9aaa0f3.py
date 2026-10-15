"""Extreme heat hazard multipliers from NEX-GDDP-CMIP6 (MPI-ESM1-2-HR).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and whose heat index
exceeds 298 K. HM = max(1, projected event-days / historical days over percentile), per county.

Order of operations: daily fields are area-averaged to counties first, then percentiles and
event-days are computed on the county series.
"""

import numpy as np
import pandas as pd

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


def county_series(variable: str, scenario: str, period: str) -> np.ndarray:
    """Area-weighted county mean of a daily variable: (days, counties) float32."""
    weights, _ = inputs.county_weights()
    weights = weights.tocsr()
    x = inputs.daily(variable, scenario, period)
    valid = np.isfinite(x).any(axis=0).astype(float)
    wsum = weights @ valid
    out = np.empty((x.shape[0], weights.shape[0]), dtype=np.float32)
    step = 1500
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(0, x.shape[0], step):
            chunk = np.nan_to_num(x[i:i + step]).astype(np.float64)
            tot = (weights @ chunk.T).T
            out[i:i + step] = (tot / wsum).astype(np.float32)
    del x
    return out


def event_days(scenario: str, period: str, thresholds: np.ndarray) -> np.ndarray:
    """Count of days per county above the tasmin threshold and the heat index floor."""
    tasmin = county_series("tasmin", scenario, period)
    hot_enough = heat_index_c(
        county_series("tas", scenario, period), county_series("hurs", scenario, period)
    )
    return ((tasmin > thresholds) & (hot_enough > HEAT_INDEX_FLOOR_C)).sum(axis=0).astype(float)


def hazard_multipliers() -> pd.DataFrame:
    """Columns EXHT_N95_<scenario>_HM and EXHT_N99_<scenario>_HM, indexed by county FIPS."""
    _, fips = inputs.county_weights()
    history = county_series("tasmin", "historical", "historical")
    result = {}
    for name, percentile in PERCENTILES.items():
        thresholds = np.nanpercentile(history, percentile, axis=0)
        # Denominator: historical days with tasmin over the percentile only.
        past = (history > thresholds).sum(axis=0).astype(float)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                future = event_days(ssp, period, thresholds)
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.where(past > 0, future / past, np.nan)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
