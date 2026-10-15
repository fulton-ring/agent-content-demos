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
    return np.nanmean(inputs.fwi(scenario, period, ensemble=ENSEMBLE), axis=0)


def elasticity(historic_fwi: pd.Series) -> float:
    """gamma: OLS of ln(wildfire EAL) on ln(FWI) and fuel shares, no spatial fixed effects."""
    baseline = inputs.baseline()
    fuels = inputs.county_fuel_shares().drop(columns="nonburnable")
    eal = baseline["WFIR_EALT"]
    usable = (eal > 0) & (historic_fwi > 0) & fuels.notna().all(axis=1)
    design = pd.concat(
        [historic_fwi[usable].map(np.log).rename("log_fwi"), fuels[usable]], axis=1
    ).assign(const=1.0)
    coefficients, *_ = np.linalg.lstsq(
        design.to_numpy(), np.log(eal[usable].to_numpy()), rcond=None
    )
    return float(coefficients[0])


def hazard_multipliers() -> pd.DataFrame:
    """Columns WFIR_<period>_<warming>_HM indexed by county FIPS."""
    _, fips = inputs.county_weights()
    hist_cell = cell_fwi("historical", "historical")
    historic = pd.Series(county_mean(hist_cell), index=fips)
    gamma = elasticity(historic)
    hist_ok = np.isfinite(hist_cell) & (hist_cell > 0)
    safe_hist = np.where(hist_ok, hist_cell, 1.0)
    result = {}
    for warming, ssp in inputs.SSP.items():
        for period in PERIODS:
            fut_cell = cell_fwi(ssp, period)
            with np.errstate(invalid="ignore", divide="ignore"):
                cell_hm = (fut_cell / safe_hist) ** gamma
            cell_hm = np.where(hist_ok & np.isfinite(cell_hm), cell_hm, np.nan)
            county_hm = county_mean(cell_hm)
            fallback = (
                pd.Series(county_mean(fut_cell), index=fips) / historic
            ) ** gamma
            hm = pd.Series(county_hm, index=fips)
            hm = hm.where(hm.notna(), fallback)
            result[f"WFIR_{period}_{warming}_HM"] = hm
    return pd.DataFrame(result, index=fips)
