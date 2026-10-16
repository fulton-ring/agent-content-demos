"""Extreme heat hazard multipliers from LOCA2 (MPI-ESM1-2-HR, 1/16 degree).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and, for LOCA2 (which has
no humidity), exceeds 296.22 K. HM = max(1, projected event-days / historical days over the nth
percentile), per county.

Here the cell histograms are pooled (area weighted) to county histograms first; the percentile
and floor are then placed by linear interpolation inside their 0.1 C histogram bin.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

FLOOR_C = 296.22 - 273.15
PERCENTILES = {"L95": 95, "L99": 99}


def percentile_position(values: np.ndarray, percentile: float) -> np.ndarray:
    """Continuous bin-coordinate position of each column's percentile (bin index + fraction)."""
    cumulative = np.cumsum(values, axis=0)
    target = cumulative[-1] * percentile / 100
    b = np.argmax(cumulative >= target, axis=0)
    cols = np.arange(values.shape[1])
    in_bin = values[b, cols]
    cum_b = cumulative[b, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        frac_above = np.where(in_bin > 0, (cum_b - target) / in_bin, 0.0)
    frac_above = np.clip(frac_above, 0.0, 1.0)
    return b + (1.0 - frac_above)


def days_above_pos(values: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """Days per column above continuous position `pos`, uniform within a bin."""
    nb = values.shape[0]
    b = np.clip(np.floor(pos).astype(np.int64), 0, nb - 1)
    frac_above = 1.0 - (pos - b)
    above = np.arange(nb)[:, None] > b[None, :]
    days = (values * above).sum(axis=0)
    cols = np.arange(values.shape[1])
    days = days + frac_above * values[b, cols]
    valid = values.sum(axis=0) > 0
    return np.where(valid, days, np.nan)


def county_histograms(counts: np.ndarray) -> np.ndarray:
    """Area-weighted pooled histogram per county: bins x counties (float64)."""
    weights, _ = inputs.loca2_county_weights()
    values = counts[:-1].astype(np.float64)
    pooled = weights @ values.T  # counties x bins
    return np.asarray(pooled).T


def hazard_multipliers() -> pd.DataFrame:
    """Columns EXHT_L95_<period>_<warming>_HM and EXHT_L99_..., indexed by county FIPS."""
    _, fips = inputs.loca2_county_weights()
    edges, history = inputs.loca2_histogram("historical", "historical")
    edges = np.asarray(edges, dtype=float)
    floor_bin = int(np.searchsorted(edges, FLOOR_C, side="right") - 1)
    width = edges[floor_bin + 1] - edges[floor_bin]
    floor_pos = floor_bin + (FLOOR_C - edges[floor_bin]) / width
    hist_county = county_histograms(history)
    del history
    future_hists = {}
    for warming, ssp in inputs.SSP.items():
        for period in ("MID", "LATE"):
            _, counts = inputs.loca2_histogram(ssp, period)
            future_hists[(warming, period)] = county_histograms(counts)
            del counts
    result = {}
    for name, percentile in PERCENTILES.items():
        threshold_pos = percentile_position(hist_county, percentile)
        past = days_above_pos(hist_county, threshold_pos)
        event_pos = np.maximum(threshold_pos, floor_pos)
        for (warming, period), fh in future_hists.items():
            future = days_above_pos(fh, event_pos)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(past > 0, future / past, np.nan)
            result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
