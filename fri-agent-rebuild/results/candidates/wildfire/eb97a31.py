"""Wildfire hazard multipliers from NEX-GDDP-CMIP6 Fire Weather Index and LANDFIRE fuels.

FRI Technical Documentation, Section 8: HM = (FWI_scenario / FWI_historic) ** gamma, where gamma
is the coefficient on log historic FWI in a log-log regression of NRI county EAL on FWI with
spatial fixed effects and fuel-type shares as controls (estimated by maximum likelihood).
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

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


def period_fwi(scenario: str, period: str) -> np.ndarray:
    return county_mean(
        np.nanmean(inputs.fwi(scenario, period, ensemble=ENSEMBLE), axis=0)
    )


def elasticity(historic_fwi: pd.Series) -> float:
    """gamma: Poisson pseudo-ML of wildfire EAL on ln(FWI) and fuel shares (log link)."""
    baseline = inputs.baseline()
    fuels = inputs.county_fuel_shares().drop(columns="nonburnable")
    eal = baseline["WFIR_EALT"]
    usable = eal.notna() & (eal >= 0) & (historic_fwi > 0) & fuels.notna().all(axis=1)
    design = pd.concat(
        [historic_fwi[usable].map(np.log).rename("log_fwi"), fuels[usable]], axis=1
    ).assign(const=1.0)
    X = design.to_numpy()
    y = eal[usable].to_numpy().astype(float)
    y = y / y.mean()

    pos = y > 0
    b0, *_ = np.linalg.lstsq(X[pos], np.log(y[pos]), rcond=None)

    def obj(b):
        eta = np.clip(X @ b, -30, 30)
        mu = np.exp(eta)
        f = np.sum(mu - y * eta)
        g = X.T @ (mu - y)
        return f, g

    res = minimize(obj, b0, jac=True, method="L-BFGS-B", options={"maxiter": 2000})
    gamma = float(res.x[0])
    if not np.isfinite(gamma) or gamma <= 1.0:
        gamma = float(b0[0])
    return gamma


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
