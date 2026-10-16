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

FEMA_REGION = {
    "CT": 1, "ME": 1, "MA": 1, "NH": 1, "RI": 1, "VT": 1,
    "NJ": 2, "NY": 2, "PR": 2, "VI": 2,
    "DE": 3, "DC": 3, "MD": 3, "PA": 3, "VA": 3, "WV": 3,
    "AL": 4, "FL": 4, "GA": 4, "KY": 4, "MS": 4, "NC": 4, "SC": 4, "TN": 4,
    "IL": 5, "IN": 5, "MI": 5, "MN": 5, "OH": 5, "WI": 5,
    "AR": 6, "LA": 6, "NM": 6, "OK": 6, "TX": 6,
    "IA": 7, "KS": 7, "MO": 7, "NE": 7,
    "CO": 8, "MT": 8, "ND": 8, "SD": 8, "UT": 8, "WY": 8,
    "AZ": 9, "CA": 9, "HI": 9, "NV": 9,
    "AK": 10, "ID": 10, "OR": 10, "WA": 10,
}


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.county_weights()
    valid = np.isfinite(values)
    totals = weights @ np.where(valid, values, 0.0)
    covered = weights @ valid.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return totals / covered


def cell_fwi(scenario: str, period: str) -> np.ndarray:
    return np.nanmean(
        inputs.fwi(scenario, period, ensemble=ENSEMBLE), axis=0
    ).astype(np.float64)


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
    hist_cells = cell_fwi("historical", "historical")
    historic = pd.Series(county_mean(hist_cells), index=fips)
    gamma = elasticity(historic)
    hist_ok = np.isfinite(hist_cells) & (hist_cells > 0)
    hist_pow = np.where(hist_ok, np.power(np.where(hist_ok, hist_cells, 1.0), gamma), 0.0)
    result = {}
    for warming, ssp in inputs.SSP.items():
        for period in PERIODS:
            fut = cell_fwi(ssp, period)
            ok = hist_ok & np.isfinite(fut) & (fut >= 0)
            fut_pow = np.where(ok, np.power(np.where(ok, fut, 0.0), gamma), 0.0)
            hp = np.where(ok, hist_pow, 0.0)
            num = weights @ fut_pow
            den = weights @ hp
            with np.errstate(invalid="ignore", divide="ignore"):
                hm = num / den
            fallback = (pd.Series(county_mean(fut), index=fips) / historic) ** gamma
            hm = pd.Series(np.asarray(hm).ravel(), index=fips)
            hm = hm.where(np.isfinite(hm) & (den.ravel() > 0 if hasattr(den, 'ravel') else True), fallback)
            result[f"WFIR_{period}_{warming}_HM"] = hm
    return pd.DataFrame(result, index=fips)
