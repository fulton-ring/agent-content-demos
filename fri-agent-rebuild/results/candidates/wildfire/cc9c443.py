"""Wildfire hazard multipliers from NEX-GDDP-CMIP6 Fire Weather Index and LANDFIRE fuels.

FRI Technical Documentation, Section 8: HM = (FWI_scenario / FWI_historic) ** gamma, where gamma
is the coefficient on log historic FWI in a log-log regression of NRI county EAL on FWI with
spatial fixed effects and fuel-type shares as controls.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

PERIODS = ("MID", "LATE")

FRI_HAZARD_EAL = ("CFLD_EALT", "HWAV_EALT", "HRCN_EALT", "RFLD_EALT", "WFIR_EALT")


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.county_weights()
    valid = np.isfinite(values)
    totals = weights @ np.where(valid, values, 0.0)
    covered = weights @ valid.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return totals / covered


def period_fwi(scenario: str, period: str) -> np.ndarray:
    return county_mean(np.nanmean(inputs.fwi(scenario, period), axis=0))


def total_eal(baseline: pd.DataFrame) -> pd.Series:
    cols = [c for c in FRI_HAZARD_EAL if c in baseline.columns]
    if "WFIR_EALT" not in cols:
        return baseline["WFIR_EALT"]
    return baseline[cols].fillna(0.0).sum(axis=1)


def elasticity(historic_fwi: pd.Series) -> float:
    """gamma: OLS of ln(total EAL) on ln(FWI) and fuel shares, no spatial fixed effects."""
    baseline = inputs.baseline()
    fuels = inputs.county_fuel_shares().drop(columns="nonburnable")
    eal = total_eal(baseline)
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
    historic = pd.Series(period_fwi("historical", "historical"), index=fips)
    gamma = elasticity(historic)
    result = {}
    for warming, ssp in inputs.SSP.items():
        for period in PERIODS:
            future = pd.Series(period_fwi(ssp, period), index=fips)
            result[f"WFIR_{period}_{warming}_HM"] = (future / historic) ** gamma
    return pd.DataFrame(result, index=fips)
