"""Wildfire hazard multipliers from NEX-GDDP-CMIP6 Fire Weather Index and LANDFIRE fuels.

FRI Technical Documentation, Section 8: HM = (FWI_scenario / FWI_historic) ** gamma, where gamma
is the coefficient on log historic FWI in a log-log regression of NRI county EAL on FWI with
spatial fixed effects and fuel-type shares as controls.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

PERIODS = ("MID", "LATE")


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.county_weights()
    valid = np.isfinite(values)
    totals = weights @ np.where(valid, values, 0.0)
    covered = weights @ valid.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return totals / covered


def period_fwi(scenario: str, period: str) -> np.ndarray:
    return county_mean(np.nanmean(inputs.fwi(scenario, period), axis=0))


FEMA_REGION = {
    **dict.fromkeys(["CT", "ME", "MA", "NH", "RI", "VT"], 1),
    **dict.fromkeys(["NJ", "NY"], 2),
    **dict.fromkeys(["DE", "DC", "MD", "PA", "VA", "WV"], 3),
    **dict.fromkeys(["AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"], 4),
    **dict.fromkeys(["IL", "IN", "MI", "MN", "OH", "WI"], 5),
    **dict.fromkeys(["AR", "LA", "NM", "OK", "TX"], 6),
    **dict.fromkeys(["IA", "KS", "MO", "NE"], 7),
    **dict.fromkeys(["CO", "MT", "ND", "SD", "UT", "WY"], 8),
    **dict.fromkeys(["AZ", "CA", "NV"], 9),
    **dict.fromkeys(["ID", "OR", "WA"], 10),
}


def elasticity(historic_fwi: pd.Series) -> float:
    """gamma: OLS of ln(wildfire EAL) on ln(FWI), fuel shares and state fixed effects."""
    baseline = inputs.baseline()
    fuels = inputs.county_fuel_shares().drop(columns="nonburnable")
    eal = baseline[[c for c in baseline.columns if c.endswith("_EALT")]].sum(axis=1)
    usable = (eal > 0) & (historic_fwi > 0) & fuels.notna().all(axis=1)
    states = pd.get_dummies(baseline.loc[usable, "STATEABBRV"], drop_first=True, dtype=float)
    design = pd.concat(
        [historic_fwi[usable].map(np.log).rename("log_fwi"), fuels[usable], states], axis=1
    ).assign(const=1.0)
    X = design.to_numpy()
    y = eal[usable].to_numpy()
    beta, *_ = np.linalg.lstsq(X, np.log(y), rcond=None)
    for _ in range(100):  # Poisson pseudo-ML (log link) by IRLS
        mu = np.exp(np.clip(X @ beta, -30, 30))
        z = X @ beta + (y - mu) / mu
        step, *_ = np.linalg.lstsq(X * np.sqrt(mu)[:, None], z * np.sqrt(mu), rcond=None)
        if np.max(np.abs(step - beta)) < 1e-8:
            beta = step
            break
        beta = step
    coefficients = beta
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
