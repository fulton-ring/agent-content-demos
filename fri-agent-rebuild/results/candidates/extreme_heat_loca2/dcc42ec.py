import numpy as np
import pandas as pd

from fri_rebuild import inputs

FLOOR_C = 296.22 - 273.15
PERCENTILES = {"L95": 95, "L99": 99}


def percentile_position(counts, percentile):
    values = counts[:-1].astype(np.int64)
    cumulative = np.cumsum(values, axis=0)
    target = cumulative[-1] * percentile / 100
    b = np.argmax(cumulative >= target, axis=0)
    cols = np.arange(values.shape[1])
    in_bin = values[b, cols].astype(float)
    cum_b = cumulative[b, cols].astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac_above = np.where(in_bin > 0, (cum_b - target) / in_bin, 0.0)
    frac_above = np.clip(frac_above, 0.0, 1.0)
    return b + (1.0 - frac_above)


def days_above_pos(counts, pos):
    values = counts[:-1].astype(np.int64)
    nb = values.shape[0]
    b = np.clip(np.floor(pos).astype(np.int64), 0, nb - 1)
    frac_above = 1.0 - (pos - b)
    above = np.arange(nb)[:, None] > b[None, :]
    days = (values * above).sum(axis=0).astype(float)
    cols = np.arange(values.shape[1])
    days = days + frac_above * values[b, cols]
    valid = counts[:-1].sum(axis=0) > 0
    return np.where(valid, days, np.nan)


def county_mean(values):
    weights, _ = inputs.loca2_county_weights()
    valid = np.isfinite(values)
    totals = weights @ np.where(valid, values, 0.0)
    covered = weights @ valid.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return totals / covered


def hazard_multipliers():
    _, fips = inputs.loca2_county_weights()
    edges, history = inputs.loca2_histogram("historical", "historical")
    edges = np.asarray(edges, dtype=float)
    floor_bin = int(np.searchsorted(edges, FLOOR_C, side="right") - 1)
    width = edges[floor_bin + 1] - edges[floor_bin]
    floor_pos = floor_bin + (FLOOR_C - edges[floor_bin]) / width
    result = {}
    for name, percentile in PERCENTILES.items():
        threshold_pos = percentile_position(history, percentile)
        past = days_above_pos(history, threshold_pos)
        event_pos = np.maximum(threshold_pos, floor_pos)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                _, counts = inputs.loca2_histogram(ssp, period)
                future = days_above_pos(counts, event_pos)
                with np.errstate(divide="ignore", invalid="ignore"):
                    cell_ratio = np.where(past > 0, future / past, np.nan)
                ratio = county_mean(cell_ratio)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
