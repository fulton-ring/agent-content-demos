import numpy as np
import pandas as pd

from fri_rebuild import inputs

FLOOR_C = 296.22 - 273.15
PERCENTILES = {"L95": 95, "L99": 99}


def county_hist(counts: np.ndarray) -> np.ndarray:
    """Area-weighted county histogram (bins x counties) from per-cell histograms."""
    weights, _ = inputs.loca2_county_weights()
    values = counts[:-1].astype(np.float64)
    out = weights @ values.T
    return np.asarray(out).T


def percentile_position(values: np.ndarray, percentile: float) -> np.ndarray:
    cumulative = np.cumsum(values, axis=0)
    target = cumulative[-1] * percentile / 100
    b = np.argmax(cumulative >= target[None, :] - 1e-9 * np.maximum(cumulative[-1], 1.0)[None, :], axis=0)
    cols = np.arange(values.shape[1])
    in_bin = values[b, cols]
    cum_b = cumulative[b, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        frac_above = np.where(in_bin > 0, (cum_b - target) / in_bin, 0.0)
    frac_above = np.clip(frac_above, 0.0, 1.0)
    return b + (1.0 - frac_above)


def days_above_pos(values: np.ndarray, pos: np.ndarray) -> np.ndarray:
    nb = values.shape[0]
    b = np.clip(np.floor(pos).astype(np.int64), 0, nb - 1)
    frac_above = 1.0 - (pos - b)
    above = np.arange(nb)[:, None] > b[None, :]
    days = (values * above).sum(axis=0)
    cols = np.arange(values.shape[1])
    days = days + frac_above * values[b, cols]
    valid = values.sum(axis=0) > 0
    return np.where(valid, days, np.nan)


def hazard_multipliers() -> pd.DataFrame:
    _, fips = inputs.loca2_county_weights()
    edges, history = inputs.loca2_histogram("historical", "historical")
    edges = np.asarray(edges, dtype=float)
    floor_bin = int(np.searchsorted(edges, FLOOR_C, side="right") - 1)
    width = edges[floor_bin + 1] - edges[floor_bin]
    floor_pos = floor_bin + (FLOOR_C - edges[floor_bin]) / width
    hist_c = county_hist(history)
    del history
    result = {}
    for name, percentile in PERCENTILES.items():
        threshold_pos = percentile_position(hist_c, percentile)
        past = days_above_pos(hist_c, threshold_pos)
        event_pos = np.maximum(threshold_pos, floor_pos)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                _, counts = inputs.loca2_histogram(ssp, period)
                fut_c = county_hist(counts)
                del counts
                future = days_above_pos(fut_c, event_pos)
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.where(past > 0, future / past, np.nan)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
