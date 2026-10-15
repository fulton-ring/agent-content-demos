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


def cell_fwi(scenario: str, period: str) -> np.ndarray:
    return np.nanmean(inputs.fwi(scenario, period), axis=0)


def elasticity(historic_fwi: pd.Series) -> float:
    """gamma: OLS of ln(wildfire EAL) on ln(FWI), fuel shares and state fixed effects."""
    baseline = inputs.baseline()
    fuels = inputs.county_fuel_shares().drop(columns="nonburnable")
    eal = baseline["WFIR_EALT"]
    usable = (eal > 0) & (historic_fwi > 0) & fuels.notna().all(axis=1)
    states = pd.get_dummies(baseline.loc[usable, "STATEABBRV"], drop_first=True, dtype=float)
    design = pd.concat(
        [historic_fwi[usable].map(np.log).rename("log_fwi"), fuels[usable], states], axis=1
    ).assign(const=1.0)
    coefficients, *_ = np.linalg.lstsq(
        design.to_numpy(), np.log(eal[usable].to_numpy()), rcond=None
    )
    return float(coefficients[0])


def hazard_multipliers() -> pd.DataFrame:
    """Columns WFIR_<period>_<warming>_HM indexed by county FIPS."""
    _, fips = inputs.county_weights()
    hist_cells = cell_fwi("historical", "historical")
    historic = pd.Series(county_mean(hist_cells), index=fips)
    gamma = elasticity(historic)
    result = {}
    for warming, ssp in inputs.SSP.items():
        for period in PERIODS:
            fut_cells = cell_fwi(ssp, period)
            with np.errstate(invalid="ignore", divide="ignore"):
                ratio = np.where(hist_cells > 0, fut_cells / hist_cells, np.nan)
                hm_cells = ratio ** gamma
            result[f"WFIR_{period}_{warming}_HM"] = pd.Series(county_mean(hm_cells), index=fips)
    return pd.DataFrame(result, index=fips)
