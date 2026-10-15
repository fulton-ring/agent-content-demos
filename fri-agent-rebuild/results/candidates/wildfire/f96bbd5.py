"""Wildfire hazard multipliers from NEX-GDDP-CMIP6 Fire Weather Index and LANDFIRE fuels.

FRI Technical Documentation, Section 8: HM = (FWI_scenario / FWI_historic) ** gamma, where gamma
is the coefficient on log historic FWI in a log-log regression of NRI county EAL on FWI with
spatial fixed effects and fuel-type shares as controls.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

PERIODS = ("MID", "LATE")
ENSEMBLE = "MME75"
VARIABLE = "FWI_P95"


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.county_weights()
    valid = np.isfinite(values)
    totals = weights @ np.where(valid, values, 0.0)
    covered = weights @ valid.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return totals / covered


def period_cells(scenario: str, period: str) -> np.ndarray:
    return np.nanmean(
        inputs.fwi(scenario, period, variable=VARIABLE, ensemble=ENSEMBLE), axis=0
    )


def elasticity(historic_fwi: pd.Series) -> float:
    """gamma: OLS of ln(wildfire EAL) on ln(FWI), fuel shares and ln(burnable share)."""
    baseline = inputs.baseline()
    all_fuels = inputs.county_fuel_shares()
    fuels = all_fuels.drop(columns="nonburnable")
    burnable = (1.0 - all_fuels["nonburnable"]).clip(lower=1e-3)
    eal = baseline["WFIR_EALT"]
    usable = (eal > 0) & (historic_fwi > 0) & fuels.notna().all(axis=1) & burnable.notna()
    design = pd.concat(
        [
            historic_fwi[usable].map(np.log).rename("log_fwi"),
            fuels[usable],
            np.log(burnable[usable]).rename("log_burnable"),
        ],
        axis=1,
    ).assign(const=1.0)
    coefficients, *_ = np.linalg.lstsq(
        design.to_numpy(), np.log(eal[usable].to_numpy()), rcond=None
    )
    return float(coefficients[0])


def hazard_multipliers() -> pd.DataFrame:
    """Columns WFIR_<period>_<warming>_HM indexed by county FIPS."""
    weights, fips = inputs.county_weights()
    hist_cells = period_cells("historical", "historical")
    historic = pd.Series(county_mean(hist_cells), index=fips)
    gamma = elasticity(historic)
    county_hist = historic.to_numpy()
    result = {}
    for warming, ssp in inputs.SSP.items():
        for period in PERIODS:
            fut_cells = period_cells(ssp, period)
            valid = np.isfinite(hist_cells) & np.isfinite(fut_cells) & (hist_cells > 0)
            h_g = np.where(valid, np.where(valid, hist_cells, 1.0) ** gamma, 0.0)
            f_g = np.where(valid, np.where(valid, fut_cells, 1.0) ** gamma, 0.0)
            num = weights @ f_g
            den = weights @ h_g
            with np.errstate(invalid="ignore", divide="ignore"):
                hm = num / den
            # fall back to ratio of county means where cell aggregation is undefined
            future_county = county_mean(fut_cells)
            with np.errstate(invalid="ignore", divide="ignore"):
                fallback = (future_county / county_hist) ** gamma
            hm = np.where(np.isfinite(hm) & (den > 0), hm, fallback)
            result[f"WFIR_{period}_{warming}_HM"] = hm
    return pd.DataFrame(result, index=fips)
