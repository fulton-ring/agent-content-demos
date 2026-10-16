"""Extreme heat hazard multipliers from NEX-GDDP-CMIP6 (MPI-ESM1-2-HR).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and whose heat index
exceeds 298 K. HM = max(1, projected event-days / historical event-days), per county.

This variant computes the ratio per cell (floored at 1), then area-averages per county.
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


def event_days(scenario: str, period: str, thresholds: np.ndarray) -> np.ndarray:
    """Count of days per cell above the tasmin threshold and the heat index floor."""
    tasmin = inputs.daily("tasmin", scenario, period)
    hot_enough = heat_index_c(
        inputs.daily("tas", scenario, period), inputs.daily("hurs", scenario, period)
    )
    return ((tasmin > thresholds) & (hot_enough > HEAT_INDEX_FLOOR_C)).sum(axis=0).astype(float)


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.county_weights()
    totals = weights @ np.nan_to_num(values)
    return totals / np.asarray(weights.sum(axis=1)).ravel()


def county_mean_valid(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Area-weighted mean over valid cells only; NaN where a county has none."""
    weights, _ = inputs.county_weights()
    v = valid.astype(float)
    totals = weights @ np.where(valid, values, 0.0)
    denom = weights @ v
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 0, totals / denom, np.nan)


def hazard_multipliers() -> pd.DataFrame:
    """Columns EXHT_N95_<scenario>_HM and EXHT_N99_<scenario>_HM, indexed by county FIPS."""
    _, fips = inputs.county_weights()
    history = inputs.daily("tasmin", "historical", "historical")
    result = {}
    for name, percentile in PERCENTILES.items():
        thresholds = np.nanpercentile(history, percentile, axis=0)
        past_cells = event_days("historical", "historical", thresholds)
        past = county_mean(past_cells)
        valid = (past_cells > 0) & np.isfinite(thresholds)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                future_cells = event_days(ssp, period, thresholds)
                future = county_mean(future_cells)
                with np.errstate(divide="ignore", invalid="ignore"):
                    cell_ratio = np.where(valid, future_cells / np.where(valid, past_cells, 1.0), 0.0)
                cell_hm = np.maximum(1.0, cell_ratio)
                hm = county_mean_valid(cell_hm, valid)
                with np.errstate(divide="ignore", invalid="ignore"):
                    fallback = np.where(past > 0, future / past, np.nan)
                hm = np.where(np.isfinite(hm), hm, np.maximum(1.0, fallback))
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, hm)
    return pd.DataFrame(result, index=fips)
