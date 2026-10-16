"""Extreme heat hazard multipliers from NEX-GDDP-CMIP6 (MPI-ESM1-2-HR).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and whose heat index
exceeds 298 K. HM = max(1, projected event-days / historical days over percentile), per county.
"""

import warnings

import numpy as np
import pandas as pd

from fri_rebuild import inputs

HEAT_INDEX_FLOOR_C = 298.0 - 273.15
PERCENTILES = {"N95": 95, "N99": 99}
HALF_WINDOW = 7


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


def year_length(n_days: int):
    for per in (360, 365):
        if n_days % per == 0:
            return per
    return None


def calendar_thresholds(history: np.ndarray, pcts):
    """Per-calendar-day percentile thresholds: dict pct -> (per, cells), or None."""
    per = year_length(history.shape[0])
    if per is None:
        return None, None
    years = history.shape[0] // per
    h = history.reshape(years, per, history.shape[1])
    out = {p: np.empty((per, history.shape[1]), dtype=np.float32) for p in pcts}
    offsets = np.arange(-HALF_WINDOW, HALF_WINDOW + 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for d in range(per):
            idx = (d + offsets) % per
            sample = h[:, idx, :].reshape(-1, history.shape[1])
            q = np.nanpercentile(sample, list(pcts), axis=0)
            for i, p in enumerate(pcts):
                out[p][d] = q[i]
    return out, per


def exceed(series: np.ndarray, thr: np.ndarray, per) -> np.ndarray:
    """Boolean (days, cells): series above threshold. thr is (cells,) or (per, cells)."""
    if thr.ndim == 1:
        return series > thr
    n = series.shape[0]
    if n % per != 0:
        full = np.tile(thr, (n // per + 1, 1))[:n]
        return series > full
    years = n // per
    return (series.reshape(years, per, -1) > thr[None]).reshape(n, -1)


def event_days(scenario: str, period: str, thr, per) -> np.ndarray:
    """Count of days per cell above the tasmin threshold and the heat index floor."""
    tasmin = inputs.daily("tasmin", scenario, period)
    over = exceed(tasmin, thr, per)
    del tasmin
    hot_enough = heat_index_c(
        inputs.daily("tas", scenario, period), inputs.daily("hurs", scenario, period)
    )
    return (over & (hot_enough > HEAT_INDEX_FLOOR_C)).sum(axis=0).astype(float)


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.county_weights()
    totals = weights @ np.nan_to_num(values)
    return totals / np.asarray(weights.sum(axis=1)).ravel()


def hazard_multipliers() -> pd.DataFrame:
    """Columns EXHT_N95_<scenario>_HM and EXHT_N99_<scenario>_HM, indexed by county FIPS."""
    _, fips = inputs.county_weights()
    history = inputs.daily("tasmin", "historical", "historical")
    cal, per = calendar_thresholds(history, list(PERCENTILES.values()))
    result = {}
    for name, percentile in PERCENTILES.items():
        if cal is None:
            thr = np.nanpercentile(history, percentile, axis=0)
            per_used = None
        else:
            thr = cal[percentile]
            per_used = per
        # Denominator: historical days with tasmin over the percentile only.
        past_counts = exceed(history, thr, per_used).sum(axis=0).astype(float)
        past = county_mean(past_counts)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                future = county_mean(event_days(ssp, period, thr, per_used))
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.where(past > 0, future / past, np.nan)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
